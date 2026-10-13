"""Staged, backed-up BP/RP generation. Uploads are never removed or modified."""
from __future__ import annotations
import copy
import json
import math
import re
import shutil
import subprocess
import struct
import zlib
import tempfile
import uuid
from pathlib import Path
from endstone_music.playlists import atomic_json, ID

GLOBAL_PREFIX = "endstone_music.global."


def read_json(path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else copy.deepcopy(default)


def reject_links(path, tree=False):
    path = Path(path).absolute()
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError(f"Symlink paths are not supported for music packs: {path}")
    if tree and path.exists() and any(child.is_symlink() for child in path.rglob("*")):
        raise ValueError(f"Symlinks inside pack directories are not supported: {path}")


class PackGenerator:
    def __init__(self, key="endstone_music", data_path=None):
        self.key = key
        self.data_path = Path(data_path or ".")
        self.data_path.mkdir(parents=True, exist_ok=True)
        self.metadata_file = self.data_path / "pack_metadata.json"
        self.metadata = read_json(self.metadata_file, {})
        for key in ("pack_uuid", "module_uuid", "behavior_uuid", "behavior_module_uuid"):
            self.metadata.setdefault(key, str(uuid.uuid4()))
            uuid.UUID(self.metadata[key])
        self.pack_uuid = self.metadata["pack_uuid"]
        self.module_uuid = self.metadata["module_uuid"]
        self.version = self.metadata.get("version", [1, 0, 0])
        if not isinstance(self.version, list) or len(self.version) != 3 or any(type(x) is not int or x < 0 for x in self.version):
            raise ValueError("Invalid pack metadata version")
        self.last_registered_sounds = []

    def generate(self, upload_dir, output_dir, pack_name, playlists=None):
        upload_dir, output_dir = Path(upload_dir), Path(output_dir)
        reject_links(upload_dir, tree=True)
        reject_links(output_dir, tree=True)
        upload_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)
        playlists = playlists or {}
        if any(not ID.fullmatch(x) for x in playlists):
            raise ValueError("Invalid playlist identifier")
        destination = output_dir / f"{self.key}_pack"
        version = [*self.version[:2], self.version[2] + 1]
        with tempfile.TemporaryDirectory(prefix="music-build-", dir=output_dir) as temp:
            stage = Path(temp) / destination.name
            if destination.exists():
                shutil.copytree(destination, stage)
            else:
                stage.mkdir()
            sounds = stage / "sounds" / "custom"
            sounds.mkdir(parents=True, exist_ok=True)
            definitions = read_json(stage / "sounds" / "sound_definitions.json", {"format_version": "1.14.0", "sound_definitions": {}})
            entries = definitions["sound_definitions"]
            durations = read_json(self.data_path / "track_durations.json", {})
            seen = set()
            for file in sorted(upload_dir.iterdir()):
                if not file.is_file() or file.suffix.lower() not in (".ogg", ".wav", ".mp3"):
                    continue
                stem = re.sub(r"[ -]", "_", file.stem.lower())
                if not ID.fullmatch(stem) or stem in seen:
                    raise ValueError(f"Unsafe or duplicate normalized audio filename: {file.name}")
                seen.add(stem)
                target = sounds / f"{stem}.ogg"
                # FFmpeg is only invoked from installed PATH; no executable downloads.
                if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
                    raise RuntimeError("Install FFmpeg/ffprobe before generating audio packs")
                subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(file), "-vn", "-ac", "2", "-ar", "44100", "-c:a", "libvorbis", "-map_metadata", "-1", str(target)], check=True, timeout=600)
                probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(target)], check=True, capture_output=True, text=True, timeout=30)
                duration = float(probe.stdout.strip())
                if not math.isfinite(duration) or not 0.05 <= duration <= 86400:
                    raise ValueError(f"Invalid audio duration: {file.name}")
                durations[f"custom.{stem}"] = duration
                entries[f"custom.{stem}"] = {"category": "neutral", "sounds": [f"sounds/custom/{stem}"]}
            # Add dedicated 2D aliases; original spatial triggers retain their sound IDs.
            for name, definition in list(entries.items()):
                if name.startswith(GLOBAL_PREFIX):
                    continue
                alias = copy.deepcopy(definition)
                alias["sounds"] = [dict(s if isinstance(s, dict) else {"name": s}, is3D=False, stream=True) for s in definition["sounds"]]
                entries[GLOBAL_PREFIX + name] = alias
            atomic_json(stage / "sounds" / "sound_definitions.json", definitions, False)
            atomic_json(stage / "manifest.json", self._manifest(pack_name, "resources", version), False)
            behavior = Path(temp) / f"{self.key}_behavior"
            self._custom_content(stage, behavior, playlists, version)
            self._publish(stage, destination)
            self._publish(behavior, output_dir / behavior.name)
            self.version = version
            self.metadata["version"] = version
            atomic_json(self.metadata_file, self.metadata)
            atomic_json(self.data_path / "track_durations.json", durations)
        self.last_registered_sounds = sorted(x for x in entries if not x.startswith(GLOBAL_PREFIX))
        return self.last_registered_sounds

    def _manifest(self, name, kind, version):
        behavior = kind == "data"
        doc = {"format_version": 2, "header": {"name": name, "description": "Endstone Music generated content", "uuid": self.metadata["behavior_uuid" if behavior else "pack_uuid"], "version": version, "min_engine_version": [1, 21, 80]}, "modules": [{"type": kind, "uuid": self.metadata["behavior_module_uuid" if behavior else "module_uuid"], "version": version}]}
        if behavior:
            doc["dependencies"] = [{"uuid": self.pack_uuid, "version": version}]
        return doc

    @staticmethod
    def _publish(stage, target):
        reject_links(stage, tree=True)
        reject_links(target, tree=True)
        reject_links(target.with_name(target.name + ".backup"), tree=True)
        target.parent.mkdir(parents=True, exist_ok=True)
        backup = target.with_name(target.name + ".backup")
        prepared = target.with_name(target.name + ".prepared-" + uuid.uuid4().hex)
        shutil.copytree(stage, prepared)
        try:
            if target.exists():
                if backup.exists():
                    shutil.rmtree(backup)
                target.rename(backup)
            try:
                prepared.rename(target)
            except Exception:
                if backup.exists() and not target.exists():
                    backup.rename(target)
                raise
        finally:
            if prepared.exists():
                shutil.rmtree(prepared)

    @staticmethod
    def _texture(path, record=False):
        # Original 16x16 pixel art, written without imaging dependencies.
        rows = []
        for y in range(16):
            row = bytearray()
            for x in range(16):
                radius = (x - 7.5) ** 2 + (y - 7.5) ** 2
                if record:
                    color = (66, 224, 185, 255) if radius < 10 else (29, 35, 52, 255) if radius < 55 else (0, 0, 0, 0)
                else:
                    color = (65, 215, 175, 255) if 3 <= x <= 12 and 5 <= y <= 10 else (57, 38, 62, 255) if (x + y) % 3 else (92, 57, 76, 255)
                row.extend(color)
            rows.append(b"\0" + bytes(row))
        def chunk(kind, data):
            return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 16, 16, 8, 6, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(b"".join(rows))) + chunk(b"IEND", b""))

    def _custom_content(self, resource, behavior, playlists, version):
        atomic_json(behavior / "manifest.json", self._manifest("Endstone Music Jukebox", "data", version), False)
        for name in playlists:
            atomic_json(behavior / "items" / f"playlist_{name}.json", {"format_version": "1.21.80", "minecraft:item": {"description": {"identifier": f"endstone_music:playlist_{name}", "menu_category": {"category": "items"}}, "components": {"minecraft:display_name": {"value": f"Playlist: {name}"}, "minecraft:icon": {"textures": {"default": "endstone_music_playlist"}}, "minecraft:max_stack_size": 1}}}, False)
        atomic_json(behavior / "blocks" / "jukebox.json", {"format_version": "1.21.80", "minecraft:block": {"description": {"identifier": "endstone_music:jukebox", "menu_category": {"category": "construction"}}, "components": {"minecraft:geometry": "minecraft:geometry.full_block", "minecraft:material_instances": {"*": {"texture": "endstone_music_jukebox", "render_method": "opaque"}}, "minecraft:destructible_by_mining": {"seconds_to_destroy": 2}, "minecraft:destructible_by_explosion": {"explosion_resistance": 1200}, "minecraft:movable": {"movement_type": "immovable"}}}}, False)
        for filename, atlas_name, key, texture in (
            ("item_texture.json", "atlas.items", "endstone_music_playlist", "textures/items/endstone_music_playlist"),
            ("terrain_texture.json", "atlas.terrain", "endstone_music_jukebox", "textures/blocks/endstone_music_jukebox"),
        ):
            path = resource / "textures" / filename
            atlas = read_json(path, {"resource_pack_name": "endstone_music", "texture_name": atlas_name, "texture_data": {}})
            atlas.setdefault("texture_data", {})[key] = {"textures": texture}
            atomic_json(path, atlas, False)
        blocks_path = resource / "blocks.json"
        blocks = read_json(blocks_path, {"format_version": [1, 1, 0]})
        blocks["endstone_music:jukebox"] = {"sound": "wood"}
        atomic_json(blocks_path, blocks, False)
        self._texture(resource / "textures" / "items" / "endstone_music_playlist.png", True)
        self._texture(resource / "textures" / "blocks" / "endstone_music_jukebox.png")
        texts = resource / "texts"
        texts.mkdir(exist_ok=True)
        language = texts / "en_US.lang"
        lines = language.read_text(encoding="utf-8").splitlines() if language.exists() else []
        lines = [line for line in lines if not line.startswith("tile.endstone_music:jukebox.name=")]
        lines.append("tile.endstone_music:jukebox.name=Music Jukebox")
        language.write_text("\n".join(lines) + "\n", encoding="utf-8")
        languages = read_json(texts / "languages.json", [])
        if "en_US" not in languages:
            languages.append("en_US")
        atomic_json(texts / "languages.json", languages, False)

    def install_to_world(self, world_dir, world_name):
        worlds = Path(world_dir)
        if Path(world_name).name != world_name:
            raise ValueError("World name must be a folder name")
        target = next((p for p in worlds.iterdir() if p.is_dir() and not p.is_symlink() and p.name.lower() == world_name.lower()), None)
        if target is None:
            return False
        reject_links(target / "resource_packs", tree=True)
        reject_links(target / "behavior_packs", tree=True)
        behavior_source = target / "resource_packs" / f"{self.key}_behavior"
        updates = []
        # Preflight BOTH pack lists before publishing any world changes.
        for filename, pack_id in (("world_resource_packs.json", self.pack_uuid), ("world_behavior_packs.json", self.metadata["behavior_uuid"])):
            path = target / filename
            reject_links(path)
            reject_links(path.with_name(path.name + ".bak"))
            current = read_json(path, [])
            if not isinstance(current, list) or any(not isinstance(x, dict) or "pack_id" not in x for x in current):
                raise ValueError(f"Invalid {filename}; unchanged")
            current = [x for x in current if x["pack_id"] != pack_id]
            current.insert(0, {"pack_id": pack_id, "version": self.version})
            updates.append((path, current))
        if behavior_source.exists():
            self._publish(behavior_source, target / "behavior_packs" / behavior_source.name)
        for path, current in updates:
            atomic_json(path, current)
        return True

    def migrate_sound_categories(self, output_dir):
        # Full generate adds 2D aliases while retaining all existing sounds.
        return {"success": False, "migrated_count": 0, "message": "Run /cmusic generate to add non-spatial aliases, retaining existing spatial sound IDs."}


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Generate music BP/RP offline; never activates a world")
    parser.add_argument("--data", type=Path, required=True, help="Pack metadata and durations directory")
    parser.add_argument("--uploads", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--playlists", type=Path, help="Validated playlists.json")
    args = parser.parse_args()
    playlists = {}
    if args.playlists:
        from endstone_music.playlists import validate
        playlists = validate(read_json(args.playlists, {}))["playlists"]
    generator = PackGenerator(data_path=args.data)
    names = generator.generate(args.uploads, args.output, "Endstone Music", playlists)
    atomic_json(args.data / "sounds_registry.json", names)
    atomic_json(args.data / "global_sounds_registry.json", names)
    print(f"Generated {len(names)} sounds. BP/RP saved to {args.output}. No world activated.")


if __name__ == "__main__":
    main()
