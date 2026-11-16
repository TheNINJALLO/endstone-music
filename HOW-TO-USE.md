# Endstone Music 0.2.2 - How to use

[README](README.md) | [Installation and rollback](INSTALL.md) | [Live server acceptance](docs/ACCEPTANCE.md)

Target: Linux x86-64, Endstone **0.11.15**, BDS **1.26.60.6** (runtime **26.60**, protocol **2225**), Python **3.11+**. Conversion uses FFmpeg/ffprobe on PATH or installs missing tools automatically on Linux/Windows x86-64. The first conversion needs internet access; verified tools are cached under `plugins/music/tools/` for later offline use.

Music has two ways to play albums:

| Playback | Who starts it | Who hears it | Controls |
|---|---|---|---|
| Insertable single/album disc | Any player holding a configured disc | Nearby listeners initially; Follow Player keeps the rest of the album with them | Insert, eject, sneak-click to skip/restart |
| Global playlist | Operator or holder of `endstone_music.command.cmusic` | Everyone online, across dimensions | Global Playlists menu, play, next, stop |

## 1. Install and generate the audio packs

1. Follow [INSTALL.md](INSTALL.md) to install `endstone_music-0.2.2-py3-none-any.whl`. Keep only one Music wheel in `plugins/`.
2. Start the server once to create the plugin data folder, normally `plugins/music/`.
3. Set `target_world_name` in that folder's `config.json` to the world's directory name, for example `Bedrock level`. It must be a direct folder under `worlds/`.
4. Put your `.ogg`, `.mp3` or `.wav` files in `plugins/music/uploads/`. Use distinct names such as `intro.wav` and `main.mp3`.
5. As an operator, run `/cmusic generate`. Wait for the completion message. Conversion and any first-time tool downloads run in a background worker; a second generation request will not start another job. The server log reports tool installation progress.
6. Restart the server and reconnect clients. Accept/download the resource pack. Generation installs both the resource and behavior packs into the selected world and preserves unrelated pack-list entries.
7. Run `/cmusic status`. For this target, it should show `adapter supported=True`. Use `generated_tracks.json` for exact sound IDs and measured durations: `intro.wav` becomes `custom.intro`.

Keep the source uploads and `pack_metadata.json`. Repeated generation reuses unchanged audio and retains the existing pack identities. Regenerate after upgrading from 0.2.0, then restart and reconnect. New jukebox presets or new global playlist item IDs also require regeneration and a restart.

## 2. Create single-track and album discs

1. Open `/cmusic` > **Albums & Discs** > **Create album / single-track disc**.
2. Enter a unique ID, for example `intro_single` or `server_album`, and a display title.
3. In **Ordered track IDs**, enter one generated ID for a single (`custom.intro`) or a comma-separated album (`custom.intro, custom.main`). Use the actual IDs from your generated library.
4. Choose whether to loop. Leave the base item as `minecraft:music_disc_cat`, or choose another item already registered on the server.
5. Submit, reopen **Albums & Discs**, and select the saved entry to receive its item. You can also use `/cmusic give server_album` in-game or `/cmusic give server_album PlayerName` for an online player.

An album ID and its ordered tracks are saved in `config.json`. The menu can save a single-track entry under `albums`; manually configured `discs` entries use one `track`. Both produce usable single-track discs. [The example configuration](examples/albums-and-jukeboxes.json) shows both schemas; merge the relevant sections into your config and replace its placeholder durations with measured values.

Use different IDs for insertable discs and global playlists, and reserve `jukebox` for the generated block. With a shared ID, the direct `/cmusic give <id>` command chooses the insertable disc.

The item carries playlist metadata. Renaming an ordinary vanilla disc does not create a custom disc. Custom disc artwork or a custom base item requires an installed behavior/resource pack that registers it.

## 3. Insert, eject, skip and recover discs

The default disc preset accepts `minecraft:jukebox` within a 32-block initial hearing radius.

| Action | Result |
|---|---|
| Right-click an empty accepted block while holding a custom disc | Inserts exactly one item and starts its track/album |
| Right-click an occupied managed block normally | Ejects the stored item to an empty inventory slot |
| Sneak-right-click an occupied managed block | Skips to the next track, or restarts a completed/stopped playlist |
| Break an occupied managed block | Returns the stored disc before allowing the break; a full inventory keeps the block intact |
| `/cmusic recover` as an operator | Opens stored discs for recovery, including discs in removed or unloaded blocks |

