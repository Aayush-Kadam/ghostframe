"""Versioned capture policy and finite resource budgets, checked before persistence."""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass
from typing import Any

from .models import GFError, canonical


@dataclass(frozen=True)
class Limits:
    payload_bytes: int = 65536
    depth: int = 24
    string_bytes: int = 32768
    nodes: int = 20000
    events: int = 10000
    run_bytes: int = 16 * 1024 * 1024
    store_bytes: int = 256 * 1024 * 1024
    runs: int = 1000
    checkpoint_bytes: int = 1024 * 1024
    checkpoints: int = 256
    steps: int = 64
    seconds: float = 60
    active_operations: int = 4
    branches: int = 100
    branch_depth: int = 1
    export_bytes: int = 32 * 1024 * 1024
    response_bytes: int = 32 * 1024 * 1024
    request_bytes: int = 32768
    files: int = 100
    file_bytes: int = 32768
    filesystem_bytes: int = 1024 * 1024

    def __post_init__(self):
        if isinstance(self.seconds, bool):
            raise TypeError("Execution duration must be numeric, not boolean")
        if any(
            not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0 for v in asdict(self).values()
        ):
            raise ValueError("Limits must be finite positive numbers")
        if any(
            not isinstance(v, int) or isinstance(v, bool) for k, v in asdict(self).items() if k != "seconds"
        ):
            raise ValueError("Count and byte limits must be positive integers")

    def check(self, value: Any, size: int | None = None, code: str = "PAYLOAD_TOO_LARGE") -> int:
        stack = [(value, 0, False)]
        seen: set[int] = set()
        count = 0
        while stack:
            v, depth, leaving = stack.pop()
            if leaving:
                seen.remove(id(v))
                continue
            count += 1
            if depth > self.depth or count > self.nodes:
                raise GFError(code, "Structure exceeds configured budget")
            if isinstance(v, (dict, list, tuple)):
                if id(v) in seen:
                    raise GFError("UNSUPPORTED_SERIALIZATION", "Cyclic containers are unsupported")
                seen.add(id(v))
                stack.append((v, depth, True))
                if len(v) + count > self.nodes:
                    raise GFError(code, "Structure exceeds configured budget")
                if isinstance(v, dict):
                    for k, x in v.items():
                        if not isinstance(k, str):
                            raise GFError("UNSUPPORTED_SERIALIZATION", "JSON keys must be strings")
                        stack.extend(((k, depth + 1, False), (x, depth + 1, False)))
                else:
                    stack.extend((x, depth + 1, False) for x in v)
            elif isinstance(v, str):
                if len(v) > self.string_bytes or len(v.encode("utf-8")) > self.string_bytes:
                    raise GFError(code, "String exceeds configured budget")
            elif v is None or isinstance(v, (bool, int, float)):
                if isinstance(v, float) and not math.isfinite(v):
                    raise GFError("UNSUPPORTED_SERIALIZATION", "Finite JSON required")
                if isinstance(v, int) and v.bit_length() > 256:
                    raise GFError(code, "Integer exceeds configured budget")
            else:
                raise GFError("UNSUPPORTED_SERIALIZATION", "Finite JSON required")
        n = len(canonical(value).encode("utf-8"))
        if n > (self.payload_bytes if size is None else size):
            raise GFError(code, "Serialized value exceeds configured budget")
        return n


