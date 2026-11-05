"""Regression tests for the 26.60 adapter, playlist engine, and disc storage."""

import copy
import heapq
import inspect
import json
import math
import os
import struct
import sys
import tempfile
import types
import unittest
import wave
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from endstone_music.audio_adapter import SoundAdapter, SoundPayloadError, adapt_sound_payload, inspect_sound_payload
from endstone_music.library import Library, Track, atomic_json
from endstone_music.playback import PlaybackEngine, Position
from endstone_music.jukebox import JukeboxController, block_key
from endstone_music.pack_generator import PackGenerator


def varuint(value):
    data = bytearray()
    while value > 127:
        data.append((value & 127) | 128)
        value >>= 7
    return bytes(data + bytes([value]))


def sound_payload(sound="custom.first", volume=1, pitch=1, handle=None, offset=None):
    name = sound.encode()
    # Signed X/Z and unsigned Y are preserved, not reinterpreted, by the adapter.
    return (varuint(len(name)) + name + varuint(3) + varuint(64) + varuint(9)
            + struct.pack("<ff", volume, pitch) + varuint(0) + b"\x00"
            + (b"\x00" if handle is None else b"\x01" + struct.pack("<Q", handle))
            + (b"\x00" if offset is None else b"\x01" + struct.pack("<f", offset)))


class FakeLocation:
    def __init__(self, dimension, x=0, y=64, z=0):
        self.dimension, self.x, self.y, self.z = dimension, x, y, z


class FakeItem:
    def __init__(self, item_type="minecraft:music_disc_cat", amount=1, data=0):
        self.type, self.amount, self.data = item_type, amount, data
        self.disc_id = "album"


class FakeInventory:
    held_item_slot = 0

    def __init__(self):
        self.slots = {0: FakeItem()}

    @property
    def first_empty(self):
        return next((slot for slot in range(5) if self.slots.get(slot) is None), -1)

    def get_item(self, slot):
        return copy.deepcopy(self.slots.get(slot))

    def set_item(self, slot, item):
        self.slots[slot] = copy.deepcopy(item)


class FakePlayer:
    is_sneaking = False

    def __init__(self, name="Player", dimension="overworld", x=0):
        self.name = self.unique_id = name
        self.location = FakeLocation(types.SimpleNamespace(name=dimension), x=x)
        self.inventory = FakeInventory()
        self.calls = []
        self.messages = []

    def play_sound(self, location, sound, volume=1, pitch=1):
        self.calls.append(("play", sound, location, volume, pitch))

    def stop_sound(self, sound):
        self.calls.append(("stop", sound))

    def send_message(self, message):
        self.messages.append(message)


