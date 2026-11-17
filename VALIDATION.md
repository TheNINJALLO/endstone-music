# Music 0.2.3 / Endstone 0.11.16 validation

Date: 2026-11-16. The current SDK contract and playback suites ran against native Endstone 0.11.16 bindings: 110 checks, with 108 passing and two Windows symlink checks skipped. A new runtime-pair test verifies scoped playback on Bedrock 26.65 and rejects unreviewed SDK/runtime combinations. Both official BDS 1.26.65.1 archives and executable hashes were verified. Real client audio remains unqualified. Earlier release validation follows unchanged.

# Music 0.2.2 validation

Date: 2026-11-16. Local host: Windows x86-64, Python 3.12.14, native Endstone 0.11.15 SDK.

- `python run_tests.py`: 109 tests; 107 passed and two existing symlink checks skipped because this Windows account cannot create symlinks.
- Twelve new checks cover PATH preference, Linux/Windows tool selection, initial installation, offline cache reuse, cache corruption, SHA-256 rejection, download failure/retry, invalid compression, cancellation and preservation of existing packs on installation failure.
- A real conversion with an empty PATH downloaded both Windows x64 tools, verified their pinned SHA-256 digests and produced stereo and mono Vorbis OGG files. A fresh generator reused the cached executables with network access disabled and converted the source again.
- Startup still registers its music hooks without accessing the download function. Conversion and tool setup use the existing background generation worker.

No live server or audible Bedrock-client playback test was performed for this fix. Linux tool execution remains for Linux CI/server qualification; platform selection is covered locally.

## Historical 0.2.1 validation

Date: 2026-11-04. Local host: Windows x86-64, Python 3.11.9, native Endstone 0.11.15 SDK. Target: Linux x86-64, BDS 1.26.60.6, protocol 2225.

- python run_tests.py: 97 tests; 95 passed locally and two symlink checks skipped because this Windows account cannot create symlinks. Both execute in the Linux release workflow.
- Coverage includes the previous 0.2.0 playlist/control/custom-content checks, native event/NBT signatures, scoped packet adaptation, real stereo/mono FFmpeg conversion, follow-player albums, late global listeners, persistence, pack migration and failure rollback.
- python -m compileall -q src tests tools and wheel/bundle integrity checks are part of packaging.
- Official Linux and Windows BDS package identities and executable hashes are recorded in compatibility/.

No live Linux server startup, outbound server packet capture, connected Bedrock client or audible playback test has been completed. See docs/ACCEPTANCE.md for qualification. Automated success does not certify in-game audio or content registration.

The release workflow reruns all suites on Linux before publishing the wheel, setup bundle and artifact checksums. See the workflow result for its authoritative CI outcome.

## Historical 0.2.0 development validation

The following is the prior release's historical record; its environment, deployment statements and late-join behavior describe 0.2.0.

### Prior validation record

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
