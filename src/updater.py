"""Auto-update from GitHub Releases.

On start the app asks the GitHub API for the latest release. If its tag is newer
than VERSION and it has a .zip asset, the user is offered the update: the zip is
downloaded, a small batch script waits for the app to exit, copies the new files
over the install folder and restarts the app.
"""
import json
import os
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

from version import GITHUB_REPO, VERSION

EXE_NAME = "LandingTrainer.exe"
SYS32 = r"%SystemRoot%\System32"  # absolute paths: never pick up e.g. Git's find.exe from PATH
UA = {"User-Agent": "LandingTrainer-Updater", "Accept": "application/vnd.github+json"}


def parse_version(tag):
    nums = []
    for part in tag.strip().lstrip("vV").split("."):
        digits = "".join(c for c in part if c.isdigit())
        nums.append(int(digits or 0))
    return tuple((nums + [0, 0, 0])[:3])


def enabled():
    return bool(GITHUB_REPO) and getattr(sys, "frozen", False)


def check(repo=GITHUB_REPO, current=VERSION, timeout=6):
    """Return the newer release as dict(version, notes, url, size) or None."""
    req = urllib.request.Request(f"https://api.github.com/repos/{repo}/releases/latest", headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        rel = json.load(r)
    if rel.get("draft") or rel.get("prerelease"):
        return None
    if parse_version(rel.get("tag_name", "0")) <= parse_version(current):
        return None
    assets = [a for a in rel.get("assets", []) if a["name"].lower().endswith(".zip")]
    if not assets:
        return None  # release exists but the build has not been attached yet
    return dict(version=rel["tag_name"].lstrip("vV"), notes=(rel.get("body") or "").strip(),
                url=assets[0]["browser_download_url"], size=assets[0].get("size", 0))


def download_and_extract(url, progress=None):
    """Download the release zip and return (temp dir, folder that contains the new exe)."""
    tmp = tempfile.mkdtemp(prefix="LandingTrainerUpdate_")
    zpath = os.path.join(tmp, "update.zip")
    req = urllib.request.Request(url, headers={"User-Agent": UA["User-Agent"]})
    with urllib.request.urlopen(req, timeout=30) as r, open(zpath, "wb") as fh:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = r.read(256 * 1024)
            if not chunk:
                break
            fh.write(chunk)
            done += len(chunk)
            if progress and total:
                progress(done * 100 // total)
    out = os.path.join(tmp, "x")
    with zipfile.ZipFile(zpath) as z:
        z.extractall(out)
    for root, _dirs, files in os.walk(out):
        if EXE_NAME in files:
            return tmp, root
    raise RuntimeError(f"{EXE_NAME} not found in the downloaded update.")


def install_and_restart(tmp, new_dir, install_dir=None, pid=None, restart=True):
    """Start a detached batch script that replaces the files once this process has exited."""
    install_dir = install_dir or os.path.dirname(sys.executable)
    pid = pid or os.getpid()
    bat = os.path.join(tmp, "apply_update.bat")
    lines = [
        "@echo off",
        ":wait",
        f'{SYS32}\\tasklist.exe /FI "PID eq {pid}" 2>nul | {SYS32}\\find.exe "{pid}" >nul'
        f' && ({SYS32}\\ping.exe -n 2 127.0.0.1 >nul & goto wait)',
        f'{SYS32}\\robocopy.exe "{new_dir}" "{install_dir}" /E /IS /IT /R:5 /W:1 /NFL /NDL /NJH /NJS /NP >nul',
    ]
    if restart:
        lines.append(f'start "" "{os.path.join(install_dir, EXE_NAME)}"')
    lines.append(f'(goto) 2>nul & rmdir /s /q "{tmp}"')
    with open(bat, "w", encoding="mbcs") as fh:
        fh.write("\r\n".join(lines) + "\r\n")
    # CREATE_NO_WINDOW keeps a hidden console; tasklist/robocopy fail under DETACHED_PROCESS.
    subprocess.Popen(["cmd", "/c", bat], creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
    return bat
