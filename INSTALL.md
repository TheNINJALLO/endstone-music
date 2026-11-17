# Music 0.2.3 - Install, upgrade and roll back

[README](README.md) | [Complete how-to](HOW-TO-USE.md) | [Live server checks](docs/ACCEPTANCE.md)

Target: Linux x86-64, Endstone **0.11.16**, BDS **1.26.65.1** / runtime **26.65** / protocol **2225**, Python **3.11+**. FFmpeg and ffprobe on PATH are used when available. Missing tools install automatically on the conversion worker on Linux/Windows x86-64 and are cached under `plugins/music/tools/`. Startup never waits for downloads.

The first conversion needs HTTPS access to `github.com` and `release-assets.githubusercontent.com` and write access to the Music data folder. Downloads use a pinned [ffmpeg-static release](https://github.com/eugeneware/ffmpeg-static/releases/tag/b6.1.1) and verified SHA-256 digests. Cached tools work offline. If downloads are blocked, install FFmpeg and ffprobe on PATH and verify `ffmpeg -version` and `ffprobe -version` from the server's launch environment, then retry `/cmusic generate`.

## Install or upgrade

1. Stop the server. Back up the full world, previous Music wheel and active Music data folder (normally `plugins/music/`), including uploads, config, playlist/disc storage, generated registries and `pack_metadata.json`. Keep the world's resource/behavior pack folders and both pack activation lists in the same backup.
2. Download `endstone_music-0.2.3-py3-none-any.whl` from [Music v0.2.3](https://github.com/TheNINJALLO/endstone-music/releases/tag/v0.2.3), or build it locally into `dist/`. Replace the old Music wheel in `plugins/`; keep only one version. The optional setup ZIP includes a release-time copy of the docs; use this repository for current instructions.
3. Preserve existing plugin data and pack UUID metadata. Start Endstone, inspect the logs and run `/cmusic status` as an operator. The target should report `adapter supported=True`.
4. Set `target_world_name` in `config.json` to the direct folder name under `worlds/`. Place audio in the Music data folder's `uploads/`, then run `/cmusic generate` and wait for completion. Upgrades from 0.2.0 require this regeneration.
5. Restart the server and reconnect clients so the new packs load. Accept/download the RP. The plugin activates the generated resource and behavior packs while preserving unrelated entries; it does not change the server's pack acceptance policy.
6. Follow the [how-to](HOW-TO-USE.md) to create insertable single/album discs or operator global playlists. Generate again after adding global playlist IDs to register their custom items, or after changing jukebox presets to update spatial events. Restart/reconnect after pack changes.
7. Complete [the acceptance checklist](docs/ACCEPTANCE.md) with at least two clients, including an ordinary player. See [the validation record](VALIDATION.md) for automated results; live startup, content registration and audible playback still need verification on the server.

Existing `playlists.json` retains operator playlists and dimension-specific custom-block bindings. Insertable discs use `config.json` and `jukeboxes.json`. Keep these stores and generated metadata together. A valid reload stops global music and restarts stored-disc playlists; a server restart also restarts stored-disc playlists from the beginning.

## Offline generation and manual pack installation

Run this from an environment where the plugin package is installed. FFmpeg/ffprobe must be on PATH or already cached under the supplied data folder's `tools/` directory for a fully offline conversion; otherwise the command downloads them when needed. Use a copy of the existing Music data folder, especially its `pack_metadata.json`, to retain pack identities:

```bash
python -m endstone_music.pack_generator \
  --data /path/to/music-data \
  --uploads /path/to/music-data/uploads \
  --output /path/to/generated-packs \
  --playlists /path/to/music-data/playlists.json
```

Omit `--playlists` for a new setup with no global playlists. The command creates packs and generated registries without activating a world. Use the in-game generator after configuring custom jukebox presets so their spatial profiles are included.

For manual installation, stop the server. Copy `endstone_music_pack/` into the world's `resource_packs/` and `endstone_music_behavior/` into its `behavior_packs/`. In `world_resource_packs.json` and `world_behavior_packs.json`, add/update the corresponding manifest header UUID and version, preserving unrelated entries. The BP dependency must match the RP UUID/version. Copy the updated generated registries and metadata from the offline data copy back to the active Music data folder as part of that same update. Restart and reconnect clients.

## Required in-game checks

- Insertable disc: nearby admission, whole-track/album follow without movement fading, positional mode when disabled, skip, eject, full inventory and recovery.
- Global playlist: normal volume across dimensions, late join at the current offset, next, stop, replacement and looping. A new join sound or legacy trigger must not interrupt it.
- Permissions: ordinary players can use configured insertable discs, while global playlist commands/items/custom-block controls remain operator-only. Revoke management permission with a menu open and retry its actions.
- Generated content: custom block/item registration, accepted and outdated packs, matching RP/BP versions and clean content logs. Generate again after adding a global playlist item ID.
- Lifecycle: loaded and unloaded source chunks, removed blocks, dimension changes, duplicate clicks, reload, disconnect/rejoin and clean shutdown. Dimension transitions may reissue at the current offset; they must not restart at zero.

## Rollback

Stop the server. Restore the previous wheel, plugin data, pack folders and RP/BP activation lists as a matched set. Restore the world backup if custom blocks were placed, rather than removing their BP while leaving blocks behind. Restore original UUID/version metadata with those packs. Restart and reconnect clients, then verify the old setup loads.

Rotating `.bak`/`.backup` files help short-term recovery; retain a separate complete backup. World/player inventories and the plugin's disc ledger are separate stores, so a process crash during an item transfer still warrants an inventory audit.
