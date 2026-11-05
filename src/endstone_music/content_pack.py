"""Custom block/item assets and world activation retained from the 0.2.0 release."""
import json
import copy
import shutil
import struct
import zlib
import uuid
from pathlib import Path
from .playlists import atomic_json

def read_json(path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else copy.deepcopy(default)

def reject_links(path, tree=False):
    path = Path(path).absolute()
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError(f"Symlink paths are not supported for music packs: {path}")
    if tree and path.exists() and any(child.is_symlink() for child in path.rglob("*")):
        raise ValueError(f"Symlinks inside pack directories are not supported: {path}")


class CustomContent:
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
        if Path(world_name).name != world_name or world_name in (".", ".."):
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

