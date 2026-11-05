"""Lifecycle regressions use the real Endstone 0.11.15 API test harness."""
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import test_runtime
from test_music import FakeItem, FakePlayer
from endstone.event import PlayerInteractEvent

class Lifecycle(unittest.TestCase):
    def setUp(self):
        test_runtime.RuntimeTests.setUp(self)
        self.plugin.on_enable()
        self.plugin.playlists.put("party", [{"sound": "custom.a", "duration": 2}], True)
        (self.plugin.data_path / "global_sounds_registry.json").write_text('["custom.a"]')
        self.player.has_permission = lambda permission: True
        self.player.send_message = Mock()

    def start(self):
        self.plugin.start_playlist(self.player, "party")

    def test_pending_join_cannot_interrupt_global(self):
        self.plugin._join_music(self.player)
        self.start()
        before = list(self.player.calls)
        self.scheduler.advance(20)
        self.assertEqual(self.player.calls, before)
        self.assertIsNotNone(self.plugin.music.session)

    def test_legacy_trigger_does_not_interrupt_global(self):
        self.start()
        self.plugin.cmusic_config["triggers"] = [{"mode": "item_only", "item": "minecraft:stick", "sound": "custom.a"}]
        self.plugin._interact_music(types.SimpleNamespace(player=self.player, item=FakeItem("minecraft:stick"),
            block=None, action=PlayerInteractEvent.Action.RIGHT_CLICK_AIR))
        self.assertEqual(set(self.plugin.playback.sources), {"operator:global"})

    def test_disable_stops_global_and_invalidates_pending_join(self):
        self.plugin._join_music(self.player)
        self.start()
        self.plugin.on_disable()
        before = list(self.player.calls)
        self.scheduler.advance(40)
        self.assertEqual(self.player.calls, before)
        self.assertIsNone(self.plugin.music.session)
        self.assertFalse(self.plugin.playback.sources)

    def test_reload_valid_stops_invalid_keeps_global(self):
        self.start()
        self.plugin.cmusic_config_file.write_text("{bad")
        self.plugin.on_command(self.player, types.SimpleNamespace(name="cmusic"), ["reload"])
        self.assertIsNotNone(self.plugin.music.session)
        self.plugin.cmusic_config_file.write_text(json.dumps(self.config))
        self.plugin.on_command(self.player, types.SimpleNamespace(name="cmusic"), ["reload"])
        self.assertIsNone(self.plugin.music.session)

    def test_global_late_listener_seeks_without_restarting_existing_listener(self):
        clock = [0.0]
        self.plugin.playback.clock = self.plugin.music.clock = lambda: clock[0]
        self.plugin.audio_adapter.play = Mock(wraps=self.plugin.audio_adapter.play)
        self.start()
        before = list(self.player.calls)
        second = FakePlayer("Late", "nether", x=10000)
        self.server.online_players.append(second)
        clock[0] = 0.5
        self.plugin._music_tick()
        self.assertEqual(self.player.calls, before)
        call = self.plugin.audio_adapter.play.call_args
        self.assertIs(call.args[0], second)
        self.assertEqual(call.args[2], "endstone_music.global.custom.a")
        self.assertEqual(call.kwargs["position_seconds"], 0.5)

    def test_revoked_operator_cannot_stop_from_runtime_menu(self):
        self.start()
        self.player.has_permission = lambda permission: False
        self.plugin._runtime_command(self.player, ["stop"])
        self.assertIsNotNone(self.plugin.music.session)
        self.assertIn("operator:global", self.plugin.playback.sources)

if __name__ == "__main__":
    unittest.main(verbosity=2)
