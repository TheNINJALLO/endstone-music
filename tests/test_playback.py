"""Pure state-machine tests; these do not substitute for Bedrock client tests."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location("music_playlists_test", Path(__file__).resolve().parents[1] / "src/endstone_music/playlists.py")
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)


class PlaybackTests(unittest.TestCase):
    def setUp(self):
        self.time = 0
        self.played, self.stopped = [], []
        self.player = m.Playback(self.played.append, self.stopped.append, lambda: self.time)
        self.playlist = {"loop": False, "tracks": [{"sound": "custom.a", "duration": 4, "pitch": 2}, {"sound": "custom.b", "duration": 3}]}

    def test_pitch_timing_and_end(self):
        self.player.start("test", self.playlist)
        self.time = 1.9
        self.player.tick()
        self.assertEqual(len(self.played), 1)
        self.time = 2
        self.player.tick()
        self.assertEqual(self.played[-1]["sound"], "custom.b")
        self.time = 5
        self.player.tick()
        self.assertIsNone(self.player.session)
        self.assertEqual(self.stopped, ["custom.a", "custom.b"])

    def test_stop_prevents_later_advance(self):
        self.player.start("test", self.playlist)
        self.player.stop()
        self.time = 50
        self.player.tick()
        self.assertEqual(len(self.played), 1)

    def test_loop_snapshot_and_replacement(self):
        self.playlist["loop"] = True
        self.player.start("test", self.playlist)
        self.playlist["tracks"].clear()
        self.player.next()
        self.player.next()
        self.assertEqual(self.played[-1]["sound"], "custom.a")
        self.player.start("new", {"loop": False, "tracks": [{"sound": "custom.c", "duration": 1}]})
        self.assertEqual(self.player.session["name"], "new")

    def test_empty_rejected_without_stopping_session(self):
        self.player.start("test", self.playlist)
        with self.assertRaises(ValueError):
            self.player.start("empty", {"loop": False, "tracks": []})
        self.assertEqual(self.player.session["name"], "test")

    def test_play_failure_cleans_up(self):
        self.player.play_callback = lambda track: (_ for _ in ()).throw(RuntimeError("unavailable"))
        with self.assertRaises(RuntimeError):
            self.player.start("test", self.playlist)
        self.assertIsNone(self.player.session)


class StoreTests(unittest.TestCase):
    def test_atomic_validation_persistence_and_binding_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "playlists.json"
            store = m.PlaylistStore(path)
            store.put("party", [{"sound": "custom.a", "duration": 2}], True)
            key = json.dumps(["overworld", 1, 2, 3], separators=(",", ":"))
            store.bind(key, "party")
            reloaded = m.PlaylistStore(path)
            self.assertEqual(store.data, reloaded.data)
            before = path.read_bytes()
            for duration in [None, float("nan"), -1, True, float("inf")]:
                with self.assertRaises(ValueError):
                    store.put("bad", [{"sound": "custom.a", "duration": duration}])
                self.assertEqual(before, path.read_bytes())
            with self.assertRaises(ValueError):
                store.bind("overworld:1:2:3", "party")
            store.delete("party")
            self.assertEqual(store.data["jukeboxes"], {})
            self.assertTrue(path.with_name("playlists.json.bak").exists())

    def test_reload_failure_keeps_memory_and_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "playlists.json"
            store = m.PlaylistStore(path)
            store.put("party", [], False)
            path.write_text("{invalid")
            with self.assertRaises(ValueError):
                store.reload()
            self.assertIn("party", store.data["playlists"])
            self.assertEqual(path.read_text(), "{invalid")


if __name__ == "__main__":
    unittest.main()
