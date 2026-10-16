import copy
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from ghostframe.fixtures import flagship, load
from ghostframe.models import GFError, digest
from ghostframe.runtime import Engine, initial_state, semantic
from ghostframe.sandbox import Sandbox, normalize
from ghostframe.store import Store


@pytest.fixture
def pair(tmp_path):
    s = Store(tmp_path / "test.db")
    return s, Engine(s)


@pytest.mark.parametrize("fixture", load()["development"] + load()["regression"], ids=lambda f: f["id"])
def test_fixtures_independent_oracles(pair, fixture):
    s, e = pair
    rid = e.run(fixture)
    outcome = s.summary(rid)["outcome"]
    assert outcome["final_files"] == fixture["expected_files"]
    assert outcome["task_correct"] == fixture["expected_correct"]
    assert outcome["result"].get("error") == fixture["expected_error"]
    assert outcome["journal_reconciled"]
    original = s.export(rid)
    replay = e.replay(rid)
    assert semantic(s.events(rid)) == semantic(s.events(replay["run_id"]))
    assert s.export(rid) == original
    for cp in s.checkpoints(rid):
        assert s.restore(cp["id"], rid) == cp["body"]["state"]
    if fixture.get("intervention"):
        target = next(
            x for x in s.events(rid) if x["kind"] == "TOOL_CALL_COMPLETED" and x["tool"] == "read_ticket"
        )
        intervention = fixture["intervention"]
        b = e.fork(rid, target["event_id"], intervention["replacement"])
        assert b["comparison"]["branch_outcome"]["final_files"] == intervention["expected_files"]
        assert b["comparison"]["branch_outcome"]["task_correct"] == intervention["expected_correct"]
        assert s.export(rid) == original
        assert len([x for x in s.events(b["branch_id"]) if x["kind"] == "INTERVENTION_APPLIED"]) == 1
        assert all(x["provenance"] == "REEXECUTED_SCRIPTED" for x in s.events(b["branch_id"]))


def test_flagship_host_and_parent_isolation(pair, tmp_path):
    s, e = pair
    physical = tmp_path / "final_report.txt"
    physical.write_text("host sentinel")
    rid = e.run(flagship())
    source = s.export(rid)
    target = next(
        x for x in s.events(rid) if x["tool"] == "read_ticket" and x["kind"] == "TOOL_CALL_COMPLETED"
    )
    b = e.fork(rid, target["event_id"], {"action": "delete", "target": "/documents/draft_report.txt"})
    assert not s.summary(rid)["outcome"]["task_correct"]
    assert s.summary(b["branch_id"])["outcome"]["task_correct"]
    assert physical.read_text() == "host sentinel"
    assert s.export(rid) == source
    delete = next(
        x
        for x in s.events(b["branch_id"])
        if x["kind"] == "TOOL_CALL_REQUESTED" and x["tool"] == "delete_file"
    )
    assert delete["payload"]["path"] == "/documents/draft_report.txt"


@pytest.mark.parametrize("table", ["events", "checkpoints", "runs"])
def test_database_immutable(pair, table):
    s, e = pair
    e.run(flagship())
    with s.connect() as db:
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(f"DELETE FROM {table}")
        col = "body" if table != "runs" else "metadata"
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(f"UPDATE {table} SET {col} = {col}")


@pytest.mark.parametrize("fault", ["payload", "delete", "sequence", "parent", "schema", "checkpoint", "tail"])
def test_corruption_detected(pair, fault):
    s, e = pair
    rid = e.run(flagship())
    with s.connect() as db:
        db.execute("DROP TRIGGER events_no_update")
        db.execute("DROP TRIGGER events_no_delete")
        if fault == "delete":
            db.execute("DELETE FROM events WHERE run_id=? AND seq=3", (rid,))
        elif fault == "tail":
            db.execute(
                "DELETE FROM events WHERE run_id=? AND seq=(SELECT MAX(seq) FROM events WHERE run_id=?)",
                (rid, rid),
            )
        elif fault == "checkpoint":
            db.execute("DROP TRIGGER checkpoints_no_update")
            db.execute("UPDATE checkpoints SET body='{}' WHERE run_id=?", (rid,))
        else:
            body = s.events(rid)[3]
            body[
                {"payload": "payload", "sequence": "seq", "parent": "parent", "schema": "schema_version"}[
                    fault
                ]
            ] = {"x": "tampered"} if fault == "payload" else 999
            db.execute("UPDATE events SET body=? WHERE run_id=? AND seq=3", (json.dumps(body), rid))
    if fault == "tail":
        assert not s.verify(rid)["complete"]
        with pytest.raises(GFError) as exc:
            e.replay(rid)
        assert exc.value.code == "MISSING_CAPTURE"
    else:
        with pytest.raises(GFError):
            s.verify(rid)


def test_schema_and_unsupported_forks(pair):
    s, e = pair
    rid = e.run(flagship())
    target = next(
        x for x in s.events(rid) if x["tool"] == "read_ticket" and x["kind"] == "TOOL_CALL_COMPLETED"
    )
    for payload in [
        {},
        {"action": "shell", "target": "/documents/a"},
        {"action": "delete", "target": "/etc/passwd"},
    ]:
        with pytest.raises(GFError):
            e.fork(rid, target["event_id"], payload)
    with pytest.raises(GFError):
        e.fork(rid, s.events(rid)[0]["event_id"], {"action": "noop", "target": "/documents/a"})
    b = e.fork(rid, target["event_id"], {"action": "noop", "target": "/documents/a"})
    with pytest.raises(GFError, match="outside this version"):
        e.replay(b["branch_id"])