Eject a vanilla disc already in a jukebox before inserting a custom disc. Leave an empty inventory slot for ejection or recovery. A failed storage write rolls back the inventory change rather than intentionally consuming or duplicating the item.

Stored discs survive restarts and reloads; their playlists restart from the beginning. `/cmusic stop` stops plugin music but leaves discs stored. Sneak-click the block to restart it, or eject and reinsert.

Custom discs are stored in the plugin's `jukeboxes.json`, separately from the vanilla block actor's record slot. Vanilla hopper/comparator automation for these discs is not implemented. Keep `jukeboxes.json` with the world and inventory backups.

## 4. Keep the whole song or album with the listener

**Follow Player is enabled by default**, including when an older preset omits `follow_player`.

- A listener must initially be in range of the available jukebox, in the same dimension. Once attached, they keep the remaining track or album when walking away or unloading the source chunk.
- Playback uses streamed stereo, non-positional audio, so walking does not fade it or restart the track. A dimension change may reissue audio at the current track offset.
- Players elsewhere do not receive that album just because another player started listening. Disconnecting removes a listener's attachment; reconnecting far away does not restore it.
- Walking past another jukebox does not replace the attached album. Inserting or skip/restarting at a different jukebox explicitly selects it.
- Completion, stop, eject or replacement ends playback. Looping albums keep playing until stopped or ejected. Personal audio can take priority; operator global playback suppresses legacy triggers and join sounds.

For normal distance fading, turn off **Follow listeners for the whole track or album (no fading)** in the preset, or set `follow_player` to `false` in its configuration. Positional mode uses mono events, cuts off outside the radius and stays dimension-limited. External packs must define the personal sound event with `is3D=false` to support no-fade playback.

## 5. Configure individual jukeboxes or other speaker blocks

1. Open `/cmusic` > **Custom Jukebox Setup** > **Create / edit preset**.
2. Set the preset ID, accepted block ID, hearing radius, volume, pitch and Follow Player toggle. Saving an existing ID replaces that preset's settings.
3. Run `/cmusic generate`, wait, restart the server and reconnect clients so the preset's spatial sound events are available.
4. Run `/cmusic bind lounge` (replace `lounge` with your preset ID), then right-click a block of that preset's exact type. Eject any inserted disc before changing its preset.
5. Insert a configured disc. Different blocks of the same type can use different bound presets. Unbound blocks use the first matching preset in the config.

Presets can use existing blocks such as `minecraft:jukebox` or `minecraft:noteblock`, or custom block IDs already registered by the server's packs. This form configures playback; it does not create new block models or item artwork.

## 6. Play a global playlist and use the generated custom jukebox

Global playlists use their own `playlists.json`; creating an insertable album does not automatically create a global playlist.

1. Generate the audio first so its sound IDs and durations are registered.
2. Open `/cmusic` > **Global Playlists** > **Create playlist**.
3. Choose an ID containing lowercase letters, digits or underscores, up to 48 characters. Enter ordered tracks separated by semicolons, for example `custom.intro; custom.main`. Duration can be omitted for generated audio, or supplied as `custom.intro=60` when the actual duration is known.
4. Save and select **Play for everyone**, or use `/cmusic play lobby`. Everyone hears the generated non-positional aliases; new listeners join at the current track position. `/cmusic next` advances this global playlist.
5. To use physical playlist controls, run `/cmusic generate` again after creating the playlist, restart and reconnect. Use `/cmusic give jukebox` to receive the generated `endstone_music:jukebox`, place it, and use `/cmusic give lobby` to receive the custom playlist item.
6. Right-click the custom block with the playlist item to link it. Clicking the linked block opens its operator controls; use **Play for everyone**, **Next track**, **Stop global music** or **Unlink this jukebox**. Using a playlist item on another block starts its global playlist.

Only music operators control these global playlist items/blocks. Ordinary players may still use configured insertable discs on their accepted blocks. A linked global session continues if its source chunk unloads; a loaded block detected as removed ends that linked session. Its binding remains dimension-specific.

Edits to a global playlist affect its next start; the active session keeps its snapshot. `/cmusic stop` stops all plugin music, while **Stop global music** in the global menu stops only that global session, allowing other eligible sources to resume.

