[Download compatibility release v0.2.3](https://github.com/TheNINJALLO/endstone-music/releases/tag/v0.2.3).

> Compatibility update **0.2.3** targets **Endstone 0.11.16 / BDS 1.26.65.1**, protocol **2225**, Python **3.11+**. API level remains **0.11**. Keep configuration and player data when replacing the wheel. Earlier acceptance records below describe their original builds; current qualification is tracked in the workspace upgrade report.

<!-- endstone-professional-header:start -->
<p align="center">
  <img src="docs/assets/banner.svg" width="100%" alt="Endstone Music &mdash; Album discs, follow-player audio, global playlists and custom jukeboxes">
</p>

<p align="center">
  <a href="https://github.com/TheNINJALLO/endstone-music/actions/workflows/wheel-release.yml"><img alt="Build" src="https://img.shields.io/github/actions/workflow/status/TheNINJALLO/endstone-music/wheel-release.yml?branch=main&amp;style=for-the-badge&amp;logo=githubactions&amp;logoColor=white&amp;label=Build"></a>
  <a href="https://github.com/TheNINJALLO/endstone-music/releases/latest"><img alt="Latest release" src="https://img.shields.io/github/v/release/TheNINJALLO/endstone-music?display_name=tag&amp;style=for-the-badge&amp;label=Release"></a>
</p>

<p align="center">
  <img alt="Endstone 0.11.16" src="https://img.shields.io/badge/Endstone-0.11.16-52b7a8?style=flat-square">
  <img alt="API 0.11" src="https://img.shields.io/badge/API-0.11-63b8ff?style=flat-square">
  <img alt="BDS 1.26.65.1" src="https://img.shields.io/badge/BDS-1.26.65.1-8b7dff?style=flat-square">
  <img alt="Python >=3.11" src="https://img.shields.io/badge/Python-%3E=3.11-3776AB?style=flat-square&amp;logo=python&amp;logoColor=white">
</p>

<p align="center">
  <strong>Album discs, follow-player audio, global playlists and custom jukeboxes.</strong>
</p>

<p align="center">
  <a href="#what-it-does">What it does</a> &bull;
  <a href="#how-to-use">How to use</a> &bull;
  <a href="#commands-and-permissions">Commands</a> &bull;
  <a href="#install">Install</a> &bull;
  <a href="https://github.com/TheNINJALLO/endstone-music/releases">Releases</a>
</p>

## Overview

Music **0.2.3** includes single-track and album discs, configurable jukeboxes, operator global playlists and generated audio/resource packs, with automatic setup of conversion tools.

**Follow Player is on by default:** once a nearby listener hears a disc, the remaining track or album stays with them as they move away. The initial radius controls admission; it does not send that album to unrelated distant players. Global playlists intentionally play to everyone.

## What it does

- Insert, eject, skip/restart and recover persistent single-track or album discs.
- Set per-block presets for radius, volume, pitch and optional positional fading.
- Edit ordered global playlists and use generated custom playlist items/jukebox blocks.
- Convert OGG, MP3 and WAV uploads into streamed stereo and mono assets in a background worker.
- Keep one plugin-owned voice per listener and use the scoped protocol-2225 adapter for current-position playback.
- Retain uploads, existing pack identities and unrelated pack entries during generation.

## How to use

1. Install the wheel, then start the server once to create the Music data folder.
2. Set `target_world_name` in `plugins/music/config.json` to the actual world folder.
3. Put audio in `plugins/music/uploads/`, run `/cmusic generate`, and wait for completion. Missing FFmpeg/ffprobe tools install automatically on the conversion worker; the first conversion needs internet access.
4. Restart the server and reconnect clients, accepting the generated resource pack. Generation installs both the resource and behavior packs.
5. Open `/cmusic` > **Albums & Discs**, create a disc with one generated track ID or an ordered list, then select it to receive the item.
6. Right-click a vanilla jukebox with that disc. Normal right-click ejects; sneak-right-click skips or restarts. Leave an empty inventory slot for ejection.
7. For server-wide music, use **Global Playlists** instead. Generate again after adding a global playlist if you want its custom playlist item, then restart/reconnect.

Follow the [complete how-to](HOW-TO-USE.md) for no-fade playback, custom block setup, triggers, login audio, global playlists, configuration and troubleshooting. Existing servers upgrading from 0.2.0 should regenerate the packs and restart/reconnect.

## Commands and permissions

Management requires `endstone_music.command.cmusic` (operator by default). Ordinary players can use configured insertable discs on accepted blocks. Global playlist controls require music operator permission.

| Command | Purpose |
|---|---|
| `/cmusic` | Open the operator menu |
| `/cmusic status` | Runtime, adapter counters, track/disc counts and global playback |
| `/cmusic generate` or `/cmusic migrate` | Generate and activate the selected world's resource/behavior packs |
| `/cmusic reload` | Validate config/playlists, stop global audio and restart stored-disc playlists |
| `/cmusic give <disc-id> [player name]` | Give an insertable single/album disc to an online player |
| `/cmusic bind <preset-id>` | Assign a preset on the next matching block click |
| `/cmusic recover` | Open stored-disc recovery |
| `/cmusic playlists` | Manage global playlists |
| `/cmusic play <playlist-id>` | Play a global playlist for everyone |
| `/cmusic next` | Advance the global playlist |
| `/cmusic stop` | Stop all plugin-owned music; keep inserted discs recoverable |
| `/cmusic give jukebox` | Give the generated custom jukebox block in-game |
| `/cmusic give <playlist-id>` | Give a generated global playlist item in-game |
| `/cmusic playlist ...` | Create, add, remove, move, loop or delete a global playlist |

The [full command reference](HOW-TO-USE.md#command-reference) includes playlist editing syntax. Keep global playlist and insertable-disc IDs distinct; reserve `jukebox` for the generated block.

## Compatibility

| Component | Target |
|---|---|
| Plugin | `0.2.3` |
| Endstone / API | `0.11.16` / `0.11` |
| BDS / runtime / protocol | `1.26.65.1` / `26.65` / `2225` |
| Server platform | Linux x86-64 |
| Python | `>=3.11` |
| Audio tools | Existing `ffmpeg`/`ffprobe` on PATH, or automatic download on Linux/Windows x86-64 |

Playback is gated to the reviewed runtime combination. Unsupported runtimes keep administration and stored-disc recovery available, but disable new playback. Missing converter executables are downloaded from a pinned [ffmpeg-static release](https://github.com/eugeneware/ffmpeg-static/releases/tag/b6.1.1), verified with SHA-256 and cached under `plugins/music/tools/`. Startup and playback do not trigger downloads; cached tools work offline. No pip command, administrator access or PATH changes are needed.

The current Windows validation ran **109 automated tests: 107 passed and two symlink checks were skipped**. A separate real conversion installed both tools with an empty PATH, produced stereo/mono Vorbis audio and reused the cache offline. The previous 0.2.1 release passed 97 tests in Linux CI. Live server integration and audible Bedrock-client playback remain unverified; see the [validation record](VALIDATION.md) and [acceptance checklist](docs/ACCEPTANCE.md).

## Install

Download `endstone_music-0.2.3-py3-none-any.whl` from [Music v0.2.3](https://github.com/TheNINJALLO/endstone-music/releases/tag/v0.2.3). To build the wheel from this source:

```bash
python -m pip install build
python -m build --wheel
```

Stop the server, back up the world and Music data, replace the older Music wheel in `plugins/`, and restart. See [installation, upgrade and rollback](INSTALL.md). The optional setup ZIP contains the wheel and the documentation snapshot from release time; current guides are maintained in this repository.

## Configuration and data

The active data folder is normally `plugins/music/`. `config.json` holds insertable albums/discs, triggers, join settings and jukebox presets. `playlists.json` holds operator global playlists and custom-block links; `jukeboxes.json` holds the exact inserted items. Retain these files, `uploads/`, `pack_metadata.json` and the installed world packs together when backing up or migrating.

Use [the configuration example](examples/albums-and-jukeboxes.json) as a schema reference. Its sample durations are placeholders: use measured generated durations or the real duration of external sound events. Merge your settings rather than replacing a live config with the example.

Custom inserted discs use plugin storage rather than the vanilla record slot; hopper/comparator automation is not included. The built-in global custom block/items are generated by the plugin; additional artwork and arbitrary custom block/item IDs must be registered by installed packs.

## Verification and release automation

- [Full how-to and troubleshooting](HOW-TO-USE.md)
- [Install and rollback](INSTALL.md)
- [Native API and protocol adapter](docs/ABI_ADAPTER.md)
- [Validation record](VALIDATION.md) and [server/client acceptance](docs/ACCEPTANCE.md)
- [Exact BDS identities](compatibility/bds-1.26.65.1.json)

After installing the project and audio tools, run `python run_tests.py`. The [release workflow](.github/workflows/wheel-release.yml) reruns the suites on Linux, builds the wheel/setup bundle and uploads artifacts. A new package version on `main`, or a matching `v*` tag, publishes its release; branch builds leave existing releases unchanged.
<!-- endstone-professional-header:end -->
