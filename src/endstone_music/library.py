"""Validated track, album, disc, and jukebox definitions."""

import json
import math
import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .audio_adapter import SOUND_ID


ID = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,95}$")
DISC_MARKER = "§0cmusic:"


def atomic_json(path, data):
    path = Path(path)
    contents = json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("w", dir=path.parent, encoding="utf-8", delete=False) as output:
            temporary = Path(output.name)
            output.write(contents)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def number(value, label, minimum, maximum):
    if isinstance(value, bool):
        raise ValueError(f"{label} must be numeric")
    value = float(value)
    if not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError(f"{label} must be between {minimum} and {maximum}")
    return value


@dataclass(frozen=True)
class Track:
    id: str
    sound: str
    duration: float
    title: str = ""
    spatial_sounds: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Disc:
    id: str
    title: str
    tracks: tuple[Track, ...]
    item: str = "minecraft:music_disc_cat"
    loop: bool = False


class Library:
    def __init__(self, config, generated=None):
        self.tracks, self.discs, self.jukeboxes = {}, {}, {}
        track_configs = dict(generated or {})
        for key, value in config.get("tracks", {}).items():
            base = track_configs.get(key, track_configs.get(value.get("sound", ""), {}))
            track_configs[key] = {**base, **value}
        for key, value in track_configs.items():
            sound = value.get("sound", key)
            if not ID.fullmatch(key) or not SOUND_ID.fullmatch(sound):
                raise ValueError(f"Invalid track ID: {key}")
            spatial = value.get("spatial_sounds", {})
            if not isinstance(spatial, dict) or any(not SOUND_ID.fullmatch(s) for s in spatial.values()):
                raise ValueError(f"Invalid spatial sound for {key}")
            self.tracks[key] = Track(key, sound, number(value["duration"], f"{key} duration", 0.05, 86400), value.get("title", key), spatial)
        for key, value in config.get("albums", {}).items():
            self._disc(key, value, value.get("tracks", []))
        for key, value in config.get("discs", {}).items():
            if key in self.discs:
                raise ValueError(f"Duplicate album/disc ID: {key}")
            self._disc(key, value, [value["track"]])
        for key, value in config.get("jukeboxes", {"default": {"block": "minecraft:jukebox"}}).items():
            if not ID.fullmatch(key) or not SOUND_ID.fullmatch(value["block"]):
                raise ValueError(f"Invalid jukebox preset: {key}")
            follow_player = value.get("follow_player", True)
            if type(follow_player) is not bool:
                raise ValueError(f"{key} follow_player must be true or false")
            self.jukeboxes[key] = {
                "block": value["block"],
                "radius": number(value.get("radius", 32), "Jukebox radius", 1, 4096),
                "volume": number(value.get("volume", 1), "Jukebox volume", 0, 4),
                "pitch": number(value.get("pitch", 1), "Jukebox pitch", 0.25, 4),
                "follow_player": follow_player,
            }
        for key, preset_id in config.get("jukebox_bindings", {}).items():
            if preset_id not in self.jukeboxes or len(key.split("|")) != 4:
                raise ValueError(f"Invalid jukebox binding: {key}")

    def _disc(self, key, value, tracks):
        if not ID.fullmatch(key) or not tracks or len(tracks) > 256:
            raise ValueError(f"Invalid or empty album/disc: {key}")
        item = value.get("item", "minecraft:music_disc_cat")
        if not SOUND_ID.fullmatch(item):
            raise ValueError(f"Invalid disc item: {item}")
        try:
            playlist = tuple(self.tracks[track] for track in tracks)
        except KeyError as error:
            raise ValueError(f"{key} references an unknown track: {error}") from error
        self.discs[key] = Disc(key, value.get("title", key), playlist, item, bool(value.get("loop", False)))

    def disc_from_item(self, item):
        if item is None:
            return None
        meta = item.item_meta
        if meta is None:
            return None
        for line in meta.lore:
            if line.startswith(DISC_MARKER):
                disc = self.discs.get(line[len(DISC_MARKER):])
                return disc if disc is not None and str(item.type) == disc.item else None
        return None

    def make_disc(self, disc_id):
        from endstone.inventory import ItemStack

        disc = self.discs[disc_id]
        item = ItemStack(disc.item, 1)
        meta = item.item_meta
        meta.display_name = f"§r§b{disc.title}"
        meta.lore = [f"§r§7{len(disc.tracks)} track(s)", DISC_MARKER + disc_id]
        if not item.set_item_meta(meta) or DISC_MARKER + disc_id not in item.item_meta.lore:
            raise ValueError("The server could not attach custom disc metadata to this item")
        return item
