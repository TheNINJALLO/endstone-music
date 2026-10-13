# 0.2.0 development build

- Add ordered persistent playlists and server-wide operator playback with generated non-spatial streamed sound aliases.
- Add editable mobile-friendly playlist forms, console edits, loop/next/stop/status and generated custom playlist items.
- Add real custom jukebox BP block, RP textures/name, dimension-aware persistent binding and operator controls.
- Suppress legacy audio while global music owns the channel. Narrow join sounds and stops to the joining player and named sound.
- Retain source uploads, validate durations/IDs/paths, preserve RP UUIDs and existing definitions, build staged packs with backups, activate BP/RP without erasing unrelated entries.
- Add reload/disable/quit cleanup, loaded-block checks and stale-form safeguards.
- Require Python 3.11 and Endstone >=0.11.14,<0.12; use installed FFmpeg/ffprobe instead of executable auto-downloads.
- Add local tests, installation/rollback guidance and an explicit live-client acceptance checklist.
