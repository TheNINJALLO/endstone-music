# Endstone Music 0.2.0

Operator-controlled server-wide music, editable playlists, real custom playlist items and a custom jukebox block. Existing trigger and join-sound configuration remains readable.

Based on `TheNINJALLO/endstone-music` commit `841b12e5954f10da444b1d1f21cceb7d5163bc9e` (0.1.2). Targets **Endstone 0.11.14 / API 0.11, Python 3.11+, BDS 1.26.52.3** as stated by the original repository. This upgrade has automated local tests and pack checks, but has **not run on a live Endstone/Bedrock server or been audibly tested**. Validate a backed-up test world before production.

## What changed

- A single operator-controlled global playlist session. One sound packet per connected player per track. The resource pack gives each global sound its own `is3D: false, stream: true` definition; no huge radius, artificial high volume, or repeated replay workaround.
- Ordered persistent playlists: create, edit, reorder, remove tracks, loop, next, stop, and delete. Durations come from FFprobe after conversion, or explicit seconds; timing accounts for pitch. Active sessions use a snapshot, so editing does not disrupt them.
- A real BP item `endstone_music:playlist_<id>` for each playlist. Identification uses the registered item ID, never a display name or lore. Renaming a vanilla item cannot activate it.
- A real BP block `endstone_music:jukebox`, its implicit placeable item, RP PNG artwork, English name, and operator interaction menus. Bindings persist by dimension and integer block coordinates. Use a playlist item on it to link, or select a playlist in its menu. Controls are server-wide.
- Pack generation retains original audio uploads and existing sound definitions, with dedicated global aliases so old proximity triggers remain positional. Stable pack UUIDs, bumped versions, file backups and directory backups.

## Quick start

1. Back up plugin data, the world, its pack directories and pack activation JSON. Install the new wheel following [INSTALL.md](INSTALL.md).
2. Install **FFmpeg and FFprobe on the server PATH** from a trusted source. Audio generation does not download executables automatically. Python dependencies no longer bundle static-ffmpeg/pydub.
3. Put audio you have permission to use in `plugins/music/uploads/` (use the actual plugin data folder reported by Endstone; upgraded installs may use `plugins/endstone_music/`). Supported inputs: OGG, MP3, WAV. Use lowercase letters, numbers and underscores for filenames. Spaces/hyphens normalize to underscores; collisions are rejected.
4. Set the existing `config.json` `target_world_name` to the direct world folder name. Run `/cmusic generate`. This converts audio, records durations and creates/activates BP and RP. Uploads are never deleted. `song.ogg` becomes `custom.song`.
5. Open `/cmusic` → **Global Music / Playlists** → **Create playlist**. Enter an ID such as `lobby`. Enter ordered tracks as `custom.song; custom.other`, or `custom.song=123.4; custom.other=90` to override durations. Set loop as desired. The list uses semicolons so mobile text fields work.
6. Run `/cmusic generate` again to create the playlist's custom item definition. Restart the test server and reconnect clients so they download the new packs. New playlist IDs require regeneration and restart; changing track order or loop alone does not.
7. `/cmusic play lobby` starts it for everyone. `/cmusic give lobby` gives you its playlist item; **use it on an ordinary block** to start. Air use may not fire on all clients for an otherwise inert custom item.
8. `/cmusic give jukebox` gives you the custom block. Place it, use the playlist item on it to link, then choose **Play for everyone**. Empty-hand use opens its controls. The menu also offers Stop, Next and Unlink.

All music management, new item activation, jukebox controls, and jukebox breaking require `endstone_music.command.cmusic` (default `op`). Administrators can explicitly grant this permission; possessing or copying an item alone grants no control. Custom items are an identifier mechanism, not cryptographic inventory ownership.

## Commands

