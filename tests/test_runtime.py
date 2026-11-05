import builtins
import copy
import heapq
import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from test_music import FakePlayer, FakeLocation, FakeItem
from endstone_music import EndstoneMusicPlugin
from endstone.plugin import PluginDescription
from endstone.event import PlayerInteractEvent


class Scheduler:
    def __init__(self):
        self.now = self.sequence = 0
        self.queue, self.cancelled = [], set()

    def run_task(self, plugin, callback, delay=0, period=0):
        self.sequence += 1
        heapq.heappush(self.queue, (self.now + delay, self.sequence, callback, period))
        return types.SimpleNamespace(task_id=self.sequence)

    def cancel_task(self, task_id):
        self.cancelled.add(task_id)

    def advance(self, ticks):
        end = self.now + ticks
        while self.queue and self.queue[0][0] <= end:
            self.now, sequence, callback, period = heapq.heappop(self.queue)
            if sequence not in self.cancelled:
                callback()
                if period and sequence not in self.cancelled:
                    heapq.heappush(self.queue, (self.now + period, sequence, callback, period))
        self.now = end


class Harness(EndstoneMusicPlugin):
    @property
    def data_folder(self):
        return self.test_folder

    @property
    def logger(self):
        return self.test_logger

    @property
    def server(self):
        return self.test_server

    @property
    def plugin_loader(self):
        return None

    @property
    def is_enabled(self):
        return True


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="music-runtime-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.player = FakePlayer()
        self.scheduler = Scheduler()
        self.plugin = Harness()
        self.plugin.test_folder = self.root / "plugins" / "music"
        self.plugin.test_folder.mkdir(parents=True)
        self.plugin.test_logger = types.SimpleNamespace(info=Mock(), warning=Mock(), error=Mock())
        self.server = types.SimpleNamespace(
            minecraft_version="26.60", protocol_version=2225, version="0.11.15",
            scheduler=self.scheduler, online_players=[self.player],
            command_sender=types.SimpleNamespace(send_message=Mock(), has_permission=lambda permission: True), plugin_manager=Mock(),
            level=types.SimpleNamespace(dimensions=[]),
        )
        self.server.get_player = lambda name: next((p for p in self.server.online_players if p.name == name), None)
        self.plugin.test_server = self.server
        self.plugin._description = PluginDescription(name="music", version=EndstoneMusicPlugin.version, api_version="0.11")
        self.config = {"target_world_name": "Test World", "triggers": [],
                       "tracks": {"a": {"sound": "custom.a", "duration": 10}},
                       "albums": {"album": {"tracks": ["a"]}},
                       "join_sound": {"enabled": True, "sound": "custom.a", "duration": 5}}
        (self.plugin.test_folder / "config.json").write_text(json.dumps(self.config))
        self.addCleanup(self.plugin.on_disable)

    def test_startup_registers_hooks_without_importing_or_downloading_audio_tools(self):
        original = builtins.__import__

        def guarded(name, *args, **kwargs):
            if name.startswith(("static_ffmpeg", "pydub")):
                raise AssertionError("Audio dependencies must not be imported during startup")
            return original(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=guarded):
            self.plugin.on_enable()
        self.assertEqual(self.server.plugin_manager.register_event.call_count, 5)
        self.assertTrue(self.plugin.audio_adapter.supported)
        self.plugin.logger.error.assert_not_called()

    def test_join_plays_once_after_login_delay(self):
        self.plugin.on_enable()
        self.plugin._join_music(self.player)
        self.scheduler.advance(19)
        self.assertFalse(self.player.calls)
        self.scheduler.advance(1)
        self.assertEqual([call[:2] for call in self.player.calls], [("play", "custom.a")])

    def test_legacy_per_player_join_sound_overrides_disabled_default(self):
        self.config["join_sound"]["enabled"] = False
        self.config["player_join_sounds"] = {self.player.name: {"sound": "custom.a", "duration": 3}}
        (self.plugin.test_folder / "config.json").write_text(json.dumps(self.config))
        self.plugin.on_enable()
        self.plugin._join_music(self.player)
        self.scheduler.advance(20)
        self.assertEqual([call[:2] for call in self.player.calls], [("play", "custom.a")])

    def test_quit_and_rejoin_invalidates_old_delayed_join(self):
        self.plugin.on_enable()
        self.plugin._join_music(self.player)
        self.plugin.on_player_quit(types.SimpleNamespace(player=self.player))
        replacement = FakePlayer()
        self.server.online_players = [replacement]
        self.plugin._join_music(replacement)
        self.scheduler.advance(20)
        self.assertFalse(self.player.calls)
        self.assertEqual(len(replacement.calls), 1)

    def test_disable_prevents_delayed_join_and_stops_only_owned_music(self):
        self.plugin.on_enable()
        self.plugin._join_music(self.player)
        self.plugin.on_disable()
        self.scheduler.advance(100)
        self.assertFalse(self.player.calls)
        self.assertFalse(self.plugin.playback.sources)

    def test_left_click_never_activates_music(self):
        self.plugin.on_enable()
        event = types.SimpleNamespace(action=PlayerInteractEvent.Action.LEFT_CLICK_BLOCK, player=self.player)
        self.plugin._interact_music(event)
        self.assertFalse(self.player.calls)

    def test_cancelled_custom_insertion_does_not_fall_through_to_vanilla_on_storage_error(self):
        self.plugin.on_enable()
        disc = self.plugin.library.discs["album"]
        block = types.SimpleNamespace(type="minecraft:jukebox", dimension=self.player.location.dimension, x=0, y=64, z=0)
        event = types.SimpleNamespace(action=PlayerInteractEvent.Action.RIGHT_CLICK_BLOCK, player=self.player,
                                      block=block, item=FakeItem(), cancel=Mock())
        with patch.object(self.plugin.library, "disc_from_item", return_value=disc), patch.object(self.plugin.jukebox_controller, "handle_interact", side_effect=OSError("disk full")):
            self.plugin.on_player_interact(event)
        event.cancel.assert_called_once()
        self.plugin.logger.error.assert_called_once()

    def test_item_trigger_broadcast_is_played_once_for_each_player(self):
        self.config["triggers"] = [{"mode": "item_only", "item": "minecraft:stick", "sound": "custom.a", "broadcast": True}]
        (self.plugin.test_folder / "config.json").write_text(json.dumps(self.config))
        self.plugin.on_enable()
        second = FakePlayer("Other", "nether")
        self.server.online_players.append(second)
        self.plugin._interact_music(types.SimpleNamespace(action=PlayerInteractEvent.Action.RIGHT_CLICK_AIR,
                                                          player=self.player, block=None, item=FakeItem("minecraft:stick")))
        self.assertEqual(len(self.player.calls), 1)
        self.assertEqual(len(second.calls), 1)

    def _start_block_trigger(self, follow):
        self.config["triggers"] = [{"mode": "block_only", "block": "minecraft:stone", "sound": "custom.a", "follow_player": follow}]
        (self.plugin.test_folder / "config.json").write_text(json.dumps(self.config))
        self.plugin.on_enable()
        block = types.SimpleNamespace(type="minecraft:stone", dimension=self.player.location.dimension,
                                      location=FakeLocation(self.player.location.dimension), x=0, y=64, z=0)
        with patch("endstone.level.Location", FakeLocation):
            self.plugin._interact_music(types.SimpleNamespace(action=PlayerInteractEvent.Action.RIGHT_CLICK_BLOCK,
                                                              player=self.player, block=block, item=None))

    def test_following_block_trigger_continues_when_player_leaves(self):
        self._start_block_trigger(True)
        self.player.location.x = 10000
        self.plugin._music_tick()
        self.assertEqual([call[:2] for call in self.player.calls], [("play", "custom.a")])
        self.assertIn(self.player.unique_id, self.plugin.playback.voices)

    def test_positional_block_trigger_stops_outside_range(self):
        self._start_block_trigger(False)
        self.player.location.x = 10000
        self.plugin._music_tick()
        self.assertEqual(self.player.calls[-1], ("stop", "custom.a"))
        self.assertFalse(self.plugin.playback.voices)

    def test_malformed_reload_keeps_current_configuration_and_audio(self):
        self.plugin.on_enable()
        previous = copy.deepcopy(self.plugin.cmusic_config)
        self.plugin.playback.start("personal", (self.plugin.library.tracks["a"],), listener=self.player.unique_id)
        (self.plugin.test_folder / "config.json").write_text("broken")
        with self.assertRaises(ValueError):
            self.plugin._reload_music()
        self.assertEqual(self.plugin.cmusic_config, previous)
        self.assertIn("personal", self.plugin.playback.sources)

    def test_pack_generation_runs_off_thread_and_completion_poll_is_cancelled(self):
        (self.root / "worlds" / "Test World").mkdir(parents=True)
        self.plugin.on_enable()
        self.assertTrue(self.plugin._start_generation(self.server.command_sender))
        self.plugin._generation.result(timeout=5)
        old_poll = self.plugin._generation_poll.task_id
        self.assertTrue(self.plugin._start_generation(self.server.command_sender))
        self.assertEqual(self.plugin._generation_poll.task_id, old_poll)
        self.scheduler.advance(10)
        self.assertIsNone(self.plugin._generation)
        self.assertIsNone(self.plugin._generation_poll)
        self.assertIn(old_poll, self.scheduler.cancelled)
        self.scheduler.advance(100)
        self.plugin.logger.error.assert_not_called()

    def test_unsupported_runtime_still_allows_stored_disc_recovery_and_status(self):
        self.server.protocol_version = 2250
        self.plugin.on_enable()
        self.assertFalse(self.plugin.audio_adapter.supported)
        self.assertTrue(self.plugin._runtime_command(self.server.command_sender, ["status"]))
        self.plugin.logger.error.assert_not_called()


if __name__ == "__main__":
    unittest.main()
