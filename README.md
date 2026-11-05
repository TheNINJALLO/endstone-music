<!-- endstone-professional-header:start -->
<p align="center">
  <img src="docs/assets/banner.svg" width="100%" alt="Endstone Music &mdash; A plugin to trigger custom music on block interaction and auto-generate resource packs">
</p>

<p align="center">
  <a href="https://github.com/TheNINJALLO/endstone-music/actions/workflows/wheel-release.yml"><img alt="Build" src="https://img.shields.io/github/actions/workflow/status/TheNINJALLO/endstone-music/wheel-release.yml?branch=main&amp;style=for-the-badge&amp;logo=githubactions&amp;logoColor=white&amp;label=Build"></a>
  <a href="https://github.com/TheNINJALLO/endstone-music/releases/latest"><img alt="Latest release" src="https://img.shields.io/github/v/release/TheNINJALLO/endstone-music?display_name=tag&amp;style=for-the-badge&amp;label=Release"></a>
</p>

<p align="center">
  <img alt="Endstone 0.11.15" src="https://img.shields.io/badge/Endstone-0.11.15-52b7a8?style=flat-square">
  <img alt="API 0.11" src="https://img.shields.io/badge/API-0.11-63b8ff?style=flat-square">
  <img alt="BDS 1.26.60.6" src="https://img.shields.io/badge/BDS-1.26.60.6-8b7dff?style=flat-square">
  <img alt="Python >=3.11" src="https://img.shields.io/badge/Python-%3E=3.11-3776AB?style=flat-square&amp;logo=python&amp;logoColor=white">
</p>

<p align="center">
  <strong>A plugin to trigger custom music on block interaction and auto-generate resource packs.</strong>
</p>

<p align="center">
  <a href="#what-it-does">What it does</a> &bull;
  <a href="#how-to-use">How to use</a> &bull;
  <a href="#commands-and-permissions">Commands</a> &bull;
  <a href="#install">Install</a> &bull;
  <a href="https://github.com/TheNINJALLO/endstone-music/releases">Releases</a>
</p>

## Overview

A plugin to trigger custom music on block interaction and auto-generate resource packs. This release is aligned with Endstone 0.11.15 and Minecraft Bedrock Dedicated Server 1.26.60.6, and is distributed as a Python wheel for direct installation in an Endstone server.

## What it does

- Adds single-track discs, ordered album playlists, looping, and configurable jukebox presets.
- Uses Endstone's native sound calls and a protocol-2225 packet hook for current-position playback when listeners enter range.
- Builds streamed stereo personal audio and mono positional jukebox audio from OGG, MP3, or WAV uploads in a background worker.
- Tracks one plugin-owned music voice per listener, with range/dimension cleanup and exact sound stopping.
- Preserves inserted discs with typed NBT, insert/eject rollback on write failures, full-inventory protection, and recovery controls.

## How to use

1. Place audio files in the plugin's `uploads/` directory, then run `/cmusic generate`.
2. Restart the server so clients receive the generated resource pack.
3. Run `/cmusic`, create a trigger, and select its item/block conditions and sound settings.
4. Use `/cmusic reload` after supported manual configuration edits.

## Commands and permissions

| Command / usage | What it does | Access |
|---|---|---|
| `/cmusic`<br>`/cmusic <reload\|generate\|migrate>` | Manage custom music triggers and resource packs | `endstone_music.command.cmusic` |

## Compatibility

| Component | Target version |
|---|---|
| Endstone | `0.11.15` |
| Endstone API | `0.11` |
| Bedrock Dedicated Server | `1.26.60.6` |
| Python | `>=3.11` |
| Plugin release | `v0.2.1` |

## Install

Download the wheel from the matching GitHub release:

```bash
gh release download v0.2.1 --repo TheNINJALLO/endstone-music --pattern "*.whl"
```

Copy the downloaded wheel into the server's `plugins/` directory, remove any older wheel for the same plugin, and restart Endstone.