## 7. Triggers and login music

The main menu retains **Add New Trigger**, **Manage Triggers**, **Join Sound Settings** and **Per-Player Join Sounds**.

- Trigger modes are item plus block, item only, or block only. Configure sound, volume, pitch, distance, broadcast, loop, duration and Follow Player.
- Item-only triggers target the clicking player, or everyone when Broadcast is enabled. A block trigger with Broadcast off targets the clicking player; with Broadcast on, eligible nearby listeners can hear it. Follow Player keeps admitted listeners attached.
- Generated durations are used when available. Supply the actual duration for external sounds, especially when looping; timing depends on it.
- Join sounds are personal and delayed one second after login. Per-player settings override the default. Old login callbacks are invalidated on disconnect; an operator global session suppresses join playback and legacy triggers.

## Command reference

All management commands use `endstone_music.command.cmusic` (operator by default). Run menu, bind, recover and custom-item give commands in-game.

| Command | Purpose |
|---|---|
| `/cmusic` | Open the main menu |
| `/cmusic status` | Runtime identity, adapter counters, library counts and current global playlist |
| `/cmusic generate` | Build and activate the selected world's RP/BP; restart/reconnect afterwards |
| `/cmusic migrate` | Run the current pack generator |
| `/cmusic reload` | Validate config and playlists; stop global audio and restart stored-disc playlists |
| `/cmusic give <disc-id> [player name]` | Give a configured insertable single/album disc; target must be online |
| `/cmusic bind <preset-id>` | Bind a preset on the next click of a matching block |
| `/cmusic recover` | Recover a stored disc |
| `/cmusic playlists` | Open global playlist management, or list playlists in console |
| `/cmusic play <playlist-id>` | Start a global playlist |
| `/cmusic next` | Advance the global playlist |
| `/cmusic stop` | Stop all plugin music; keep inserted discs recoverable |
| `/cmusic give jukebox` | Give the generated custom block to the operator |
| `/cmusic give <playlist-id>` | Give a generated global playlist item to the operator |
| `/cmusic playlist create <id>` | Create an empty global playlist |
| `/cmusic playlist add <id> <sound> [seconds]` | Append a track; generated durations allow omission of seconds |
| `/cmusic playlist remove <id> <track>` | Remove a track by its 1-based number |
| `/cmusic playlist move <id> <from> <to>` | Reorder tracks using 1-based numbers |
| `/cmusic playlist loop <id> <on\|off>` | Set looping |
| `/cmusic playlist delete <id>` | Delete a global playlist and its bindings |

## Data, troubleshooting and verification

| File in the Music data folder | Purpose |
|---|---|
| `config.json` | Triggers, join sounds, tracks, insertable albums/discs, presets and per-block preset bindings |
| `uploads/` | Original audio; retained during generation |
| `generated_tracks.json`, `track_durations.json` | Generated IDs, timing and spatial aliases |
| `sounds_registry.json`, `global_sounds_registry.json` | Generated sound registrations |
| `playlists.json` | Operator global playlists and custom-block links |
| `jukeboxes.json` | Exact stored insertable discs and their locations |
| `pack_metadata.json` | Stable RP/BP UUIDs and version |

- **No sound:** check `/cmusic status`, the client's accepted pack, the selected world, actual sound IDs and the resource/behavior pack content logs. Generation alone does not reload clients' packs.
- **Adapter unsupported or rejected packets:** use the exact target runtime and record the status counters. Stored-item recovery remains available on unsupported runtimes. See [ABI_ADAPTER.md](docs/ABI_ADAPTER.md).
- **Global track says generate first:** generate its 2D alias and reconnect clients before starting it. Unverified vanilla IDs are not accepted for global playback.
- **No item or block after giving:** generate after creating a global playlist and restart/reconnect to register its item; use unique IDs and leave inventory space.
- **Cannot eject:** leave an empty inventory slot. Check storage errors in the server log; use the operator recovery menu for inaccessible blocks.
- **Reload fails:** correct the JSON and unknown track/preset references. A config/playlist validation failure keeps the current in-memory library and audio; wait for an active generation job before retrying.

See [the validation record](VALIDATION.md) for automated results. Live Linux server integration and audible client playback still require the [acceptance checklist](docs/ACCEPTANCE.md), including movement, albums, permissions and pack registration.