def fake_server(*players):
    return types.SimpleNamespace(minecraft_version="26.60", protocol_version=2225, version="0.11.15",
                                 online_players=list(players), get_player=lambda name: next((p for p in players if p.name == name), None))


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.player = FakePlayer()
        self.server = fake_server(self.player)
        self.now = 0.0
        self.adapter = SoundAdapter(self.server, Mock(), clock=lambda: self.now)

    def test_exact_runtime_gate(self):
        self.assertTrue(self.adapter.supported)
        for field, value in (("minecraft_version", "26.61"), ("protocol_version", 2250), ("version", "0.11.14")):
            server = fake_server()
            setattr(server, field, value)
            with self.subTest(field=field):
                adapter = SoundAdapter(server, Mock())
                with self.assertRaises(RuntimeError):
                    adapter.play(self.player, self.player.location, "custom.first")
        self.assertFalse(self.player.calls)

    def test_optional_handle_is_preserved_when_seeking(self):
        data = sound_payload(handle=0x123456789ABCDEF0, offset=1)
        result = adapt_sound_payload(data, position_seconds=12.5, bypass_range=True)
        self.assertIn(struct.pack("<Q", 0x123456789ABCDEF0), result)
        self.assertEqual(struct.unpack("<f", result[-4:])[0], 12.5)
        self.assertEqual(result[-14], 1)  # Bypass flag precedes optional handle flag.
        self.assertEqual(inspect_sound_payload(result)[0], "custom.first")

    def test_only_owned_matching_playback_packets_are_modified(self):
        self.adapter.play(self.player, self.player.location, "custom.first", position_seconds=7.25, bypass_range=True)
        unrelated = types.SimpleNamespace(packet_id=86, player=self.player, payload=sound_payload("random.orb"))
        before = unrelated.payload
        self.adapter.on_packet_send(unrelated)
        self.assertEqual(unrelated.payload, before)
        event = types.SimpleNamespace(packet_id=86, player=self.player, payload=sound_payload())
        self.adapter.on_packet_send(event)
        self.assertEqual(struct.unpack("<f", event.payload[-4:])[0], 7.25)
        self.assertEqual(self.adapter.rewritten_packets, 1)
        again = types.SimpleNamespace(packet_id=86, player=self.player, payload=sound_payload())
        before = again.payload
        self.adapter.on_packet_send(again)
        self.assertEqual(again.payload, before)

    def test_another_player_or_volume_cannot_consume_pending_packet(self):
        self.adapter.play(self.player, self.player.location, "custom.first", position_seconds=9)
        for player, volume in ((FakePlayer("Other"), 1), (self.player, 2)):
            event = types.SimpleNamespace(packet_id=86, player=player, payload=sound_payload(volume=volume))
            before = event.payload
            self.adapter.on_packet_send(event)
            self.assertEqual(event.payload, before)
        self.assertEqual(self.adapter.rewritten_packets, 0)

    def test_expired_or_disconnected_requests_do_not_touch_later_sounds(self):
        self.adapter.play(self.player, self.player.location, "custom.first", position_seconds=9)
        self.now = 3
        event = types.SimpleNamespace(packet_id=86, player=self.player, payload=sound_payload())
        before = event.payload
        self.adapter.on_packet_send(event)
        self.assertEqual(event.payload, before)
        self.adapter.play(self.player, self.player.location, "custom.first")
        self.adapter.forget(self.player)
        self.adapter.on_packet_send(event)
        self.assertEqual(event.payload, before)

    def test_truncated_unknown_or_malformed_payload_is_rejected(self):
        data = sound_payload()
        for malformed in (data[:-1], data + b"extra", b"\xff" * 8, b"\x80", data[:-3] + b"\x02\x00\x00"):
            with self.subTest(payload=malformed):
                with self.assertRaises(SoundPayloadError):
                    inspect_sound_payload(malformed)

    def test_empty_stop_and_invalid_numeric_settings_are_rejected(self):
        with self.assertRaises(ValueError):
            self.adapter.stop(self.player, "")
        for value in (float("nan"), float("inf"), -1):
            with self.assertRaises(ValueError):
                self.adapter.play(self.player, self.player.location, "custom.first", position_seconds=value)
        self.assertFalse(self.player.calls)


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.player = FakePlayer()
        self.server = fake_server(self.player)
        self.adapter = Mock(supported=True)
        self.engine = PlaybackEngine(self.server, self.adapter, Mock(), clock=lambda: self.now)
        self.tracks = (Track("a", "custom.a", 10, spatial_sounds={"default": "custom.a.jukebox.default"}),
                       Track("b", "custom.b", 20, spatial_sounds={"default": "custom.b.jukebox.default"}))
        self.location_patch = patch("endstone.level.Location", FakeLocation)
        self.location_patch.start()
        self.addCleanup(self.location_patch.stop)

    def start_box(self, key="box", **options):
        self.engine.start(key, self.tracks, position=Position("overworld", 0, 64, 0), **options)

    def test_album_advances_exactly_at_track_boundary(self):
        self.start_box()
        self.engine.tick()
        self.assertEqual(self.adapter.play.call_args.args[2], "custom.a.jukebox.default")
        self.now = 10
        self.engine.tick()
        self.adapter.stop.assert_called_once_with(self.player, "custom.a.jukebox.default")
        self.assertEqual(self.adapter.play.call_args.args[2], "custom.b.jukebox.default")
        self.now = 30
        self.engine.tick()
        self.assertFalse(self.engine.sources)
        self.assertFalse(self.engine.voices)

    def test_late_listener_seeks_to_current_track_position(self):
        self.player.location.x = 100
        self.start_box(radius=32)
        self.engine.tick()
        self.adapter.play.assert_not_called()
        self.now = 14.25
        self.player.location.x = 4
        self.engine.tick()
        self.assertEqual(self.adapter.play.call_args.kwargs["position_seconds"], 4.25)
        self.assertEqual(self.adapter.play.call_args.args[2], "custom.b.jukebox.default")

    def test_pitch_changes_timeline_and_seek_position(self):
        self.start_box(pitch=2)
        self.now = 6
        self.engine.tick()
        self.assertEqual(self.adapter.play.call_args.kwargs["position_seconds"], 2)
        self.assertEqual(self.adapter.play.call_args.args[2], "custom.b.jukebox.default")

    def test_loop_restarts_with_new_voice_even_on_single_track(self):
        self.engine.start("single", self.tracks[:1], listener=self.player.unique_id, loop=True)
        self.engine.tick()
        self.now = 10
        self.engine.tick()
        self.assertEqual(self.adapter.play.call_count, 2)
        self.adapter.stop.assert_called_once_with(self.player, "custom.a")

    def test_only_nearest_jukebox_owns_listener_voice(self):
        self.start_box("near")
        self.engine.start("far", self.tracks, position=Position("overworld", 20, 64, 0))
        self.engine.tick()
        self.assertEqual(self.adapter.play.call_count, 1)
        self.now = 2
        self.player.location.x = 20
        self.engine.tick()
        self.assertEqual(self.adapter.play.call_count, 2)
        self.assertEqual(self.adapter.play.call_args.kwargs["position_seconds"], 2)

    def test_different_dimension_is_silent_and_departure_stops_only_owned_sound(self):
        self.start_box()
        self.engine.tick()
        self.player.location.dimension.name = "nether"
        self.engine.tick()
        self.adapter.stop.assert_called_once_with(self.player, "custom.a.jukebox.default")
        self.assertFalse(self.engine.voices)

    def test_personal_track_takes_priority_then_jukebox_resumes_at_current_offset(self):
        self.start_box()
        self.engine.start("join", self.tracks[:1], listener=self.player.unique_id, duration=2)
        self.engine.tick()
        self.assertEqual(self.adapter.play.call_args.args[2], "custom.a")
        self.now = 3
        self.engine.tick()
        self.assertEqual(self.adapter.play.call_args.args[2], "custom.a.jukebox.default")
        self.assertEqual(self.adapter.play.call_args.kwargs["position_seconds"], 3)

    def test_replaced_source_is_not_stopped_by_old_duration(self):
        self.engine.start("personal", self.tracks[:1], listener=self.player.unique_id, duration=2)
        self.engine.tick()
        self.now = 1
        self.engine.start("personal", self.tracks[1:], listener=self.player.unique_id, duration=10)
        self.engine.tick()
        self.now = 3
        self.engine.tick()
        self.assertEqual(self.adapter.play.call_count, 2)
        self.assertIn("personal", self.engine.sources)

    def test_global_personal_audio_reaches_players_once_across_dimensions(self):
        self.server.online_players.append(FakePlayer("Other", "nether"))
        self.engine.start("global", self.tracks[:1], listener="*")
        self.engine.tick()
        self.engine.tick()
        self.assertEqual(self.adapter.play.call_count, 2)

    def test_quit_invalidates_voice_and_personal_source(self):
        self.engine.start("join", self.tracks[:1], listener=self.player.unique_id)
        self.engine.tick()
        self.engine.quit(self.player)
        self.assertFalse(self.engine.sources)
        self.assertFalse(self.engine.voices)
        self.adapter.forget.assert_called_once_with(self.player)

    def test_new_personal_trigger_replaces_previous_personal_source(self):
        self.engine.start("trigger:0", self.tracks[:1], listener=self.player.unique_id)
        self.engine.tick()
        self.engine.start("trigger:1", self.tracks[1:], listener=self.player.unique_id)
        self.engine.tick()
        self.assertNotIn("trigger:0", self.engine.sources)
        self.assertEqual(self.adapter.play.call_args.args[2], "custom.b")

    def test_follow_player_does_not_fade_or_replay_when_listener_moves(self):
        self.start_box(follow_player=True, volume=0.75, radius=8)
        self.engine.tick()
        self.assertEqual(self.adapter.play.call_args.args[2], "custom.a")
        self.assertEqual(self.adapter.play.call_args.args[3], 0.75)
        self.assertIs(self.adapter.play.call_args.args[1], self.player.location)
        self.player.location.x = 100000
        self.now = 5
        self.engine.tick()
        self.assertEqual(self.adapter.play.call_count, 1)
        self.adapter.stop.assert_not_called()
        self.assertIn(self.player.unique_id, self.engine.voices)

    def test_follow_player_keeps_entire_album_outside_original_radius(self):
        self.start_box(follow_player=True, volume=0.75, radius=8)
        self.engine.tick()
        self.player.location.x = 100000
        self.now = 12
        self.engine.tick()
        self.assertEqual(self.adapter.play.call_args.args[2], "custom.b")
        self.assertEqual(self.adapter.play.call_args.args[3], 0.75)
        self.assertEqual(self.adapter.play.call_args.kwargs["position_seconds"], 2)
        self.now = 30
        self.engine.tick()
        self.assertFalse(self.engine.voices)
        self.assertFalse(self.engine.sources)

    def test_follow_player_does_not_push_music_to_new_listeners_outside_range(self):
        self.start_box(follow_player=True, radius=8)
        self.engine.tick()
        other = FakePlayer("Other", x=1000)
        self.server.online_players.append(other)
        self.engine.tick()
        self.assertEqual(self.adapter.play.call_count, 1)
        self.assertNotIn(other.unique_id, self.engine.sources["box"].followers)
        self.now = 12
        other.location.x = 1
        self.engine.tick()
        self.assertIn(other.unique_id, self.engine.sources["box"].followers)
        self.assertEqual(self.adapter.play.call_args.kwargs["position_seconds"], 2)
        other.location.x = 1000
        self.now = 15
        self.engine.tick()
        self.assertIn(other.unique_id, self.engine.voices)

    def test_follow_player_survives_dimension_change_at_current_album_position(self):
        self.start_box(follow_player=True)
        self.engine.tick()
        self.player.location = FakeLocation(types.SimpleNamespace(name="nether"), x=1000)
        self.now = 4
        self.engine.tick()
        self.assertEqual(self.adapter.play.call_args.args[2], "custom.a")
        self.assertEqual(self.adapter.play.call_args.kwargs["position_seconds"], 4)
        self.assertIs(self.adapter.play.call_args.args[1], self.player.location)
        self.assertIn(self.player.unique_id, self.engine.voices)

    def test_unloaded_jukebox_keeps_followers_but_does_not_add_listeners(self):
        self.start_box(follow_player=True)
        self.engine.tick()
        source = self.engine.sources["box"]
        source.unavailable = True
        self.player.location.x = 1000
        other = FakePlayer("Other")
        self.server.online_players.append(other)
        self.now = 12
        self.engine.tick()
        self.assertIn(self.player.unique_id, self.engine.voices)
        self.assertNotIn(other.unique_id, self.engine.voices)
        self.assertEqual(self.adapter.play.call_args.args[2], "custom.b")

    def test_stopping_following_album_stops_only_its_owned_sound(self):
        self.start_box(follow_player=True)
        self.engine.tick()
        self.player.location.x = 1000
        self.engine.stop("box")
        self.engine.tick()
        self.adapter.stop.assert_called_once_with(self.player, "custom.a")
        self.assertFalse(self.engine.voices)

    def test_disconnect_clears_following_entitlement(self):
        self.start_box(follow_player=True)
        self.engine.tick()
        self.engine.quit(self.player)
        self.assertFalse(self.engine.sources["box"].followers)
        self.server.online_players = [FakePlayer("Player", x=1000)]
        self.engine.tick()
        self.assertFalse(self.engine.voices)

    def test_failed_play_does_not_capture_a_listener_who_never_heard_music(self):
        self.start_box(follow_player=True)
        self.adapter.play.side_effect = RuntimeError("send failed")
        self.engine.tick()
        self.assertFalse(self.engine.sources["box"].followers)
        self.player.location.x = 1000
        self.adapter.play.side_effect = None
        self.engine.tick()
        self.assertFalse(self.engine.voices)

    def test_listenerless_playback_cannot_become_an_accidental_broadcast(self):
        with self.assertRaisesRegex(ValueError, "source position"):
            self.engine.start("missing-target", self.tracks)

    def test_walking_past_a_newer_jukebox_does_not_interrupt_pushed_album(self):
        self.start_box(follow_player=True, radius=8)
        self.engine.tick()
        self.now = 1
        self.engine.start("other", (Track("new", "custom.new", 50),),
                          position=Position("overworld", 1000, 64, 0), radius=8, follow_player=True)
        self.player.location.x = 1000
        self.engine.tick()
        self.assertEqual(self.adapter.play.call_count, 1)
        self.now = 12
        self.engine.tick()
        self.assertEqual(self.adapter.play.call_args.args[2], "custom.b")

    def test_explicit_new_jukebox_action_can_replace_pushed_album(self):
        self.start_box(follow_player=True)
        self.engine.tick()
        self.engine.start("other", (Track("new", "custom.new", 50),),
                          position=Position("overworld", 1, 64, 0), follow_player=True)
        self.engine.prefer_source(self.player, "other")
        self.engine.tick()
        self.assertEqual(self.adapter.play.call_args.args[2], "custom.new")
        self.assertNotIn(self.player.unique_id, self.engine.sources["box"].followers)


class JukeboxTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="music-disc-test-")
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "jukeboxes.json"
        self.player = FakePlayer()
        self.block = types.SimpleNamespace(dimension=self.player.location.dimension, x=0, y=64, z=0,
                                           type="minecraft:jukebox", data=types.SimpleNamespace(block_states={"record_bit": False}))
        self.server = fake_server(self.player)
        self.server.level = types.SimpleNamespace(dimensions=[])
        self.plugin = types.SimpleNamespace(server=self.server, logger=Mock(), cmusic_config={})
        self.config = {
            "tracks": {"a": {"sound": "custom.a", "duration": 10}},
            "albums": {"album": {"title": "Album", "tracks": ["a"]}},
        }
        self.library = Library(self.config)
        self.library.disc_from_item = lambda item: self.library.discs.get(getattr(item, "disc_id", None))
        self.engine = Mock(adapter=types.SimpleNamespace(supported=True), sources={})
        self.controller = JukeboxController(self.plugin, self.library, self.engine, self.path)
        self.encoder = patch("endstone_music.jukebox.encode_item", lambda item: {"type": item.type, "amount": item.amount, "data": item.data, "custom": "preserved"})
        self.decoder = patch("endstone_music.jukebox.decode_item", lambda data: FakeItem(data["type"], data["amount"], data["data"]))
        self.encoder.start()
        self.decoder.start()
        self.addCleanup(self.encoder.stop)
        self.addCleanup(self.decoder.stop)

    def insert(self):
        self.assertTrue(self.controller.handle_interact(self.player, self.block))

    def test_insert_consumes_one_and_restart_keeps_ejectable_disc(self):
        self.player.inventory.slots[0].amount = 2
        self.insert()
        self.assertEqual(self.player.inventory.get_item(0).amount, 1)
        stored = JukeboxController(self.plugin, self.library, self.engine, self.path)
        self.assertEqual(stored.entries[block_key(self.block)]["item"]["custom"], "preserved")
        self.assertTrue(stored.eject(self.player, block_key(self.block)))
        self.assertEqual(self.player.inventory.get_item(1).amount, 1)
        self.assertFalse(stored.entries)

    def test_save_failure_rolls_back_inventory_and_does_not_start_audio(self):
        self.engine.reset_mock()
        with patch("endstone_music.jukebox.atomic_json", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.controller.handle_interact(self.player, self.block)
        self.assertEqual(self.player.inventory.get_item(0).amount, 1)
        self.assertFalse(self.controller.entries)
        self.engine.start.assert_not_called()

    def test_full_inventory_keeps_disc_inserted(self):
        self.insert()
        self.player.inventory.slots = {slot: FakeItem("minecraft:stone") for slot in range(5)}
        self.assertFalse(self.controller.eject(self.player, block_key(self.block)))
        self.assertIn(block_key(self.block), self.controller.entries)

    def test_eject_storage_failure_removes_provisional_returned_item(self):
        self.insert()
        with patch("endstone_music.jukebox.atomic_json", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.controller.eject(self.player, block_key(self.block))
        self.assertIsNone(self.player.inventory.get_item(0))
        self.assertIn(block_key(self.block), self.controller.entries)

    def test_vanilla_disc_in_block_is_not_overwritten(self):
        self.block.data.block_states["record_bit"] = True
        self.insert()
        self.assertEqual(self.player.inventory.get_item(0).amount, 1)
        self.assertFalse(self.controller.entries)

    def test_block_binding_selects_distinct_preset(self):
        self.library.jukeboxes["lounge"] = {"block": "minecraft:jukebox", "radius": 8, "pitch": 1, "volume": 0.5}
        self.plugin.cmusic_config = {"jukebox_bindings": {block_key(self.block): "lounge"}}
        self.insert()
        self.assertEqual(self.controller.entries[block_key(self.block)]["preset"], "lounge")
        self.assertEqual(self.engine.start.call_args.kwargs["radius"], 8)

    def test_jukebox_follow_mode_is_forwarded_to_playback(self):
        self.insert()
        self.assertTrue(self.engine.start.call_args.kwargs["follow_player"])

    def test_unloaded_block_is_unavailable_without_pausing_existing_followers(self):
        self.insert()
        source = types.SimpleNamespace(paused=False, unavailable=False)
        self.engine.sources = {"box:" + block_key(self.block): source}
        self.controller.tick()
        self.assertTrue(source.unavailable)
        self.assertFalse(source.paused)

    def test_chunk_lookup_error_does_not_pause_pushed_album(self):
        self.insert()
        source = types.SimpleNamespace(paused=False, unavailable=False)
        self.engine.sources = {"box:" + block_key(self.block): source}
        self.server.level.dimensions = [types.SimpleNamespace(
            name="overworld", get_block_at=Mock(side_effect=RuntimeError("Chunk is not available")),
        )]
        self.controller.tick()
        self.assertTrue(source.unavailable)
        self.assertFalse(source.paused)


class LibraryTests(unittest.TestCase):
    def test_jukebox_follow_defaults_on_and_can_be_disabled(self):
        self.assertTrue(Library({}).jukeboxes["default"]["follow_player"])
        library = Library({"jukeboxes": {"room": {"block": "minecraft:jukebox", "follow_player": False}}})
        self.assertFalse(library.jukeboxes["room"]["follow_player"])
        with self.assertRaisesRegex(ValueError, "follow_player"):
            Library({"jukeboxes": {"bad": {"block": "minecraft:jukebox", "follow_player": "false"}}})

    def test_manual_track_alias_keeps_generated_positional_events(self):
        generated = {"custom.intro": {"sound": "custom.intro", "duration": 60,
                                      "spatial_sounds": {"default": "custom.intro.jukebox.default"}}}
        library = Library({"tracks": {"intro": {"sound": "custom.intro", "duration": 60}},
                           "discs": {"single": {"track": "intro"}}}, generated)
        self.assertEqual(library.discs["single"].tracks[0].spatial_sounds["default"], "custom.intro.jukebox.default")

    def test_single_and_album_disc_playlists_validate(self):
        library = Library({"tracks": {"a": {"duration": 1, "sound": "custom.a"}},
                           "discs": {"single": {"track": "a"}}, "albums": {"album": {"tracks": ["a", "a"]}}})
        self.assertEqual(len(library.discs["single"].tracks), 1)
        self.assertEqual(len(library.discs["album"].tracks), 2)

    def test_unknown_tracks_and_nonfinite_durations_rejected(self):
        for config in ({"albums": {"bad": {"tracks": ["missing"]}}},
                       {"tracks": {"a": {"sound": "custom.a", "duration": float("nan")}}},
                       {"tracks": {"a": {"sound": "custom.a", "duration": -1}}}):
            with self.subTest(config=config), self.assertRaises(ValueError):
                Library(config)


class PackTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="music-pack-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.uploads, self.output = self.root / "uploads", self.root / "output"
        self.uploads.mkdir()
        self.generator = PackGenerator(data_path=self.root)

    def test_real_conversion_produces_stereo_and_mono_streamed_assets(self):
        source = self.uploads / "Test Song.WAV"
        with wave.open(str(source), "wb") as audio:
            audio.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
            audio.writeframes(b"".join(struct.pack("<h", int(1000 * math.sin(index * 2 * math.pi * 440 / 8000))) for index in range(8000)))
        sounds = self.generator.generate(self.uploads, self.output, "Test", jukeboxes={"lounge": {"radius": 24}})
        self.assertIn("custom.test_song", sounds)
        self.assertTrue(source.exists())
        pack = self.output / "endstone_music_pack"
        definitions = json.loads((pack / "sounds" / "sound_definitions.json").read_text())["sound_definitions"]
        self.assertFalse(definitions["custom.test_song"]["sounds"][0]["is3D"])
        self.assertTrue(definitions["custom.test_song.jukebox.lounge"]["sounds"][0]["is3D"])
        self.assertTrue(definitions["custom.test_song.jukebox.lounge"]["sounds"][0]["stream"])
        self.assertEqual(definitions["custom.test_song.jukebox.lounge"]["max_distance"], 24)
        _, ffprobe = self.generator._tools()
        for variant, channels in (("personal", 2), ("spatial", 1)):
            info = json.loads(self.generator._run([ffprobe, "-v", "error", "-show_streams", "-of", "json", str(pack / "sounds" / "custom" / variant / "test_song.ogg")]))
            self.assertEqual(info["streams"][0]["channels"], channels)
            self.assertEqual(info["streams"][0]["codec_name"], "vorbis")
        version = self.generator.version.copy()
        with patch.object(self.generator, "_tools", side_effect=AssertionError("Unchanged audio must be reused")):
            self.generator.generate(self.uploads, self.output, "Test", jukeboxes={"lounge": {"radius": 24}})
        self.assertEqual(self.generator.version[2], version[2] + 1)

    def test_failed_conversion_preserves_pack_metadata_and_uploads(self):
        self.generator.generate(self.uploads, self.output, "Original")
        manifest = self.output / "endstone_music_pack" / "manifest.json"
        original, metadata = manifest.read_bytes(), self.generator.metadata_file.read_bytes()
        bad = self.uploads / "broken.ogg"
        bad.write_bytes(b"invalid audio")
        with self.assertRaises(RuntimeError):
            self.generator.generate(self.uploads, self.output, "New")
        self.assertEqual(manifest.read_bytes(), original)
        self.assertEqual(self.generator.metadata_file.read_bytes(), metadata)
        self.assertTrue(bad.exists())

    def test_colliding_names_are_rejected_before_replacing_pack(self):
        (self.uploads / "a-b.ogg").write_bytes(b"a")
        (self.uploads / "a b.wav").write_bytes(b"b")
        with self.assertRaisesRegex(ValueError, "collide"):
            self.generator.generate(self.uploads, self.output, "Test")

    def test_spatial_suffix_in_track_name_cannot_overwrite_another_track(self):
        for name in ("a.wav", "a_spatial.wav"):
            with wave.open(str(self.uploads / name), "wb") as audio:
                audio.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
                audio.writeframes(b"\x00\x00" * 8000)
        self.generator.generate(self.uploads, self.output, "Test")
        root = self.output / "endstone_music_pack" / "sounds" / "custom"
        self.assertEqual(len(list(root.rglob("*.ogg"))), 4)

    def test_cancelled_generator_cannot_restart_after_shutdown(self):
        self.generator.cancel()
        with self.assertRaisesRegex(RuntimeError, "cancelled"):
            self.generator.generate(self.uploads, self.output, "Test")

    def test_world_pack_stack_is_preserved_and_invalid_stack_is_not_reset(self):
        worlds = self.root / "worlds"
        world = worlds / "My World"
        world.mkdir(parents=True)
        stack = world / "world_resource_packs.json"
        atomic_json(stack, [{"pack_id": "other", "version": [1, 0, 0]}])
        self.assertTrue(self.generator.install_to_world(worlds, "my world"))
        self.assertEqual(json.loads(stack.read_text())[1]["pack_id"], "other")
        stack.write_text("invalid", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.generator.install_to_world(worlds, "My World")
        self.assertEqual(stack.read_text(), "invalid")


class EndstoneContractTests(unittest.TestCase):
    def test_real_plugin_metadata_and_event_signatures(self):
        from endstone_music import EndstoneMusicPlugin
        from endstone.event import Event
        from endstone.plugin import PluginDescription
        from endstone.plugin.plugin_loader import _build_commands, _build_permissions

        attributes = dict(EndstoneMusicPlugin.__dict__)
        description = PluginDescription(name="music", version=attributes.pop("version"),
                                        commands=_build_commands(copy.deepcopy(attributes.pop("commands"))),
                                        permissions=_build_permissions(copy.deepcopy(attributes.pop("permissions"))), **attributes)
        self.assertEqual(description.version, "0.2.1")
        handlers = []
        for name in dir(EndstoneMusicPlugin):
            method = getattr(EndstoneMusicPlugin, name)
            if getattr(method, "_is_event_handler", False):
                annotation = list(inspect.signature(method).parameters.values())[1].annotation
                self.assertTrue(issubclass(annotation, Event), name)
                handlers.append(name)
        self.assertEqual(len(handlers), 5)

    def test_native_nbt_types_round_trip(self):
        from endstone import nbt
        from endstone_music.items import encode_tag, decode_tag

        tag = nbt.CompoundTag()
        tag["name"] = nbt.StringTag("Album")
        tag["byte"] = nbt.ByteTag(7)
        tag["short"] = nbt.ShortTag(300)
        tag["int"] = nbt.IntTag(100000)
        tag["long"] = nbt.LongTag(2 ** 40)
        tag["list"] = nbt.ListTag()
        tag["list"].append(nbt.StringTag("Lore"))
        encoded = encode_tag(tag)
        self.assertEqual(encode_tag(decode_tag(encoded)), encoded)


if __name__ == "__main__":
    unittest.main()