> [!IMPORTANT]
> Use Endstone `0.11.15` with BDS `1.26.60.6`. Back up worlds and plugin data before upgrading a production server.

## Configuration and secrets

Runtime databases, logs, local `.env` files, server directories, and root `config.toml` files are excluded from source releases. When an example configuration is provided, copy it locally and keep live tokens, passwords, webhook URLs, and server identifiers out of Git.

## Release automation

A new package version on main, or a matching `v*` tag, runs [the wheel release workflow](.github/workflows/wheel-release.yml), builds the package in a clean GitHub runner, stores the wheel as a workflow artifact, and attaches it to the matching GitHub release.
<!-- endstone-professional-header:end -->

---

## Album discs and custom jukeboxes

Target: Linux x86-64, Endstone **0.11.15**, BDS **1.26.60.6** / runtime **26.60**, protocol **2225**, Python **3.11+**. Official server files were verified for Linux and Windows. The packet/event/NBT contracts and audio conversion are tested automatically. Live Linux server integration and audible playback still require the [acceptance checklist](docs/ACCEPTANCE.md); the local automated tests run on Windows.

### Set up music

1. Put OGG, MP3, or WAV audio in the active plugin data folder's uploads directory, normally plugins/music/uploads/.
2. Set target_world_name in that folder's config.json to the actual world directory name.
3. Run /cmusic generate. Conversion runs in a worker so it does not block the game loop. Install FFmpeg and ffprobe on PATH before generation. The plugin does not download executables or load converters at startup.
4. Restart the server and reconnect clients so they receive the updated pack. Keep source uploads: regeneration reuses unchanged audio and reconverts changed files.
5. Open /cmusic → **Albums & Discs** → **Create album / single-track disc**. Enter one track ID for a single or a comma-separated ordered list for an album. Generated IDs look like custom.my_song; exact IDs and measured durations are in generated_tracks.json.
6. Select a saved disc in **Albums & Discs** to receive its item, or use /cmusic give <disc-or-album-id> [player name].

Discs have configurable titles and existing item IDs. Their metadata identifies the playlist; renaming an ordinary vanilla disc does not turn it into a custom disc. They can also use custom item IDs already registered by an installed behavior/resource pack.

### Play and manage jukeboxes

- Right-click an accepted block with a custom disc to insert one item and start its playlist.
- Right-click an occupied custom jukebox normally to eject the stored item. A full inventory keeps the disc inserted.
- Sneak-right-click to advance to the next track, or restart a completed playlist.
- Block breaking first returns the inserted disc. If it cannot be returned or saved safely, the break is cancelled.
- /cmusic recover returns discs from managed blocks that were externally removed or are unloaded.
- Inserted discs remain stored across plugin/server restarts. Their playlists restart from the beginning.

Open **Custom Jukebox Setup** to create presets with block ID, radius, volume, and pitch. Use /cmusic bind <preset-id>, then right-click a matching block to assign a preset to that individual location. This allows multiple radii/volumes on blocks of the same type. Regenerate the resource pack and restart after adding presets or changing spatial ranges.

**Follow Player is enabled by default.** Once a listener hears a jukebox or block trigger, the full track or album continues at its configured volume as they walk away. It uses the streamed stereo, non-positional event, so movement does not fade it or restart the song. The initial radius controls who receives the music; it does not broadcast to players elsewhere. The current album is not interrupted just by walking past another jukebox.

Already attached listeners continue through chunk unloading and dimension changes, using the current track offset when audio must be reissued. A disconnect removes the listener. Playlist completion, stop/eject, or explicit replacement ends that pushed playback; looping albums continue until stopped or ejected. Personal audio retains its normal priority.

Disable the **Follow listeners for the whole track or album (no fading)** toggle in Custom Jukebox Setup, or set follow_player to false in a preset, to use normal positional audio and radius cutoff. Trigger forms have the same option. Missing follow_player settings default to true, including existing configurations. With positional mode, the nearest audible jukebox is selected and different dimensions remain isolated. Unavailable blocks do not admit new listeners; loaded blocks that were replaced stop their music while the stored discs remain recoverable.

