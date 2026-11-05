"""Verify and inspect official BDS files without running or modifying a server."""

import argparse
import hashlib
import json
import re
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def inspect(platform, profile, directory, download):
    config = profile["platforms"][platform]
    directory = directory / platform
    directory.mkdir(parents=True, exist_ok=True)
    archive = directory / "bedrock-server-1.26.60.6.zip"
    if not archive.exists():
        if not download:
            raise FileNotFoundError(f"Missing {archive}; supply --download or copy the official archive here")
        request = urllib.request.Request(config["url"], headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request, timeout=60) as response, archive.open("wb") as output:
            while data := response.read(1024 * 1024):
                output.write(data)
    if digest(archive) != config["archive_sha256"]:
        raise ValueError(f"Unexpected {platform} archive SHA-256; refusing to inspect another build")
    executable = directory / config["executable"]
    with zipfile.ZipFile(archive) as package:
        with package.open(config["executable"]) as source, executable.open("wb") as output:
            while data := source.read(1024 * 1024):
                output.write(data)
    executable_hash = digest(executable)
    if executable_hash != config["executable_sha256"]:
        raise ValueError(f"Unexpected {platform} executable SHA-256")
    binary = executable.read_bytes()
    terms = (b"JukeboxBlock", b"JukeboxBlockActor", b"RecordItem", b"PlaySoundPacket", b"StopSoundPacket")
    strings = {}
    for term in terms:
        matches = list(re.finditer(re.escape(term), binary))
        strings[term.decode()] = {
            "count": len(matches),
            "sample_file_offsets": [match.start() for match in matches[:8]],
        }
    result = {
        "platform": platform, "bds_package": profile["bds_package"],
        "archive_sha256": digest(archive), "executable_sha256": executable_hash,
        "executable_size": len(binary), "strings": strings,
        "note": "String offsets identify evidence only; they are not callable function addresses or ABI layouts.",
        "private_memory_hooks": False, "connected_client_tested": False,
    }
    (directory / "inspection.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--platform", choices=("windows", "linux", "both"), default="both")
    parser.add_argument("--directory", type=Path, default=ROOT / "scratch" / "bds-1.26.60.6")
    args = parser.parse_args()
    profile = json.loads((ROOT / "compatibility" / "bds-1.26.60.6.json").read_text())
    platforms = ("windows", "linux") if args.platform == "both" else (args.platform,)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda platform: inspect(platform, profile, args.directory, args.download), platforms))
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
