"""Package the tested wheel and operator setup files, excluding BDS binaries."""

import hashlib
import json
import tomllib
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    version = project["version"]
    wheel = ROOT / "dist" / f"endstone_music-{version}-py3-none-any.whl"
    with zipfile.ZipFile(wheel) as archive:
        assert archive.testzip() is None, "Wheel archive integrity check failed"
        metadata = archive.read(f"endstone_music-{version}.dist-info/METADATA").decode()
        assert f"Version: {version}" in metadata.splitlines()
        for source in (ROOT / "src" / "endstone_music").glob("*.py"):
            assert archive.read(f"endstone_music/{source.name}") == source.read_bytes(), f"Outdated wheel source: {source.name}"
    bundle = ROOT / "dist" / f"endstone_music-{version}-bds-1.26.60.6.zip"
    files = [ROOT / name for name in ("README.md", "HOW-TO-USE.md", "INSTALL.md", "CHANGELOG.md", "VALIDATION.md", "docs/ABI_ADAPTER.md", "docs/ACCEPTANCE.md", "docs/assets/banner.svg", "tools/inspect_bds.py")]
    files += list((ROOT / "examples").glob("*.json"))
    files += list((ROOT / "compatibility").rglob("*.json"))
    with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(wheel, "plugins/" + wheel.name)
        for path in files:
            archive.write(path, str(path.relative_to(ROOT)).replace("\\", "/"))
    result = {"version": version, "wheel": wheel.name, "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
              "bundle": bundle.name, "bundle_sha256": hashlib.sha256(bundle.read_bytes()).hexdigest(),
              "live_linux_server_tested": False, "audible_playback_verified": False}
    (ROOT / "dist" / f"music-{version}-artifacts.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