def test_driver_compatibility(pair):
    s, e = pair
    rid = e.run(flagship())
    with s.connect() as db:
        db.execute("DROP TRIGGER runs_no_update")
        m = s.metadata(rid)
        m["driver_version"] = "unknown"
        db.execute("UPDATE runs SET metadata=? WHERE id=?", (json.dumps(m), rid))
    with pytest.raises(GFError, match="compatible"):
        e.replay(rid)


def test_replay_divergence(pair):
    s, e = pair
    rid = e.run(flagship())

    def wrong_action(state):
        return "write_file", {"path": "/documents/draft_report.txt", "content": "bad", "approved": False}

    e.driver.action = wrong_action
    with pytest.raises(GFError) as exc:
        e.replay(rid)
    assert exc.value.code == "EVENT_MISMATCH"
    failed = exc.value.details["failed_run_id"]
    assert s.events(failed)[-1]["kind"] == "RUN_FAILED"
    assert s.events(failed)[-1]["provenance"] == "DIVERGED"


def test_double_finalization_and_missing_parent(pair):
    s, e = pair
    rid = e.run(flagship())
    with pytest.raises(GFError):
        s.append(rid, "RUN_COMPLETED")
    r = s.create({})
    with pytest.raises(GFError):
        s.append(r, "TOOL_CALL_COMPLETED", {}, tool="x")
    with pytest.raises(GFError):
        s.append(r, "TOOL_CALL_REQUESTED", {}, parent="nonexistent")


def test_concurrent_branches(pair):
    s, e = pair
    rid = e.run(flagship())
    before = s.export(rid)
    target = next(
        x for x in s.events(rid) if x["tool"] == "read_ticket" and x["kind"] == "TOOL_CALL_COMPLETED"
    )
    with ThreadPoolExecutor(4) as pool:
        branches = list(
            pool.map(
                lambda _: e.fork(
                    rid, target["event_id"], {"action": "delete", "target": "/documents/draft_report.txt"}
                ),
                range(4),
            )
        )
    assert len({b["branch_id"] for b in branches}) == 4
    assert all(s.verify(b["branch_id"])["complete"] for b in branches)
    assert s.export(rid) == before


@given(st.text(alphabet="abcdefghijklmnopqrstuvwxyz_", min_size=1, max_size=30))
def test_virtual_path_normalization(name):
    assert normalize("/documents/./" + name) == "/documents/" + name
    with pytest.raises(GFError):
        normalize("/documents/../" + name)


@given(st.dictionaries(st.text(alphabet="abc", min_size=1), st.integers(), max_size=10))
def test_canonical_roundtrip(value):
    assert digest(value) == digest(json.loads(json.dumps(value)))


# This property checks semantics across SQLite I/O, not a per-example latency SLO.
# Shared Windows runners can pause for longer than the old five-second deadline.
# Keep all examples/assertions; CI bounds the complete job separately.
@settings(max_examples=15, deadline=None)
@given(st.sampled_from(["delete", "write", "noop", "archive"]), st.text(alphabet="abc ", max_size=30))
def test_computational_replay_and_isolation_property(action, content):
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as directory:
        s = Store(Path(directory) / "property.db")
        e = Engine(s)
        f = copy.deepcopy(flagship())
        f["ticket"] = {"action": action, "target": "/documents/draft_report.txt", "content": content}
        r = e.run(f)
        original = s.export(r)
        assert e.replay(r)["status"] == "REPLAY_SUCCESS"
        assert s.export(r) == original


def test_unsupported_dispatch_and_snapshot_copy():
    state = initial_state(flagship())
    box = Sandbox(state)
    with pytest.raises(GFError):
        box.call("shell", {"cmd": "echo nope"})
    box.state["files"].clear()
    assert state["files"]


def test_state_divergence_is_not_marked_success(pair):
    s, e = pair
    rid = e.run(flagship())
    real_observe = e.driver.observe

    def changed_observe(state, tool, result):
        real_observe(state, tool, result)
        state["seed"] += 1

    e.driver.observe = changed_observe
    with pytest.raises(GFError) as exc:
        e.replay(rid)
    assert exc.value.code == "EVENT_MISMATCH"
    failed = exc.value.details["failed_run_id"]
    assert s.events(failed)[-1]["kind"] == "RUN_FAILED"
    assert s.events(failed)[-1]["provenance"] == "DIVERGED"


def test_identical_branch_reports_unchanged_actions(pair):
    s, e = pair
    rid = e.run(flagship())
    event = next(
        x for x in s.events(rid) if x["kind"] == "TOOL_CALL_COMPLETED" and x["tool"] == "read_ticket"
    )
    branch = e.fork(rid, event["event_id"], event["payload"])
    assert not branch["comparison"]["continuation_changed"]
    assert branch["comparison"]["first_observed_divergence"] is None


def test_export_verification_without_database(pair):
    from ghostframe.evidence import verify_bundle

    s, e = pair
    rid = e.run(flagship())
    target = next(
        x for x in s.events(rid) if x["tool"] == "read_ticket" and x["kind"] == "TOOL_CALL_COMPLETED"
    )
    branch = e.fork(rid, target["event_id"], {"action": "delete", "target": "/documents/draft_report.txt"})
    export = s.export(branch["branch_id"])
    assert verify_bundle(export)["valid"]
    export["bundle"]["events"][1]["payload"] = {"tampered": True}
    export["digest"] = digest(export["bundle"], "ghostframe.bundle.v1")
    with pytest.raises(GFError):
        verify_bundle(export)
