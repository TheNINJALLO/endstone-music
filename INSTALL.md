# Install, test and roll back

## Before installation

This is a local development build, not a deployed release. Nothing has been pushed, restarted or changed on a live world. Target versions are inherited from the repository and checked against Endstone v0.11.14 API sources, not verified against your live server.

1. Stop the test server before replacing wheels. Back up the full world and the existing plugin data directory, previous wheel, `pack_metadata.json`, `config.json`, all uploaded audio, RP/BP directories and `world_resource_packs.json` / `world_behavior_packs.json`.
2. Keep a copy outside the plugin's rotating `.bak` and `.backup` files. Copying a backup does not verify it; confirm it is readable.
3. Remove the old plugin wheel from the test server's `plugins/` directory and copy `endstone_music-0.2.0-py3-none-any.whl` there. Install FFmpeg/ffprobe on PATH. Do not install two versions of this plugin together.
4. Start Endstone and inspect logs. Existing config stays intact. A new `playlists.json` is created. Empty global music state is intentional.
5. Follow the README quick start in order. Pack generation can occur with zero playlists, so generate audio durations first, then create playlists, then regenerate custom items. Restart/reconnect after changing pack content. World RP/BP activation preserves unrelated pack entries.
6. Require the RP on your test server if music should be mandatory, using your normal Bedrock server configuration. This plugin does not silently change pack acceptance settings.
7. Test with at least two Bedrock clients, one operator and one ordinary player, and only then repeat your normal controlled production upgrade procedure.

## Manual pack installation / offline generation

Use the offline generator with a copy of your original metadata so existing RP UUIDs remain stable. Copy `endstone_music_pack/` into the world's `resource_packs/`, and `endstone_music_behavior/` into its `behavior_packs/`. Add or update their header UUID/version entries in the corresponding world pack list. Preserve all unrelated entries. The BP depends on the exact RP UUID/version. Restart the server and reconnect clients. Do not use the bundled template's arbitrary UUIDs to replace an existing production pack identity.

## Required in-game checks

- Two clients hear the same track at normal volume; walk far away, teleport, and change dimensions without sound fading/restarting. Repeat on mobile/touch input.
- Join midway: no restart for current listeners; new client starts at the next track. Check single-track looping and non-looping playlists.
- Operator Stop/Next/replacement; ordinary player commands, copied items, renamed vanilla items, and jukebox clicks cannot take control. Revoke permission with a menu open and retry.
- Give/place custom jukebox; link using item and menu; empty-hand controls; unlink; break; cancel a break using a protection plugin; unload chunk; duplicate coordinates in another dimension.
- Loop boundary, long track, explicit duration, pitch, rapid repeated clicks, reload, disable, server restart and full inventory.
- Legacy triggers outside global mode; legacy joins before/after a global start; no delayed callback cuts off global music.
- Accepted/rejected/missing/outdated RP; both packs show no content-log errors; custom item and block textures and names load.

## Rollback

Stop the server. Restore the previous wheel, the backed-up plugin data, original pack directories and original RP/BP activation JSON as a matched set. Restore the world backup if custom blocks were placed; removing a BP while those blocks remain can produce missing content. Restore original UUID/version metadata with the packs. Restart and reconnect clients; verify the old plugin and packs load. `.bak`/`.backup` are short-term recovery aids, not a substitute for the complete pre-upgrade backup.
