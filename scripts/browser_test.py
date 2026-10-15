"""Start a fresh local server and run Playwright in the same network namespace."""

import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

root = Path(__file__).resolve().parents[1]
temporary = tempfile.TemporaryDirectory(prefix="ghostframe-browser-")
database = str(Path(temporary.name) / "browser.db")
from ghostframe import CapturePolicy, Recorder, trace_tool

large_recorder = Recorder(database, policy=CapturePolicy(enabled=True))


@trace_tool(recorder=large_recorder)
def synthetic_read(index):
    return {"synthetic_index": index}


with large_recorder.run("Large SDK trace — playback-only") as large_id:
    for index in range(500):
        synthetic_read(index)
server = subprocess.Popen(
    [sys.executable, "-m", "ghostframe.cli", "--db", database, "serve"],
    cwd=root,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
try:
    for attempt in range(100):
        try:
            urllib.request.urlopen("http://127.0.0.1:8765/api/health", timeout=1)
            break
        except OSError:
            time.sleep(0.1)
    else:
        raise RuntimeError("Local API did not start")
    executable = root / ".browser/chromium"
    env = {**os.environ, "GHOSTFRAME_LARGE_RUN": large_id}
    if executable.exists():
        env["CHROMIUM_EXECUTABLE"] = str(executable)
        env["FONTCONFIG_PATH"] = str(root / ".browser/fonts")
    npm = "npm.cmd" if os.name == "nt" else "npm"
    result = subprocess.run([npm, "run", "e2e"], cwd=root / "web", env=env, check=False)
    raise SystemExit(result.returncode)
finally:
    server.terminate()
    server.wait(timeout=10)
    temporary.cleanup()
