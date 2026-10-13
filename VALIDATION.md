# Validation record

Date: 2026-10-13 UTC. Local Python 3.12. Target Python minimum: 3.11.

## Baseline

Source: https://github.com/TheNINJALLO/endstone-music/tree/841b12e5954f10da444b1d1f21cceb7d5163bc9e

All eight original files were fetched at that commit and their exact Git blob SHA-1 values verified before edits (see bundle `source_manifest.json`). Original baseline was retained separately.

- `python -m compileall -q music_upgrade/baseline`: passed.
- In baseline: `python -c 'from setuptools.build_meta import build_wheel; build_wheel("../baseline_dist")'`: passed, 0.1.2 wheel.
- Baseline repository contains no automated tests.
- Endstone runtime is not installed in this environment. No live server/world connection was made.

## Final checks

From the editable source directory:

- `python run_tests.py`: **30 tests passed**. Seven builder state/store tests, plus 23 independent reviewer tests run in isolated Python subprocesses.
- `python -m compileall -q src`: passed.
- `python -c 'from setuptools.build_meta import build_wheel; build_wheel("dist")'`: passed, `endstone_music-0.2.0-py3-none-any.whl`.
- Offline generator created complete BP/RP template with a real jukebox block, empty `lobby` playlist item, manifests, PNG textures and language entry; no audio is bundled.
- Template JSON parsed successfully; pack/module UUIDs are unique and BP dependency equals RP UUID/version; both original PNGs decode as 16×16 RGBA.

Tests cover duration/pitch timing, looping, terminal end, snapshot edits, replacement, empty playlists, stop and callback failures; persistence/reload/validation; permissions and item identity; dimension binding, stale forms, unloaded/missing block cleanup, unlink ownership and duplicate events; reload/disable and old join callback interference; actual local FFmpeg audio conversion, retained input bytes, 2D aliases, migration of existing sound definitions, malformed world JSON, symlink path rejection and pack-list idempotence/preservation.

Endstone-facing checks use mocks based on verified v0.11.14 signatures. FFmpeg conversion is real, but sound packets are mocked. Template validation checks structure and assets; it is not an in-game Bedrock content validator. A wheel build does not prove the server loads it. No full type checker/linter was installed, and no live Endstone startup, Bedrock client, content-log, dimension transition or audible no-fade test was run.

## Required before production

Run the full checklist in INSTALL.md on a backed-up test server with the actual Endstone/BDS versions and at least two clients, including a non-operator. Verify pack acceptance, custom item/block registration, mobile interactions, global audio continuity, cross-dimension behavior and old triggers. Late joins deliberately wait for the next track; no unsupported seek synchronization is claimed.

See docs/API_EVIDENCE.md for official source evidence and compatibility limits. Nothing was pushed, deployed, merged or restarted remotely.

## Artifact integrity

The distributable patch was applied with `git apply --check` and `git apply` to a clean copy of the eight verified baseline files. Every resulting editable source/document/test file byte-matched the final source tree. All five packaged Python modules in the wheel byte-matched their source counterparts. The bundle includes per-file SHA-256 checksums and excludes build caches, egg-info and rotating pack backups. Typed command overloads were separately checked against Endstone's official usage parser and type map; no live command registration test is implied.
