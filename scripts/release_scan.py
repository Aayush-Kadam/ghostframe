"""Select a portable source snapshot and scan it; never imply old Git history is sanitized."""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import subprocess
import zipfile

TEXT = {
    ".py",
    ".md",
    ".txt",
    ".json",
    ".yml",
    ".yaml",
    ".toml",
    ".tsx",
    ".ts",
    ".mjs",
    ".js",
    ".html",
    ".css",
    ".ps1",
    ".sh",
    ".csv",
    ".xml",
}
PATTERNS = {
    "user_home": re.compile(r"(?i)[a-z]:[\\/]+Users[\\/]+[^\\/\s\"'<>]+"),
    "unix_home": re.compile(r"/(?:home|Users)/[^/\s\"'<>]+/"),
    "private_workspace": re.compile("/work" + r"space/(?:scratch/)?[^/\s\"'<>]+"),
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "machine_hostname": re.compile(r"\b(?:LAPTOP|DESKTOP)-[A-Z0-9]{4,}\b", re.IGNORECASE),
}


def selected(name: str) -> bool:
    p = pathlib.PurePosixPath(name)
    if any(x in {".git", ".venv", "node_modules", "__pycache__", "build", "dist"} for x in p.parts):
        return False
    if p.suffix in {".db", ".db-wal", ".db-shm", ".pyc", ".bundle", ".whl"}:
        return False
    if name.startswith(("benchmarks/forensics/", "benchmarks/reports/M8-")):
        return False
    if name.startswith("benchmarks/reports/"):
        return name in {
            "benchmarks/reports/latest.json",
            "benchmarks/reports/latest.md",
            "benchmarks/reports/raw_results.csv",
            "benchmarks/reports/browser.json",
            "benchmarks/reports/browser-evidence.json",
            "benchmarks/reports/release-summary.json",
        }
    if name.startswith("docs/milestones/") and name != "docs/milestones/M9-RC.md":
        return False
    if name.startswith("scripts/m8r"):
        return False
    return not p.name.startswith("raw-")


def candidates(root: pathlib.Path) -> list[str]:
    if (root / ".git").exists():
        output = subprocess.check_output(
            ["git", "-C", str(root), "ls-files", "--cached", "--others", "--exclude-standard"], text=True
        )
        return sorted({n for n in output.splitlines() if selected(n) and (root / n).is_file()})
    return sorted(
        p.relative_to(root).as_posix()
        for p in root.rglob("*")
        if p.is_file() and selected(p.relative_to(root).as_posix())
    )


def scan(root: pathlib.Path) -> dict:
    files = candidates(root)
    hits = []
    for name in files:
        path = root / name
        if path.suffix in TEXT or path.name in {"LICENSE", ".gitignore"}:
            text = path.read_text(encoding="utf-8", errors="replace")
            for kind, pattern in PATTERNS.items():
                if pattern.search(text):
                    hits.append({"file": name, "kind": kind})
    return {
        "files": len(files),
        "hits": hits,
        "sha256": {n: hashlib.sha256((root / n).read_bytes()).hexdigest() for n in files},
        "scope": "Selected source snapshot, not Git history; pattern scan plus separately recorded manual review, not universal secret discovery.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", default=".")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    root = pathlib.Path(args.root)
    if root.suffix == ".zip":
        with zipfile.ZipFile(root) as z:
            hits = []
            for n in z.namelist():
                if pathlib.PurePosixPath(n).is_absolute() or ".." in pathlib.PurePosixPath(n).parts:
                    hits.append({"file": n, "kind": "unsafe_archive_path"})
                if pathlib.Path(n).suffix in TEXT:
                    text = z.read(n).decode("utf-8", errors="replace")
                    hits.extend({"file": n, "kind": k} for k, p in PATTERNS.items() if p.search(text))
            result = {"files": len(z.infolist()), "hits": hits, "crc": z.testzip() or "PASS"}
    else:
        result = scan(root)
    pathlib.Path(args.output).write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "sha256"}, indent=2))
    raise SystemExit(bool(result["hits"]))


if __name__ == "__main__":
    main()
