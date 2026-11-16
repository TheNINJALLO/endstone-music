"""Install conversion tools on demand without pip or system-wide changes."""

import gzip
import hashlib
import os
import platform
import shutil
import tempfile
import threading
import time
from pathlib import Path
from urllib.request import Request, urlopen

from .content_pack import reject_links


# Published executable SHA-256 digests for the pinned upstream release:
# https://github.com/eugeneware/ffmpeg-static/releases/tag/b6.1.1
RELEASE = "b6.1.1"
BASE_URL = f"https://github.com/eugeneware/ffmpeg-static/releases/download/{RELEASE}"
DIGESTS = {
    "linux-x64": {
        "ffmpeg": "e7e7fb30477f717e6f55f9180a70386c62677ef8a4d4d1a5d948f4098aa3eb99",
        "ffprobe": "4f231a1960d83e403d08f7971e271707bec278a9ae18e21b8b5b03186668450d"
    },
    "win32-x64": {
        "ffmpeg": "04e1307997530f9cf2fe35cba2ca7e8875ca91da02f89d6c7243df819c94ad00",
        "ffprobe": "3a7e2dc003dc2cd1472827e4c7c4f056ae1ae0ae7c5bbc580c99b49827351ba4"
    }
}
_INSTALL_LOCK = threading.Lock()


def _check_cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise RuntimeError("Audio tool installation cancelled")


def _target():
    system, machine = platform.system(), platform.machine().lower()
    if system not in ("Linux", "Windows") or machine not in ("amd64", "x86_64"):
        raise RuntimeError(
            f"Automatic audio tool installation is unavailable for {system} {machine}; "
            "install FFmpeg and ffprobe on PATH"
        )
    return "win32-x64" if system == "Windows" else "linux-x64"


def _digest(path, cancel):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            _check_cancel(cancel)
            digest.update(chunk)
    return digest.hexdigest()


def _download(tool, target, destination, cancel):
    request = Request(f"{BASE_URL}/{tool}-{target}.gz", headers={"User-Agent": "Endstone-Music"})
    temporary = None
    try:
        fd, name = tempfile.mkstemp(prefix=f".{tool}-", suffix=".download", dir=destination.parent)
        temporary = Path(name)
        digest, size = hashlib.sha256(), 0
        deadline = time.monotonic() + 300
        with os.fdopen(fd, "wb") as output:
            with urlopen(request, timeout=15) as response, gzip.GzipFile(fileobj=response) as source:
                while True:
                    _check_cancel(cancel)
                    if time.monotonic() > deadline:
                        raise RuntimeError("Audio tool download exceeded five minutes")
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > 256 * 1024 * 1024:
                        raise ValueError("Audio tool download exceeds the size limit")
                    digest.update(chunk)
                    output.write(chunk)
        if digest.hexdigest() != DIGESTS[target][tool]:
            raise ValueError(f"SHA-256 verification failed for {tool}")
        _check_cancel(cancel)
        temporary.chmod(0o755)
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def ensure_audio_tools(data_path, *, cancel=None, logger=None):
    """Prefer PATH; cache verified missing tools in the plugin's data folder."""
    _check_cancel(cancel)
    tools = {tool: shutil.which(tool) for tool in ("ffmpeg", "ffprobe")}
    if all(tools.values()):
        return tools["ffmpeg"], tools["ffprobe"]
    target = _target()
    cache = Path(data_path) / "tools" / f"ffmpeg-{RELEASE}-{target}"
    while not _INSTALL_LOCK.acquire(timeout=0.2):
        _check_cancel(cancel)
    try:
        _check_cancel(cancel)
        reject_links(cache, tree=True)
        cache.mkdir(parents=True, exist_ok=True)
        for tool in tools:
            if tools[tool]:
                continue
            destination = cache / (tool + (".exe" if target.startswith("win32") else ""))
            try:
                if not destination.is_file() or _digest(destination, cancel) != DIGESTS[target][tool]:
                    if logger is not None:
                        logger.info(f"Installing {tool} for music conversion (first download may take a few minutes)...")
                    _download(tool, target, destination, cancel)
                    if logger is not None:
                        logger.info(f"Installed {tool}: {destination}")
                if os.name != "nt":
                    destination.chmod(0o755)
                tools[tool] = str(destination.resolve())
            except Exception as error:
                _check_cancel(cancel)
                raise RuntimeError(
                    f"Could not automatically install {tool}: {error}. "
                    "Allow HTTPS downloads from github.com and release-assets.githubusercontent.com, "
                    "then retry /cmusic generate, or install FFmpeg and ffprobe on PATH"
                ) from error
        return tools["ffmpeg"], tools["ffprobe"]
    finally:
        _INSTALL_LOCK.release()
