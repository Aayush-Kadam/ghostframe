"""Offline bundle verification independent of the producing SQLite database."""

from .models import Event, GFError, digest
from .store import ANCHOR


def verify_bundle(export: dict) -> dict:
    try:
        bundle = export["bundle"]
        if bundle["schema_version"] != 1 or digest(bundle, "ghostframe.bundle.v1") != export["digest"]:
            raise GFError("BUNDLE_CORRUPT", "Bundle digest or schema mismatch")
        rid = bundle["metadata"]["id"]
        checkpoints = {cp["id"]: cp for cp in bundle["checkpoints"]}
        for cp in checkpoints.values():
            if (
                cp["body"]["run_id"] != rid
                or cp["body"]["schema_version"] != 1
                or digest(cp["body"]) != cp["digest"]
            ):
                raise GFError("CHECKPOINT_CORRUPT", "Exported checkpoint mismatch")
        previous = ANCHOR
        seen = {}
        for seq, raw in enumerate(bundle["events"]):
            event = Event.model_validate(raw).model_dump()
            body = {k: v for k, v in event.items() if k != "event_digest"}
            if (
                event["seq"] != seq
                or event["run_id"] != rid
                or event["previous_digest"] != previous
                or digest(body, "ghostframe.event.v1") != event["event_digest"]
                or digest(event["payload"], "ghostframe.payload.v1") != event["payload_hash"]
            ):
                raise GFError("INTEGRITY_VIOLATION", "Exported ledger mismatch", {"seq": seq})
            if event["parent"] and event["parent"] not in seen:
                raise GFError("INTEGRITY_VIOLATION", "Exported parent is missing")
            if event["checkpoint"] and event["checkpoint"] not in checkpoints:
                raise GFError("CHECKPOINT_MISSING", "Exported checkpoint is missing")
            previous = event["event_digest"]
            seen[event["event_id"]] = event
        if not seen or bundle["events"][0]["kind"] != "RUN_STARTED":
            raise GFError("MISSING_CAPTURE", "Bundle has no run start")
        if bundle["metadata"].get("parent_id"):
            parent = bundle["parent_evidence"]
            verify_bundle(parent)
            if parent["bundle"]["metadata"]["id"] != bundle["metadata"]["parent_id"]:
                raise GFError("INTEGRITY_VIOLATION", "Branch parent mismatch")
        return {
            "valid": True,
            "run_id": rid,
            "events": len(seen),
            "head": previous,
            "complete": bundle["events"][-1]["kind"] in {"RUN_COMPLETED", "RUN_FAILED"},
            "limitation": "Checks integrity, not independent signatures or computational replay",
        }
    except GFError:
        raise
    except (ValueError, KeyError, TypeError):
        raise GFError("BUNDLE_CORRUPT", "Evidence does not match the supported bundle schema") from None
