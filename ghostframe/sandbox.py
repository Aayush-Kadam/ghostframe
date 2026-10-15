"""Only virtual state is accessible. No function resolves a path on the host."""

from __future__ import annotations

import copy
import posixpath

from .models import GFError, Ticket
from .policies import Limits


def normalize(path: str) -> str:
    if not isinstance(path, str) or not path.startswith("/") or "\\" in path or "\x00" in path or ":" in path:
        raise GFError("POLICY_DENIED", "Expected an absolute virtual POSIX path")
    if ".." in path.split("/"):
        raise GFError("POLICY_DENIED", "Traversal is forbidden")
    clean = posixpath.normpath(path)
    if not clean.startswith("/documents/"):
        raise GFError("POLICY_DENIED", "Path is outside /documents virtual root")
    return clean


def state_diff(before: dict, after: dict) -> list[dict]:
    out = []
    for key in sorted(set(before) | set(after)):
        if before.get(key) != after.get(key) or (key in before) != (key in after):
            out.append(
                {
                    "path": key,
                    "operation": "create"
                    if key not in before
                    else "delete"
                    if key not in after
                    else "modify",
                    "before": before.get(key),
                    "after": after.get(key),
                }
            )
    return out


class Sandbox:
    def __init__(self, state: dict, *, limits: Limits | None = None):
        self.limits = limits or Limits()
        self.check_files(state["files"])
        self.state = copy.deepcopy(state)
        self.journal: list[dict] = []

    def check_files(self, files: dict):
        if len(files) > self.limits.files:
            raise GFError("FILESYSTEM_QUOTA_EXCEEDED", "Virtual file count exceeded")
        total = 0
        for path, content in files.items():
            normalize(path)
            if not isinstance(content, str) or len(content.encode("utf-8")) > self.limits.file_bytes:
                raise GFError("FILESYSTEM_QUOTA_EXCEEDED", "Virtual file size exceeded")
            total += len(content.encode("utf-8"))
        if total > self.limits.filesystem_bytes:
            raise GFError("FILESYSTEM_QUOTA_EXCEEDED", "Virtual filesystem byte budget exceeded")

    def call(self, tool: str, args: dict) -> dict:
        if tool == "read_ticket":
            attempt = self.state["mock"]["attempt"]
            self.state["mock"]["attempt"] += 1
            failures = self.state["mock"].get("failures", [])
            if attempt < len(failures):
                return {"error": failures[attempt]}
            return copy.deepcopy(self.state["mock"]["ticket"])
        if tool == "request_approval":
            return {"approved": bool(self.state["mock"].get("approval", False))}
        if tool == "list_files":
            return {"files": sorted(self.state["files"])}
        if tool not in {"delete_file", "write_file", "archive_file"}:
            raise GFError("UNSUPPORTED_TOOL", "Tool is not in the virtual allowlist")
        path = normalize(args["path"])
        permissions = self.state.get("permissions", {})
        if permissions.get(path) == "deny" or permissions.get("*") == "deny":
            return {"error": "POLICY_DENIED"}
        if permissions.get(path) == "approval" and not args.get("approved"):
            return {"error": "APPROVAL_REQUIRED"}
        before = copy.deepcopy(self.state["files"])
        if tool in {"delete_file", "archive_file"} and path not in before:
            return {"error": "NOT_FOUND"}
        proposed = copy.deepcopy(before)
        if tool == "delete_file":
            del proposed[path]
        elif tool == "write_file":
            proposed[path] = args["content"]
        else:
            destination = path + ".archived"
            proposed[destination] = proposed.pop(path)
        self.check_files(proposed)
        self.state["files"] = proposed
        changes = state_diff(before, self.state["files"])
        self.journal.extend(changes)
        return {"ok": True, "changes": changes}

    def validate_ticket(self, value: dict) -> dict:
        try:
            ticket = Ticket.model_validate(value).model_dump()
        except ValueError as exc:
            raise GFError("INVALID_TOOL_RESULT", "Ticket does not match schema") from exc
        normalize(ticket["target"])
        return ticket
