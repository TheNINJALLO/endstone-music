"""Missing-tool installation, reuse, failure and cancellation regressions."""

import gzip
import hashlib
import io
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from endstone_music import audio_tools
from endstone_music.pack_generator import PackGenerator


class AudioToolTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.binaries = {name: ("test executable " + name).encode() for name in ("ffmpeg", "ffprobe")}
        digests = {name: hashlib.sha256(data).hexdigest() for name, data in self.binaries.items()}
        for item in (patch.object(audio_tools, "DIGESTS", {"linux-x64": digests, "win32-x64": digests}),
                     patch.object(audio_tools, "_target", return_value="linux-x64"),
                     patch.object(audio_tools.shutil, "which", return_value=None)):
            item.start()
            self.addCleanup(item.stop)
        self.network = patch.object(audio_tools, "urlopen", side_effect=self.response).start()
        self.addCleanup(patch.stopall)

    def response(self, request, **kwargs):
        name = request.full_url.rsplit("/", 1)[1].split("-", 1)[0]
        return io.BytesIO(gzip.compress(self.binaries[name]))

    def test_existing_path_tools_need_no_download_or_data_folder(self):
        with patch.object(audio_tools.shutil, "which", side_effect=lambda name: f"/system/{name}"):
            self.assertEqual(audio_tools.ensure_audio_tools(self.root), ("/system/ffmpeg", "/system/ffprobe"))
        self.network.assert_not_called()
        self.assertFalse((self.root / "tools").exists())

    def test_missing_tools_are_installed_and_reused_without_network(self):
        logger = Mock()
        tools = audio_tools.ensure_audio_tools(self.root, logger=logger)
        self.assertEqual(self.network.call_count, 2)
        for name, path in zip(self.binaries, tools):
            self.assertEqual(Path(path).read_bytes(), self.binaries[name])
        logger.info.assert_called()
        self.network.side_effect = AssertionError("Cached conversion must work offline")
        self.assertEqual(audio_tools.ensure_audio_tools(self.root), tools)
        self.assertFalse(list(self.root.rglob("*.download")))

    def test_missing_probe_keeps_system_ffmpeg(self):
        with patch.object(audio_tools.shutil, "which", side_effect=lambda name: "/system/ffmpeg" if name == "ffmpeg" else None):
            ffmpeg, ffprobe = audio_tools.ensure_audio_tools(self.root)
        self.assertEqual(ffmpeg, "/system/ffmpeg")
        self.assertEqual(Path(ffprobe).read_bytes(), self.binaries["ffprobe"])
        self.network.assert_called_once()
        self.assertIn("/ffprobe-linux-x64.gz", self.network.call_args.args[0].full_url)

    def test_windows_downloads_have_exe_suffix(self):
        with patch.object(audio_tools, "_target", return_value="win32-x64"):
            tools = audio_tools.ensure_audio_tools(self.root)
        self.assertEqual([Path(path).name for path in tools], ["ffmpeg.exe", "ffprobe.exe"])
        self.assertIn("win32-x64.gz", self.network.call_args.args[0].full_url)

    def test_corrupt_cache_is_repaired(self):
        tools = audio_tools.ensure_audio_tools(self.root)
        Path(tools[0]).write_bytes(b"truncated")
        self.network.reset_mock()
        self.assertEqual(audio_tools.ensure_audio_tools(self.root), tools)
        self.network.assert_called_once()
        self.assertEqual(Path(tools[0]).read_bytes(), self.binaries["ffmpeg"])

    def test_bad_checksum_never_publishes_executable(self):
        self.network.side_effect = lambda *args, **kwargs: io.BytesIO(gzip.compress(b"wrong binary"))
        with self.assertRaisesRegex(RuntimeError, "SHA-256 verification failed"):
            audio_tools.ensure_audio_tools(self.root)
        self.assertFalse(list(self.root.rglob("ffmpeg")))
        self.assertFalse(list(self.root.rglob("*.download")))

    def test_network_failure_cleans_partial_download_and_can_retry(self):
        self.network.side_effect = URLError("offline")
        with self.assertRaisesRegex(RuntimeError, "retry /cmusic generate"):
            audio_tools.ensure_audio_tools(self.root)
        self.assertFalse(list(self.root.rglob("*.download")))
        self.network.side_effect = self.response
        self.assertTrue(all(Path(path).is_file() for path in audio_tools.ensure_audio_tools(self.root)))

    def test_truncated_gzip_is_rejected(self):
        self.network.side_effect = lambda *args, **kwargs: io.BytesIO(b"not gzip")
        with self.assertRaisesRegex(RuntimeError, "Could not automatically install"):
            audio_tools.ensure_audio_tools(self.root)
        self.assertFalse(list(self.root.rglob("*.download")))

    def test_cancellation_before_download_does_not_access_network(self):
        cancel = threading.Event()
        cancel.set()
        with self.assertRaisesRegex(RuntimeError, "cancelled"):
            audio_tools.ensure_audio_tools(self.root, cancel=cancel)
        self.network.assert_not_called()

    def test_cancellation_during_download_cleans_partial_executable(self):
        cancel = threading.Event()

        def response(*args, **kwargs):
            cancel.set()
            return io.BytesIO(gzip.compress(self.binaries["ffmpeg"]))

        self.network.side_effect = response
        with self.assertRaisesRegex(RuntimeError, "cancelled"):
            audio_tools.ensure_audio_tools(self.root, cancel=cancel)
        self.assertFalse(list(self.root.rglob("*.download")))
        self.assertFalse(list(self.root.rglob("ffmpeg")))

    def test_install_failure_preserves_existing_pack_metadata_and_upload(self):
        generator = PackGenerator(data_path=self.root / "data")
        uploads, output = self.root / "uploads", self.root / "packs"
        generator.generate(uploads, output, "Original")
        manifest = output / "endstone_music_pack" / "manifest.json"
        before = manifest.read_bytes(), generator.metadata_file.read_bytes()
        source = uploads / "song.wav"
        source.write_bytes(b"source audio retained on installation failure")
        self.network.side_effect = URLError("offline")
        with self.assertRaisesRegex(RuntimeError, "Could not automatically install"):
            generator.generate(uploads, output, "Replacement")
        self.assertEqual((manifest.read_bytes(), generator.metadata_file.read_bytes()), before)
        self.assertTrue(source.is_file())
        self.assertEqual(json.loads(manifest.read_text())["header"]["name"], "Original")


class PlatformTests(unittest.TestCase):
    def test_supported_and_unsupported_platform_detection(self):
        for system, machine, target in (("Windows", "AMD64", "win32-x64"), ("Linux", "x86_64", "linux-x64")):
            with self.subTest(system=system), patch.object(audio_tools.platform, "system", return_value=system), patch.object(audio_tools.platform, "machine", return_value=machine):
                self.assertEqual(audio_tools._target(), target)
        with patch.object(audio_tools.platform, "system", return_value="Linux"), patch.object(audio_tools.platform, "machine", return_value="aarch64"):
            with self.assertRaisesRegex(RuntimeError, "install FFmpeg and ffprobe on PATH"):
                audio_tools._target()


if __name__ == "__main__":
    unittest.main()
