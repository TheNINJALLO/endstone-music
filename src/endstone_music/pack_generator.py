"""Build streamed personal/spatial audio without importing converters at startup."""

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from copy import deepcopy
from pathlib import Path

from .library import atomic_json, number
from .content_pack import CustomContent, reject_links
from .playlists import ID as PLAYLIST_ID

GLOBAL_PREFIX = "endstone_music.global."


def sound_stem(path):
    stem = re.sub(r"[^a-z0-9_]", "_", path.stem.lower()).strip("_")
    if not stem or len(stem) > 80:
        raise ValueError(f"Choose a shorter ASCII audio filename: {path.name}")
    return stem


class PackGenerator(CustomContent):
    def __init__(self, key="endstone_music", data_path=None):
        if not re.fullmatch(r"[a-z0-9_]{1,64}", key):
            raise ValueError("Invalid generated pack directory key")
        self.key, self.data_path = key, Path(data_path) if data_path else None
        self.metadata_file = self.data_path / "pack_metadata.json" if self.data_path else None
        self.pack_uuid, self.module_uuid, self.version = str(uuid.uuid4()), str(uuid.uuid4()), [1, 0, 0]
        self.metadata = {}
        if self.metadata_file and self.metadata_file.exists():
            metadata = json.loads(self.metadata_file.read_text(encoding="utf-8-sig"))
            self.metadata = metadata.copy()
            self.pack_uuid = str(uuid.UUID(metadata["pack_uuid"]))
            self.module_uuid = str(uuid.UUID(metadata["module_uuid"]))
            self.version = metadata["version"]
            if not isinstance(self.version, list) or len(self.version) != 3 or any(type(v) is not int or v < 0 for v in self.version):
                raise ValueError("Invalid pack version; existing metadata was preserved")
        for field in ("behavior_uuid", "behavior_module_uuid"):
            self.metadata[field] = str(uuid.UUID(self.metadata[field])) if field in self.metadata else str(uuid.uuid4())
        self.tracks = {}
        self._cancel = threading.Event()
        self._process = None
        self._process_lock = threading.Lock()

    def cancel(self):
        self._cancel.set()
        with self._process_lock:
            if self._process is not None and self._process.poll() is None:
                self._process.terminate()

    def _remove_generated(self, path, output_dir):
        target, root = path.resolve(), output_dir.resolve()
        if target.parent != root or not (path.name in (f"{self.key}_pack", f"{self.key}_behavior", f"{self.key}_pack.backup", f"{self.key}_behavior.backup") or path.name.startswith(f".{self.key}-")):
            raise ValueError("Refusing to remove a directory outside the generated pack output")
        shutil.rmtree(target)

    def _run(self, command):
        if self._cancel.is_set():
            raise RuntimeError("Pack generation cancelled")
        options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
        with self._process_lock:
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **options)
            self._process = process
        deadline = time.monotonic() + 300
        try:
            while True:
                if self._cancel.is_set() or time.monotonic() > deadline:
                    process.kill()
                    process.communicate()
                    raise RuntimeError("Audio conversion cancelled or exceeded five minutes")
                try:
                    output, error = process.communicate(timeout=0.2)
                    break
                except subprocess.TimeoutExpired:
                    continue
            if process.returncode:
                raise RuntimeError(error.decode(errors="replace")[-2000:])
            return output
        finally:
            with self._process_lock:
                self._process = None

    @staticmethod
    def _tools():
        ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
        if not ffmpeg or not ffprobe:
            raise RuntimeError("Install FFmpeg and ffprobe on PATH before generating music packs")
        return ffmpeg, ffprobe

    def generate(self, upload_dir, output_dir, pack_name, playlists=None, *, jukeboxes=None):
        upload_dir, output_dir = Path(upload_dir), Path(output_dir)
        reject_links(upload_dir, tree=True)
        reject_links(output_dir, tree=True)
        upload_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)
        if self._cancel.is_set():
            raise RuntimeError("Pack generation cancelled")
        files = sorted(p for p in upload_dir.iterdir() if p.is_file() and p.suffix.lower() in (".ogg", ".mp3", ".wav"))
        stems = [sound_stem(path) for path in files]
        if len(set(stems)) != len(stems):
            raise ValueError("Audio filenames collide after normalization; rename the duplicate files")
        playlists = playlists or {}
        if any(not PLAYLIST_ID.fullmatch(key) for key in playlists):
            raise ValueError("Invalid playlist identifier")
        presets = jukeboxes or {"default": {"radius": 32}}
        for key, preset in presets.items():
            if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{0,95}", key):
                raise ValueError(f"Invalid jukebox preset ID: {key}")
            number(preset.get("radius", 32), "Jukebox radius", 1, 4096)
        pack_dir = output_dir / f"{self.key}_pack"
        stage = Path(tempfile.mkdtemp(prefix=f".{self.key}-", dir=output_dir))
        behavior_stage = Path(tempfile.mkdtemp(prefix=f".{self.key}-behavior-", dir=output_dir))
        behavior_dir = output_dir / f"{self.key}_behavior"
        behavior_backup = output_dir / f".{self.key}-behavior-previous-{uuid.uuid4().hex}"
        backup = output_dir / f".{self.key}-previous-{uuid.uuid4().hex}"
        old_version = self.version.copy()
        next_version = [*self.version[:2], self.version[2] + 1]
        moved_old = committed = False
        moved_behavior = committed_behavior = False
        metadata_before = {path: path.read_bytes() if path.exists() else None for path in
                           (self.metadata_file, self.data_path / "track_durations.json") if path is not None} if self.data_path else {}
        try:
            if pack_dir.exists():
                shutil.copytree(pack_dir, stage, dirs_exist_ok=True)
            sounds_dir = stage / "sounds" / "custom"
            (sounds_dir / "personal").mkdir(parents=True, exist_ok=True)
            (sounds_dir / "spatial").mkdir(parents=True, exist_ok=True)
            definitions_path = stage / "sounds" / "sound_definitions.json"
            definitions = json.loads(definitions_path.read_text(encoding="utf-8-sig")) if definitions_path.exists() else {"format_version": "1.14.0", "sound_definitions": {}}
            if not isinstance(definitions.get("sound_definitions"), dict):
                raise ValueError("Existing sound definitions are invalid; pack was preserved")
            previous_path = stage / "music_tracks.json"
            tracks = json.loads(previous_path.read_text()) if previous_path.exists() else {}
            durations_path = self.data_path / "track_durations.json" if self.data_path else None
            legacy_durations = json.loads(durations_path.read_text(encoding="utf-8-sig")) if durations_path and durations_path.exists() else {}
            for sound, duration in legacy_durations.items():
                if sound not in tracks and sound in definitions["sound_definitions"]:
                    tracks[sound] = {"sound": sound, "duration": number(duration, "Track duration", 0.05, 86400),
                                     "title": sound, "spatial_sounds": {}}
            tools = None
            for source, stem in zip(files, stems):
                sound = f"custom.{stem}"
                stereo, mono = sounds_dir / "personal" / f"{stem}.ogg", sounds_dir / "spatial" / f"{stem}.ogg"
                with source.open("rb") as stream:
                    source_hash = hashlib.file_digest(stream, "sha256").hexdigest()
                old = tracks.get(sound, {})
                if old.get("source_sha256") != source_hash or not stereo.exists() or not mono.exists():
                    if tools is None:
                        tools = self._tools()
                    ffmpeg, ffprobe = tools
                    info = json.loads(self._run([ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "json", str(source)]))
                    duration = number(info["format"]["duration"], f"{source.name} duration", 0.05, 86400)
                    for target, channels in ((stereo, 2), (mono, 1)):
                        self._run([ffmpeg, "-v", "error", "-nostdin", "-y", "-i", str(source), "-vn", "-map_metadata", "-1",
                                   "-c:a", "libvorbis", "-q:a", "5", "-ar", "44100", "-ac", str(channels), str(target)])
                    old = {"sound": sound, "duration": duration, "title": source.stem, "source_sha256": source_hash}
                old["spatial_sounds"] = {key: f"{sound}.jukebox.{key}" for key in presets}
                tracks[sound] = old
                definitions["sound_definitions"][sound] = {
                    "category": "record", "sounds": [{"name": f"sounds/custom/personal/{stem}", "stream": True, "is3D": False}],
                }
                for key, preset in presets.items():
                    definitions["sound_definitions"][old["spatial_sounds"][key]] = {
                        "category": "record", "min_distance": 1.0, "max_distance": float(preset.get("radius", 32)),
                        "sounds": [{"name": f"sounds/custom/spatial/{stem}", "stream": True, "is3D": True}],
                    }
            for name, definition in list(definitions["sound_definitions"].items()):
                if name.startswith(GLOBAL_PREFIX) or ".jukebox." in name:
                    continue
                alias = deepcopy(definition)
                alias["sounds"] = [dict(sound if isinstance(sound, dict) else {"name": sound}, is3D=False, stream=True)
                                   for sound in definition["sounds"]]
                definitions["sound_definitions"][GLOBAL_PREFIX + name] = alias
            self._custom_content(stage, behavior_stage, playlists, next_version)
            atomic_json(definitions_path, definitions)
            atomic_json(stage / "music_tracks.json", tracks)
            atomic_json(stage / "manifest.json", {
                "format_version": 2,
                "header": {"description": "Album discs and positional jukebox audio", "name": pack_name,
                           "uuid": self.pack_uuid, "version": next_version, "min_engine_version": [1, 26, 60]},
                "modules": [{"description": "Custom music", "type": "resources", "uuid": self.module_uuid, "version": next_version}],
            })
            if self._cancel.is_set():
                raise RuntimeError("Pack generation cancelled")
            if pack_dir.exists():
                pack_dir.rename(backup)
                moved_old = True
            stage.rename(pack_dir)
            committed = True
            if behavior_dir.exists():
                behavior_dir.rename(behavior_backup)
                moved_behavior = True
            behavior_stage.rename(behavior_dir)
            committed_behavior = True
            self.version = next_version
            if self.metadata_file:
                atomic_json(self.metadata_file, {**self.metadata, "pack_uuid": self.pack_uuid, "module_uuid": self.module_uuid, "version": self.version})
                atomic_json(self.data_path / "track_durations.json", {key: track["duration"] for key, track in tracks.items()})
            self.tracks = tracks
            self.last_registered_sounds = sorted(set(tracks) | {
                key for key in definitions["sound_definitions"] if ".jukebox." not in key and not key.startswith(GLOBAL_PREFIX)
            })
            return self.last_registered_sounds
        except Exception:
            self.version = old_version
            if committed and pack_dir.exists():
                self._remove_generated(pack_dir, output_dir)
            if moved_old and backup.exists():
                backup.rename(pack_dir)
            if committed_behavior and behavior_dir.exists():
                self._remove_generated(behavior_dir, output_dir)
            if moved_behavior and behavior_backup.exists():
                behavior_backup.rename(behavior_dir)
            for path, contents in metadata_before.items():
                if contents is None:
                    path.unlink(missing_ok=True)
                elif not path.exists() or path.read_bytes() != contents:
                    with tempfile.NamedTemporaryFile("wb", dir=path.parent, delete=False) as temporary:
                        temporary.write(contents)
                    os.replace(temporary.name, path)
            raise
        finally:
            if stage.exists():
                self._remove_generated(stage, output_dir)
            if behavior_stage.exists():
                self._remove_generated(behavior_stage, output_dir)
            if backup.exists():
                saved = pack_dir.with_name(pack_dir.name + ".backup")
                reject_links(saved, tree=True)
                if saved.exists():
                    self._remove_generated(saved, output_dir)
                backup.rename(saved)
            if behavior_backup.exists():
                saved = behavior_dir.with_name(behavior_dir.name + ".backup")
                reject_links(saved, tree=True)
                if saved.exists():
                    self._remove_generated(saved, output_dir)
                behavior_backup.rename(saved)


    def migrate_sound_categories(self, output_dir):
        return {"success": True, "migrated_count": 0,
                "message": "Run /cmusic generate to rebuild streamed stereo/positional audio for 26.60. Source uploads are retained."}


def main():
    import argparse
    from .playlists import validate
    parser = argparse.ArgumentParser(description="Generate music BP/RP offline without activating a world")
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--uploads", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--playlists", type=Path)
    args = parser.parse_args()
    playlists = validate(json.loads(args.playlists.read_text(encoding="utf-8-sig")))["playlists"] if args.playlists else {}
    generator = PackGenerator(data_path=args.data)
    sounds = generator.generate(args.uploads, args.output, "Endstone Music", playlists)
    atomic_json(args.data / "sounds_registry.json", sounds)
    atomic_json(args.data / "global_sounds_registry.json", sounds)
    atomic_json(args.data / "generated_tracks.json", generator.tracks)
    print(f"Generated {len(sounds)} sounds in {args.output}. No world activated.")


if __name__ == "__main__":
    main()