Regenerate the packs after upgrading from 0.2.0 so the stereo, spatial and global aliases match this version, then restart and reconnect clients. External sound packs must define their personal events with is3D=false for movement-free playback.

These are plugin-managed jukeboxes. Custom inserted discs are stored in jukeboxes.json, rather than the vanilla block actor's record slot. Vanilla hopper/comparator automation for custom discs is not included. Custom block models and disc artwork come from the server's installed behavior/resource packs.

### Configuration

See [the example configuration](examples/albums-and-jukeboxes.json). Its sample track IDs and durations are placeholders: upload matching audio and use measured generated entries or provide the actual event IDs/durations.

Tracks can define externally supplied resource-pack sound events and durations. Discs select a single track; albums select ordered tracks. Jukeboxes define presets, and jukebox_bindings map individual dimension/block coordinates to a preset. Generated tracks include separate mono sound events for each jukebox preset so client-side attenuation matches its radius.

Existing interaction triggers and join sound settings remain supported. A loop trigger needs a measured track duration or an explicit duration; new trigger forms include a duration field. Join audio is personal, delayed one second after login, and invalidated on disconnect. Stopping music always targets a specific plugin-owned sound ID.

| Command | Purpose |
|---|---|
| /cmusic | Open the operator menu |
| /cmusic status | Show runtime identity, counts, and packet adapter diagnostics |
| /cmusic generate | Build and install the generated world resource pack |
| /cmusic reload | Validate and apply configuration; inserted discs remain recoverable |
| /cmusic give &lt;id&gt; [player name] | Give a configured single/album disc |
| /cmusic bind &lt;preset&gt; | Assign a preset on the next matching block click |
| /cmusic recover | Recover an inserted disc through the operator menu |
| /cmusic stop | Stop plugin-owned music without removing inserted discs |
| /cmusic migrate | Rebuild assets with the current generator |

All management commands require endstone_music.command.cmusic (operator by default). Ordinary players can use configured discs and jukeboxes.

### Verification and adapter details

- [Native/public ABI boundary and protocol-2225 hook](docs/ABI_ADAPTER.md)
- [Linux server and audible-playback acceptance](docs/ACCEPTANCE.md)
- [Exact BDS package identities](compatibility/bds-1.26.60.6.json)
- Verify downloaded server files: python tools/inspect_bds.py --download --platform linux
- Run tests after installing the project/dependencies: python run_tests.py

The adapter requires the reviewed 26.60 / protocol-2225 / Endstone-0.11.15 combination. Unsupported runtimes keep administration and stored-item recovery available, but disable new playback. /cmusic status reports the reason. No guessed BDS memory addresses or native object layouts are used.

### Existing global playlists and custom blocks

The 0.2.0 operator features remain available: /cmusic playlists opens the ordered playlist editor; /cmusic play <id>, next and stop control server-wide playback. Playlist files and dimension-specific custom jukebox bindings remain in playlists.json. Global playback uses the shared voice engine and generated non-positional aliases; late joiners enter at the current track position. Legacy triggers and join audio cannot interrupt a global session.

/cmusic give jukebox gives the generated endstone_music:jukebox block item; /cmusic give <playlist-id> gives its custom playlist item. These controls require operator permission. Albums & Discs provides the additional insertable single/album discs. Use distinct IDs for playlist items and insertable discs. Generate again after creating a playlist to register its custom item, then restart both server and clients. The generator installs both behavior and resource packs while retaining pack UUIDs, unrelated entries, uploads and rotating backups.

Offline pack generation is available with python -m endstone_music.pack_generator --data <data-directory> --uploads <uploads-directory> --output <output-directory> --playlists <playlists.json>. It creates packs and registries without activating a world. See INSTALL.md for installation and rollback.
