# BDS 1.26.65.1 music adapter

The target is Linux x86-64, Endstone 0.11.16, BDS package 1.26.65.1 (runtime `26.65`), protocol 2225. The wheel is platform-independent. The runtime gate accepts this version family and protocol only; it does not claim support for 26.61 or 26.70.

## Native boundary and hooks

The adapter delegates BDS object access to Endstone's existing native runtime. It calls the public `Player.play_sound(Location, sound, volume, pitch)` and `Player.stop_sound(sound)` bindings. It does not create a second private C++ ABI, reinterpret a BDS object, or patch an executable address.

`PlayerInteractEvent` intercepts custom disc insertion/ejection before vanilla handling. `BlockBreakEvent` returns an inserted disc before a managed block can break, cancelling the break when the inventory is full or persistence fails. Both hooks respect an event already cancelled by another plugin. `PlayerJoinEvent` delays personal join audio until login has settled; `PlayerQuitEvent` invalidates pending callbacks and voices.

`PacketSendEvent` hooks packet 86 (`PlaySoundPacket`). Endstone's public play-sound binding does not expose the new playback-position and listener-range fields. The adapter matches an outstanding plugin play request by player UUID, sound ID, volume, and pitch, with a two-second expiry. It validates the entire wire payload before changing the bypass-range flag and optional playback-position float. It preserves coordinates, pitch, volume, loop count, and the optional server sound handle. Packets for other sound events or players pass through unchanged. Unknown layouts pass through unchanged and increment the status diagnostic counter.

All gameplay, inventory, block access, and playback selection run on the server thread. The packet hook only validates/rewrites bytes and accesses the request table under a lock. Audio conversion and filesystem pack generation run in a separate worker.

Follow Player selects the generated stereo sound event with is3D=false and retains listeners after admission. The radius only controls initial admission. Movement does not resend or attenuate the sound; album track transitions use the current timeline. Source chunk unavailability stops new admissions while existing pushed playback continues. Dimension transitions may reissue the non-positional event at its current offset. Explicit eject/stop and playlist completion still remove the voice. Positional mode remains available through follow_player=false and uses the mono event with its baked attenuation radius.

## Protocol contract

The reviewed protocol-2225 field order is: string name; three compressed block coordinates; float volume; float pitch; compressed loop count; boolean bypass listener range check; optional little-endian uint64 server sound handle; optional little-endian float playback position seconds. The optional fields have boolean presence bytes. The hook rejects trailing bytes, truncated fields, overlong varints, invalid booleans, invalid strings, and non-finite volume/pitch values.

The public/native ABI is reviewed against Endstone source commit `23cb5758bdc070888cb89ecd1541ef25c4305b5c` (`v0.11.16`). Its internal `PlaySoundPacket` is 144 bytes on Windows and 136 on Linux, and `StopSoundPacket` is 96/88 bytes; those layouts are recorded for review only. This plugin never relies on their sizes or offsets at runtime.

Primary references:

- [Mojang protocol 26.65 sound payload schema](https://github.com/Mojang/bedrock-protocol-docs/blob/0879ab5c4c70be1bd520e32a8c49ea4a155616d6/json/PlaySoundPacketPayload.json)
- [Mojang server sound handle schema](https://github.com/Mojang/bedrock-protocol-docs/blob/0879ab5c4c70be1bd520e32a8c49ea4a155616d6/json/ServerSoundHandle.json)
- [Endstone 0.11.16 native sound calls](https://github.com/EndstoneMC/endstone/blob/23cb5758bdc070888cb89ecd1541ef25c4305b5c/src/endstone/core/player.cpp)
- [Endstone packet-send hook](https://github.com/EndstoneMC/endstone/blob/23cb5758bdc070888cb89ecd1541ef25c4305b5c/include/endstone/event/server/packet_send_event.h)
- [Mojang resource-pack sound schema](https://github.com/Mojang/bedrock-schemas/blob/main/schemas/rp/sounds/index.schema.json)

## Server file verification

`tools/inspect_bds.py --download --platform linux` obtains the official package and checks both its archive and executable SHA-256 against `compatibility/bds-1.26.65.1.json`. The same check is available for Windows. It records matching jukebox, record-item, play-sound, and stop-sound strings as evidence. Those file offsets are not callable function addresses.

The official files were downloaded and verified for both platforms. The Linux executable hash is `ae606d06f9803b4e56b6af7ae15fdc149736fb27096221a0ec082881e897b067`; Windows is `1dd638ca380b1f30156a814e7bf568932f04f977b504601817961f782609dc4e`. Only inspection JSON is tracked; server executables remain in ignored `scratch/`.

## Validation boundary

Automated validation covers the packet codec, filtering, playlist timing, listener changes, inventory rollback and recovery, actual FFmpeg conversion, and Endstone 0.11.16 metadata/event/NBT contracts. The local test host is Windows. No Linux BDS process or connected retail game client was available, so live Linux server integration, real outbound packet capture, resource-pack delivery, client seeking, and audible playback remain unqualified. Follow [the acceptance checklist](ACCEPTANCE.md) before production installation.

Custom discs are kept in the plugin's persistent jukebox store, with full typed NBT. They do not occupy the vanilla jukebox block actor's record slot. Vanilla hopper/comparator automation is not implemented for these custom discs. New item artwork or custom block models must come from an installed resource/behavior pack; any registered item/block ID can be used in the configuration.