@dataclass(frozen=True)
class CapturePolicy:
    mode: str = "metadata_only"
    allowed_tools: tuple[str, ...] = ()
    allowed_fields: tuple[str, ...] = ()
    max_bytes: int = 65536
    redact_keys: tuple[str, ...] = (
        "password",
        "token",
        "secret",
        "api_key",
        "authorization",
        "cookie",
        "credential",
    )
    redact_values: tuple[str, ...] = ()
    enabled: bool = False  # Preview compatibility: explicit legacy opt-in, never the default.
    schema_version: int = 1

    def __post_init__(self):
        if type(self.enabled) is not bool or type(self.schema_version) is not int:
            raise ValueError("Capture opt-in must be an explicit boolean and version an integer")
        if self.mode not in {"metadata_only", "allowlist", "synthetic_fixture"}:
            raise ValueError("Unknown capture mode")
        if self.max_bytes <= 0:
            raise ValueError("Capture limit must be positive")
        if self.schema_version != 1 or not isinstance(self.max_bytes, int):
            raise ValueError("Capture version or byte limit is invalid")
        if any(
            not isinstance(v, tuple) or any(not isinstance(x, str) or not x for x in v)
            for v in (self.allowed_fields, self.allowed_tools, self.redact_keys, self.redact_values)
        ):
            raise ValueError("Capture selectors must be tuples of non-empty strings")

    def descriptor(self) -> dict:
        # Never persist secret-value redaction configuration.
        return {"version": 1, "mode": self.effective_mode, "synthetic": self.mode == "synthetic_fixture"}

    @property
    def effective_mode(self) -> str:
        return "legacy_explicit" if self.enabled and self.mode == "metadata_only" else self.mode

    def capture(
        self, value: Any, tool: str | None = None, *, limits: Limits | None = None
    ) -> tuple[Any, bool]:
        if self.effective_mode == "metadata_only":
            return {"capture": "DISABLED", "reason": "METADATA_ONLY"}, False
        limits = limits or Limits()
        try:
            limits.check(value, self.max_bytes)
        except GFError as exc:
            if exc.code == "PAYLOAD_TOO_LARGE":
                return {"capture": "OVERSIZED"}, False
            raise
        complete = True
        if self.mode == "allowlist":
            if tool not in self.allowed_tools or not isinstance(value, dict):
                return {"capture": "EXCLUDED"}, False

            def select(v, prefix=""):
                nonlocal complete
                if not isinstance(v, dict):
                    complete = False
                    return None
                out = {}
                for k, x in v.items():
                    path = prefix + k
                    if path in self.allowed_fields and not isinstance(x, (dict, list, tuple)):
                        out[k] = x
                    elif isinstance(x, dict) and any(p.startswith(path + ".") for p in self.allowed_fields):
                        out[k] = select(x, path + ".")
                    else:
                        complete = False
                return out

            value = select(value)

        def redact(v):
            nonlocal complete
            if isinstance(v, dict):
                out = {}
                for k, x in v.items():
                    if any(s in k.lower() for s in self.redact_keys):
                        out[k] = "[REDACTED]"
                        complete = False
                    else:
                        out[k] = redact(x)
                return out
            if isinstance(v, (tuple, list)):
                return [redact(x) for x in v]
            if isinstance(v, str):
                original = v
                for secret in self.redact_values:
                    if secret:
                        v = v.replace(secret, "[REDACTED]")
                v = re.sub(
                    r"(?i)(bearer\s+|(?:password|token|api_key|secret)=)[^\s&\"']+", r"\1[REDACTED]", v
                )
                # Start at the literal delimiter, rather than retrying a greedy
                # scheme scan at every character of a long non-URL string.
                # Redact credentials even when the scheme is malformed.
                v = re.sub(r"(://[^\s/@:]+:)[^\s/@]+@", r"\1[REDACTED]@", v)
                if v != original or "[REDACTED]" in v:
                    complete = False
                return v
            return v

        return redact(value), complete


@dataclass(frozen=True)
class RetentionPolicy:
    enabled: bool = True
    retention_days: float = 30
    cleanup_on_startup: bool = True

    def __post_init__(self):
        if (
            type(self.enabled) is not bool
            or type(self.cleanup_on_startup) is not bool
            or isinstance(self.retention_days, bool)
        ):
            raise ValueError("Retention flags must be explicit booleans and duration numeric")
        if not math.isfinite(self.retention_days) or self.retention_days <= 0:
            raise ValueError("Retention days must be finite and positive")
