"""Validated persistent playlists and a scheduler-independent playback state machine."""
from __future__ import annotations
import copy
import json
import math
import re
import shutil
import time
from pathlib import Path

ID = re.compile(r"[a-z0-9_]{1,48}\Z")
SOUND = re.compile(r"[a-z0-9_.:]+\Z")


def atomic_json(path: Path, value, backup=True):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if backup and path.exists():
        shutil.copy2(path, path.with_name(path.name + ".bak"))
    temp.replace(path)


def validate(document):
    if not isinstance(document, dict) or document.get("schema_version") != 1:
        raise ValueError("Unsupported playlist schema; expected schema_version 1")
    playlists = document.get("playlists")
    bindings = document.get("jukeboxes")
    if not isinstance(playlists, dict) or not isinstance(bindings, dict):
        raise ValueError("playlists and jukeboxes must be objects")
    for name, playlist in playlists.items():
        if not ID.fullmatch(name) or not isinstance(playlist, dict):
            raise ValueError("Playlist IDs: 1–48 lowercase letters, numbers or underscores")
        if type(playlist.get("loop")) is not bool or not isinstance(playlist.get("tracks"), list):
            raise ValueError(f"Invalid playlist {name}")
        for track in playlist["tracks"]:
            if not isinstance(track, dict) or not isinstance(track.get("sound"), str) or not SOUND.fullmatch(track["sound"]):
                raise ValueError("Invalid sound identifier")
            for key, low, high in (("duration", .05, 86400), ("volume", 0, 1), ("pitch", .5, 2)):
                value = track.get(key, 1.0 if key != "duration" else None)
                if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
                    raise ValueError(f"{key} must be finite and between {low} and {high}")
    for key, name in bindings.items():
        if not isinstance(key, str) or not key or name not in playlists:
            raise ValueError("Invalid jukebox binding")
        try:
            coordinates = json.loads(key)
        except ValueError as error:
            raise ValueError("Invalid jukebox location") from error
        if not isinstance(coordinates, list) or len(coordinates) != 4 or not isinstance(coordinates[0], str) or any(type(x) is not int for x in coordinates[1:]):
            raise ValueError("Invalid jukebox location")
    return document


class PlaylistStore:
    def __init__(self, path):
        self.path = Path(path)
        self.reload()

    def reload(self):
        new = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {"schema_version": 1, "playlists": {}, "jukeboxes": {}}
        validate(new)
        self.data = new
        if not self.path.exists():
            atomic_json(self.path, new)

    def update(self, edit):
        candidate = copy.deepcopy(self.data)
        edit(candidate)
        validate(candidate)
        atomic_json(self.path, candidate)
        self.data = candidate

    def put(self, name, tracks, loop=False):
        self.update(lambda d: d["playlists"].__setitem__(name, {"tracks": tracks, "loop": loop}))

    def delete(self, name):
        def edit(d):
            del d["playlists"][name]
            d["jukeboxes"] = {k: v for k, v in d["jukeboxes"].items() if v != name}
        self.update(edit)

    def bind(self, key, name):
        self.update(lambda d: d["jukeboxes"].__setitem__(key, name))

    def unbind(self, key):
        self.update(lambda d: d["jukeboxes"].pop(key, None))


class Playback:
    """One global session. Joiners wait for the next track (no unsupported seeking)."""
    def __init__(self, play, stop, clock=time.monotonic):
        self.play_callback, self.stop_callback, self.clock = play, stop, clock
        self.session = None
        self.generation = 0

    def stop(self):
        self.generation += 1
        old, self.session = self.session, None
        if old:
            self.stop_callback(old["track"]["sound"])

    def start(self, name, playlist, source=None):
        if not playlist["tracks"]:
            raise ValueError("Add at least one track first")
        snapshot = copy.deepcopy(playlist)
        self.stop()
        self.session = {"name": name, "playlist": snapshot, "index": 0, "source": source}
        self._play()

    def _play(self):
        s = self.session
        track = s["playlist"]["tracks"][s["index"]]
        s["track"] = track
        s["deadline"] = self.clock() + track["duration"] / track.get("pitch", 1.0)
        try:
            self.play_callback(track)
        except Exception:
            self.stop()
            raise

    def next(self):
        if not self.session:
            return
        s = self.session
        self.stop_callback(s["track"]["sound"])
        s["index"] += 1
        if s["index"] >= len(s["playlist"]["tracks"]):
            if not s["playlist"]["loop"]:
                self.session = None
                return
            s["index"] = 0
        self._play()

    def tick(self):
        if self.session and self.clock() >= self.session["deadline"]:
            self.next()
