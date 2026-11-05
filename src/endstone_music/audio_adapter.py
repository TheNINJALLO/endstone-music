"""Protocol-2225 sound adapter over Endstone's native packet/event boundary.

Only packets produced by this adapter are eligible for rewriting. This module
never dereferences BDS objects or calls a private C++ address.
"""

import math
import re
import struct
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass


PLAY_SOUND_PACKET = 86
PROTOCOL = 2225
SOUND_ID = re.compile(r"^[a-zA-Z0-9_.:-]{1,256}$")


class SoundPayloadError(ValueError):
    pass


def _varuint(data, offset):
    value = 0
    for shift in range(0, 35, 7):
        if offset >= len(data):
            raise SoundPayloadError("Truncated varint")
        byte = data[offset]
        offset += 1
        if shift == 28 and byte > 15:
            raise SoundPayloadError("Varint exceeds 32 bits")
        value |= (byte & 127) << shift
        if byte < 128:
            return value, offset
    raise SoundPayloadError("Invalid varint")


def _boolean(data, offset):
    if offset >= len(data) or data[offset] not in (0, 1):
        raise SoundPayloadError("Invalid boolean")
    return bool(data[offset]), offset + 1


def inspect_sound_payload(data):
    """Validate the complete legacy/wire PlaySound payload for protocol 2225."""
    if not 1 <= len(data) <= 4096:
        raise SoundPayloadError("Invalid sound payload size")
    size, offset = _varuint(data, 0)
    if not 1 <= size <= 256 or offset + size > len(data):
        raise SoundPayloadError("Invalid sound name length")
    try:
        sound = data[offset:offset + size].decode("utf-8")
    except UnicodeError as error:
        raise SoundPayloadError("Invalid sound name") from error
    offset += size
    for _ in range(3):
        _, offset = _varuint(data, offset)
    if offset + 8 > len(data):
        raise SoundPayloadError("Truncated volume/pitch")
    volume, pitch = struct.unpack_from("<ff", data, offset)
    if not math.isfinite(volume) or not math.isfinite(pitch):
        raise SoundPayloadError("Invalid volume/pitch")
    offset += 8
    _, offset = _varuint(data, offset)  # loop count; preserve its original encoding
    bypass_offset = offset
    _, offset = _boolean(data, offset)
    handle, offset = _boolean(data, offset)
    if handle:
        offset += 8  # ServerSoundHandle: optional little-endian uint64
    playback_offset = offset
    playback, offset = _boolean(data, offset)
    if playback:
        offset += 4
    if offset != len(data):
        raise SoundPayloadError("Unexpected sound payload layout")
    return sound, volume, pitch, bypass_offset, playback_offset


def adapt_sound_payload(data, *, position_seconds, bypass_range):
    if not math.isfinite(position_seconds) or not 0 <= position_seconds <= 86400:
        raise SoundPayloadError("Invalid playback position")
    _, _, _, bypass_offset, playback_offset = inspect_sound_payload(data)
    return (data[:bypass_offset] + bytes([bool(bypass_range)])
            + data[bypass_offset + 1:playback_offset]
            + b"\x01" + struct.pack("<f", position_seconds))


def player_key(player):
    return str(player.unique_id)


@dataclass(frozen=True)
class PendingSound:
    token: object
    expires: float
    position_seconds: float
    bypass_range: bool
    volume: float
    pitch: float


class SoundAdapter:
    def __init__(self, server, logger, clock=time.monotonic):
        self.server, self.logger, self.clock = server, logger, clock
        self._pending = defaultdict(deque)
        self._lock = threading.Lock()
        self.rewritten_packets = 0
        self.rejected_packets = 0
        version = str(server.minecraft_version)
        endstone_version = str(server.version)
        self.supported = (
            int(server.protocol_version) == PROTOCOL
            and re.search(r"(?:^|\D)(?:1\.)?26\.60(?:\D|$)", version) is not None
            and re.search(r"(?:^|\D)0\.11\.15(?:\D|$)", endstone_version) is not None
        )
        self.identity = f"BDS {version}, protocol {server.protocol_version}, Endstone {endstone_version}"

    def require_supported(self):
        if not self.supported:
            raise RuntimeError(f"Music adapter requires BDS 1.26.60.6 / protocol 2225 / Endstone 0.11.15; found {self.identity}")

    def play(self, player, location, sound, volume=1.0, pitch=1.0, *, position_seconds=0.0, bypass_range=False):
        self.require_supported()
        if not SOUND_ID.fullmatch(sound):
            raise ValueError("Invalid sound event ID")
        if not all(math.isfinite(v) for v in (volume, pitch, position_seconds)):
            raise ValueError("Non-finite playback settings")
        if not 0 <= volume <= 4 or not 0.25 <= pitch <= 4 or not 0 <= position_seconds <= 86400:
            raise ValueError("Playback settings are out of range")
        key = (player_key(player), sound)
        pending = PendingSound(object(), self.clock() + 2.0, position_seconds, bypass_range, volume, pitch)
        with self._lock:
            self._expire()
            self._pending[key].append(pending)
        try:
            player.play_sound(location, sound, volume=volume, pitch=pitch)
        except Exception:
            with self._lock:
                queue = self._pending.get(key, deque())
                self._pending[key] = deque(entry for entry in queue if entry.token is not pending.token)
            raise

    def _expire(self):
        now = self.clock()
        for key in list(self._pending):
            queue = self._pending[key]
            while queue and queue[0].expires < now:
                queue.popleft()
            if not queue:
                del self._pending[key]

    def on_packet_send(self, event):
        if not self.supported or event.packet_id != PLAY_SOUND_PACKET or event.player is None:
            return
        data = bytes(event.payload)
        try:
            sound, volume, pitch, _, _ = inspect_sound_payload(data)
        except SoundPayloadError:
            self.rejected_packets += 1
            return
        key = (player_key(event.player), sound)
        with self._lock:
            self._expire()
            queue = self._pending.get(key)
            if not queue:
                return
            pending = queue[0]
            if not (math.isclose(volume, pending.volume, rel_tol=1e-5, abs_tol=1e-6)
                    and math.isclose(pitch, pending.pitch, rel_tol=1e-5, abs_tol=1e-6)):
                return
            event.payload = adapt_sound_payload(
                data, position_seconds=pending.position_seconds, bypass_range=pending.bypass_range,
            )
            queue.popleft()
            if not queue:
                del self._pending[key]
            self.rewritten_packets += 1

    @staticmethod
    def stop(player, sound):
        if not SOUND_ID.fullmatch(sound):
            raise ValueError("Refusing an empty or invalid stop-sound request")
        player.stop_sound(sound)

    def forget(self, player):
        key = player_key(player)
        with self._lock:
            for pending_key in list(self._pending):
                if pending_key[0] == key:
                    del self._pending[pending_key]

    def close(self):
        with self._lock:
            self._pending.clear()
