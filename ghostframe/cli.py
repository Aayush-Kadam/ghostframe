from __future__ import annotations

import argparse
import importlib.util
import json
import platform
import shutil
from pathlib import Path

from .fixtures import flagship
from .models import GFError
from .policies import RetentionPolicy
from .runtime import Engine
from .store import Store


def doctor(store):
    with store.connect() as db:
        accessible = bool(db.execute("SELECT 1").fetchone())
    return {
        "python": platform.python_version(),
        "python_supported": tuple(map(int, platform.python_version_tuple()[:2])) >= (3, 11),
        "dependencies": {
            x: importlib.util.find_spec(x) is not None for x in ["fastapi", "pydantic", "uvicorn"]
        },
        "database": str(store.path.resolve()),
        "database_accessible": accessible,
        "docker_optional": shutil.which("docker") is not None,
        "fixture": flagship()["id"],
        "frontend_compiled": (Path(__file__).parent / "static/index.html").exists(),
        "node_optional": shutil.which("node") is not None,
    }


def local_port(value: str) -> int:
    try:
        port = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("Port must be an integer from 1 to 65535") from None
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("Port must be an integer from 1 to 65535")
    return port


def main():
    p = argparse.ArgumentParser(prog="ghostframe", description="Local scripted-agent execution debugger")
    p.add_argument("--db", default=".ghostframe/ghostframe.db")
    sub = p.add_subparsers(dest="command", required=True)
    retention = sub.add_parser("retention").add_subparsers(dest="retention_command", required=True)
    for name in ("status", "dry-run", "apply"):
        r = retention.add_parser(name)
        if name == "apply":
            r.add_argument("--yes", action="store_true", help="Confirm deletion of policy-expired owned rows")
    for name in ("doctor", "demo", "benchmark"):
        sub.add_parser(name)
    serve = sub.add_parser("serve")
    serve.add_argument("--port", type=local_port, default=8765, help="Loopback port, 1 through 65535")
    serve.add_argument(
        "--allow-dev-origin", action="store_true", help="Explicitly trust local Vite port 5173"
    )
    runs = sub.add_parser("runs").add_subparsers(dest="run_command", required=True)
    runs.add_parser("list")
    runs.add_parser("inspect").add_argument("run_id")
    for name in ("replay", "verify", "export"):
        cmd = sub.add_parser(name)
        cmd.add_argument("run_id")
        if name == "export":
            cmd.add_argument("--output", default="evidence.json")
    fork = sub.add_parser("fork")
    fork.add_argument("run_id")
    fork.add_argument("--event", required=True)
    fork.add_argument("--replacement", required=True)
    compare = sub.add_parser("compare")
    compare.add_argument("run_id")
    compare.add_argument("branch_id")
    args = p.parse_args()
    s = Store(args.db, retention=RetentionPolicy(cleanup_on_startup=args.command != "retention"))
    result: object = None
    e = Engine(s)
    try:
        if args.command == "retention":
            if args.retention_command == "apply" and not args.yes:
                raise GFError("CONFIRMATION_REQUIRED", "Use --yes after inspecting retention dry-run")
            result = s.cleanup(apply=args.retention_command == "apply")
        elif args.command == "doctor":
            result = doctor(s)
        elif args.command == "demo":
            rid = e.run(flagship())
            target = next(
                x for x in s.events(rid) if x["kind"] == "TOOL_CALL_COMPLETED" and x["tool"] == "read_ticket"
            )
            result = {
                "original_id": rid,
                "event_id": target["event_id"],
                "replay": e.replay(rid),
                **e.fork(
                    rid, target["event_id"], {"action": "delete", "target": "/documents/draft_report.txt"}
                ),
            }
        elif args.command == "runs":
            result = s.runs() if args.run_command == "list" else s.export(args.run_id)
        elif args.command == "replay":
            result = e.replay(args.run_id)
        elif args.command == "verify":
            result = s.verify(args.run_id)
        elif args.command == "fork":
            result = e.fork(
                args.run_id, args.event, json.loads(Path(args.replacement).read_text(encoding="utf-8"))
            )
        elif args.command == "compare":
            result = e.compare(args.run_id, args.branch_id)
        elif args.command == "export":
            result = s.export(args.run_id)
            Path(args.output).write_text(json.dumps(result, indent=2), encoding="utf-8")
            result = {"output": str(Path(args.output).resolve()), "digest": result["digest"]}
        elif args.command == "benchmark":
            from .benchmark import benchmark

            result = benchmark()
        else:
            import uvicorn

            from .api import create_app

            uvicorn.run(
                create_app(args.db, allow_dev_origin=args.allow_dev_origin),
                host="127.0.0.1",
                port=args.port,
                access_log=False,
            )
            return
        print(json.dumps(result, indent=2))
    except GFError as exc:
        print(json.dumps({"error": exc.json()}, indent=2))
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
