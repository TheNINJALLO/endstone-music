# 0.2.3

- Support Endstone 0.11.16 / BDS 1.26.65.1 with the unchanged protocol-2225 sound layout. Retain the explicitly reviewed legacy runtime pair and reject unreviewed combinations.
- Update conversion-package tooling and runtime profiles while retaining automatic conversion dependencies.

# 0.2.2

- Automatically install missing FFmpeg and ffprobe during conversion on Linux/Windows x86-64, using pinned downloads and SHA-256 verification.
- Prefer existing PATH tools and reuse verified downloads from the Music data folder; require no extra Python dependencies or system-wide installation.
- Keep setup on the conversion worker, support cancellation and retries, and retain source audio and existing packs if setup fails.
- Add installation, cache, checksum, platform, failure and cancellation regression tests and update setup instructions.

# 0.2.1

- Add follow-player single-track and album discs, persistent insert/eject and configurable per-block jukebox presets.
- Add the Endstone 0.11.15 native sound boundary and scoped protocol-2225 playback-position adapter for BDS 1.26.60.6.
- Preserve operator global playlists, custom content generation, existing playlist stores, bindings, pack UUIDs and installed pack entries from 0.2.0.
- Share one playback voice per listener; prevent join/legacy triggers interrupting global music and keep pushed albums through movement, chunk unloading and dimension changes.
- Convert stereo/spatial OGG in a background worker using installed FFmpeg; retain uploads and roll back RP/BP and metadata on publication failure.
- Add native API, playback, disc storage, migration and custom-content checks and a Linux acceptance checklist.

# 0.2.0

- Add ordered persistent playlists and server-wide operator playback with generated non-spatial streamed sound aliases.
- Add editable mobile-friendly playlist forms, console edits, loop/next/stop/status and generated custom playlist items.
- Add real custom jukebox BP block, RP textures/name, dimension-aware persistent binding and operator controls.
- Suppress legacy audio while global music owns the channel. Narrow join sounds and stops to the joining player and named sound.
- Retain source uploads, validate durations/IDs/paths, preserve RP UUIDs and existing definitions, build staged packs with backups, activate BP/RP without erasing unrelated entries.
- Add reload/disable/quit cleanup, loaded-block checks and stale-form safeguards.
- Require Python 3.11 and Endstone >=0.11.14,<0.12; use installed FFmpeg/ffprobe instead of executable auto-downloads.
- Add local tests, installation/rollback guidance and an explicit live-client acceptance checklist.
