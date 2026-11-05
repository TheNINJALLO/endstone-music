"""One owned music voice per listener, with synchronized playlist timelines."""

import time
from dataclasses import dataclass, field

from .audio_adapter import player_key
from .library import number


def dimension_key(dimension):
    return str(getattr(dimension, "name", dimension)).removeprefix("minecraft:")


@dataclass(frozen=True)
class Position:
    dimension: str
    x: float
    y: float
    z: float

    @classmethod
    def of(cls, location):
        return cls(dimension_key(location.dimension), location.x, location.y, location.z)

    def distance_squared(self, other):
        if self.dimension != other.dimension:
            return float("inf")
        return (self.x - other.x) ** 2 + (self.y - other.y) ** 2 + (self.z - other.z) ** 2


@dataclass
class Source:
    id: str
    token: object
    tracks: tuple
    started: float
    position: Position | None
    listener: str | None
    radius: float
    volume: float
    pitch: float
    loop: bool
    spatial_profile: str
    expires: float | None = None
    paused: bool = False
    follow_player: bool = False
    followers: set[str] = field(default_factory=set)
    unavailable: bool = False

    def current(self, now):
        elapsed = max(0, now - self.started) * self.pitch
        length = sum(track.duration for track in self.tracks)
        if self.expires is not None and now >= self.expires:
            return None
        cycle = int(elapsed // length)
        if cycle and not self.loop:
            return None
        elapsed %= length
        for index, track in enumerate(self.tracks):
            if elapsed < track.duration:
                return cycle, index, track, elapsed
            elapsed -= track.duration
        return None


class PlaybackEngine:
    def __init__(self, server, adapter, logger, clock=time.monotonic):
        self.server, self.adapter, self.logger, self.clock = server, adapter, logger, clock
        self.sources = {}
        self.voices = {}

    def start(self, source_id, tracks, *, position=None, listener=None, radius=32, volume=1, pitch=1,
              loop=False, spatial_profile="default", duration=None, follow_player=False):
        self.adapter.require_supported()
        if position is None and listener is None:
            raise ValueError("Playback requires a source position or a target listener")
        if not tracks:
            raise ValueError("An empty playlist cannot be played")
        for track in tracks:
            number(track.duration, "Track duration", 0.05, 86400)
        radius = number(radius, "Playback radius", 1, 1_000_000)
        volume = number(volume, "Volume", 0, 4)
        pitch = number(pitch, "Pitch", 0.25, 4)
        now = self.clock()
        expires = None if duration is None else now + number(duration, "Playback duration", 0.05, 86400)
        if listener is not None:
            for key, previous in list(self.sources.items()):
                if previous.listener == listener or listener == "*" and previous.listener is not None:
                    del self.sources[key]
        self.sources[source_id] = Source(source_id, object(), tuple(tracks), now, position, listener,
                                         radius, volume, pitch, bool(loop), spatial_profile, expires,
                                         follow_player=bool(follow_player))

    def stop(self, source_id):
        self.sources.pop(source_id, None)

    def prefer_source(self, player, source_id):
        """An explicit jukebox action can replace that player's pushed playlist."""
        source = self.sources.get(source_id)
        if source is None or not source.follow_player:
            return
        key = player_key(player)
        for previous in self.sources.values():
            previous.followers.discard(key)
        source.followers.add(key)

    def skip(self, source_id):
        source = self.sources.get(source_id)
        if source is None:
            return
        current = source.current(self.clock())
        if current is None:
            return
        _, index, _, elapsed = current
        source.started -= (source.tracks[index].duration - elapsed) / source.pitch

    def tick(self):
        now = self.clock()
        current = {}
        for key, source in list(self.sources.items()):
            track = source.current(now)
            if track is None:
                del self.sources[key]
            elif not source.paused:
                current[key] = (source, track)
        online = {}
        for player in self.server.online_players:
            try:
                key = player_key(player)
                online[key] = player
                location = player.location
                position = Position.of(location)
                candidates = []
                for source, track in current.values():
                    if source.listener is not None and source.listener not in (key, "*"):
                        continue
                    distance = source.position.distance_squared(position) if source.position is not None else 0
                    following = source.follow_player and key in source.followers
                    if not following and (source.unavailable or distance > source.radius ** 2):
                        continue
                    if source.listener is not None:
                        rank = -2 if source.listener == "*" else -3
                    else:
                        rank = -1 if following else 0
                    order = -source.started if source.listener is not None or following else distance
                    candidates.append((rank, order, source.id, source, track))
                selected = min(candidates, key=lambda value: value[:3]) if candidates else None
                old = self.voices.get(key)
                if selected is None:
                    if old:
                        self.adapter.stop(player, old[1])
                        self.voices.pop(key, None)
                    continue
                source, (cycle, index, track, offset) = selected[3:]
                sound = (track.spatial_sounds.get(source.spatial_profile, track.sound)
                         if source.position is not None and not source.follow_player else track.sound)
                voice = (source.token, cycle, index, sound, dimension_key(location.dimension))
                if old and old[0] == voice:
                    continue
                if old:
                    self.adapter.stop(player, old[1])
                    self.voices.pop(key, None)
                if source.position is not None and not source.follow_player:
                    from endstone.level import Location
                    origin = Location(location.dimension, source.position.x, source.position.y, source.position.z)
                else:
                    origin = location
                self.adapter.play(player, origin, sound, source.volume, source.pitch,
                                  position_seconds=offset, bypass_range=True)
                if source.follow_player:
                    source.followers.add(key)
                self.voices[key] = (voice, sound)
            except Exception as error:
                self.logger.warning(f"Music playback failed for {getattr(player, 'name', 'player')}: {error}")
        for key in set(self.voices) - set(online):
            self.voices.pop(key, None)

    def quit(self, player):
        key = player_key(player)
        self.voices.pop(key, None)
        for source_id, source in list(self.sources.items()):
            source.followers.discard(key)
            if source.listener == key:
                del self.sources[source_id]
        self.adapter.forget(player)

    def close(self):
        for player in self.server.online_players:
            voice = self.voices.get(player_key(player))
            if voice:
                try:
                    self.adapter.stop(player, voice[1])
                except Exception as error:
                    self.logger.warning(f"Could not stop owned music for {player.name}: {error}")
        self.voices.clear()
        self.sources.clear()
        self.adapter.close()