- `/cmusic`: existing management menu plus Global Music / Playlists
- `/cmusic playlists`: playlist menu (console: list IDs)
- `/cmusic play <id>`, `/cmusic stop`, `/cmusic next`, `/cmusic status`
- `/cmusic playlist create <id>`
- `/cmusic playlist add <id> <sound> [seconds]` (duration can be omitted after generation)
- `/cmusic playlist remove <id> <track-number>`
- `/cmusic playlist move <id> <from-number> <to-number>` (1-based)
- `/cmusic playlist loop <id> on|off`
- `/cmusic playlist delete <id>` (also removes its jukebox bindings and stops that playlist)
- `/cmusic give <id|jukebox>` (player only; requires generated/loaded custom IDs)
- `/cmusic reload`: validates configuration, stops active global playback, cancels pending join stops, then applies it. Invalid JSON leaves active in-memory playback untouched.
- `/cmusic generate`: builds audio and both packs, updates world activation lists with backups; restart/reconnect afterward
- `/cmusic migrate`: directs legacy installations to generate, which adds the required global aliases

## Session behavior and limitations

Global music uses only generated pack sounds, not unverified vanilla sound IDs. Existing standalone triggers retain their previous configuration. While a global session is active, legacy triggers and join sounds are suppressed so they cannot replace the operator's session. Outside a global session, legacy triggers work as before. Legacy join sounds are now played only to the joining player and stopped by exact sound name, preventing the old nearby-all-sounds stop from disrupting other audio.

Late joiners **wait for the next track**. Endstone's sound API has no seek/offset support; it cannot accurately synchronize a client into the middle of an OGG. A single-track non-looping playlist therefore gives late joiners no audio until the next explicit start. Disconnecting removes that client's tracking. A session continues its bounded track schedule with zero players; looping continues until Stop, reload or disable. No auto-resume occurs after restart.

A jukebox starts the same server-wide channel; a second start replaces the previous session. Bindings distinguish dimensions. The plugin checks loaded chunks once per second without force-loading them. Removing/replacing a bound block cleans its binding and stops only a session owned by it; unloading its chunk stops its session but retains the binding. A stale form cannot play or link a removed/unloaded block. A player cannot break the custom block without the operator permission. Other plugins, explosions, commands and chunk unloads are detected on the periodic check. A block removed and replaced at the same coordinates between checks may retain its binding; verify administrative world edits explicitly. The block is marked immovable by pistons.

Volume/pitch defaults are 1.0. Advanced `playlists.json` per-track settings support volume 0–1 and pitch 0.5–2, with finite durations 0.05–86400 seconds. The mobile editor preserves settings by matching sound ID; duplicate occurrences of the same sound reuse that sound's first existing volume/pitch. Use JSON for distinct settings on duplicates. Track end uses wall-clock duration checked every server tick, not sample-perfect synchronization; lag can delay a transition. Client pack acceptance, volume slider, music behavior and audible continuity across dimensions need real Bedrock validation.

## Files and safe migration

`config.json` is not rewritten merely to add playlists; old triggers and unknown keys are retained. The new `playlists.json` stores schema-versioned playlists and jukebox bindings. `track_durations.json`, `sounds_registry.json` and `global_sounds_registry.json` are generated data. `pack_metadata.json` preserves existing RP UUIDs and adds BP UUIDs. JSON updates keep `.bak`; generated pack directories keep `.backup`. Each new backup replaces the prior backup, so keep an independent backup before every upgrade/generation. No world blocks are placed automatically.

Do not use symlinks in upload/pack paths or a symlink target world. Invalid/malformed pack activation JSON is rejected rather than erased. Staging and directory swaps protect each pack, but the entire multi-file generation/install is not one filesystem transaction; after any I/O failure inspect backups before restarting.

## Offline build and test

From this source directory:

```sh
python run_tests.py
python -m compileall -q src
python -c 'from setuptools.build_meta import build_wheel; build_wheel("dist")'
PYTHONPATH=src python -m endstone_music.pack_generator --data ./offline_data --uploads ./uploads --output ./generated --playlists ./playlists.json
```

The offline generator writes both pack directories and metadata only; it does not activate a world. No copyrighted music is included. The supplied template packs contain an empty `lobby` playlist item and the jukebox for inspection; regenerate with your own metadata/audio/config before use. See [VALIDATION.md](VALIDATION.md) for what was and was not tested.
