import json
import sys

from ghostframe.cli import main


def test_documented_cli_workflow(tmp_path, monkeypatch, capsys):
    db = str(tmp_path / "cli.db")

    def command(*args):
        monkeypatch.setattr(sys, "argv", ["ghostframe", "--db", db, *args])
        main()
        return json.loads(capsys.readouterr().out)

    assert command("doctor")["database_accessible"]
    demo = command("demo")
    rid, bid = demo["original_id"], demo["branch_id"]
    assert command("runs", "list")
    assert command("runs", "inspect", rid)["bundle"]["metadata"]["id"] == rid
    assert command("verify", rid)["valid"]
    assert command("replay", rid)["status"] == "REPLAY_SUCCESS"
    replacement = tmp_path / "replacement with spaces.json"
    replacement.write_text('{"action":"noop","target":"/documents/draft_report.txt"}')
    branch = command("fork", rid, "--event", demo["event_id"], "--replacement", str(replacement))
    assert branch["comparison"]["branch_outcome"]["final_files"]["/documents/final_report.txt"]
    assert command("compare", rid, bid)["branch_outcome"]["task_correct"]
    exported = tmp_path / "export with spaces.json"
    assert command("export", rid, "--output", str(exported))["digest"]
    assert exported.exists()


def test_benchmark_includes_every_fixture(tmp_path):
    from ghostframe.benchmark import benchmark

    result = benchmark(str(tmp_path / "reports"), repetitions=1)
    assert result["sets"]["development"]["attempts"] == 30
    assert result["sets"]["development"]["replay_success"] == 30
    assert result["sets"]["regression"]["attempts"] == 10
    assert result["branches"]["attempted"] == result["branches"]["valid"] == 5
    assert not result["failures"]


def test_runtime_logical_timeout_and_failed_replay(tmp_path):
    import pytest

    from ghostframe.fixtures import flagship
    from ghostframe.models import GFError
    from ghostframe.runtime import Engine
    from ghostframe.store import Store

    s = Store(tmp_path / "timeout.db")
    e = Engine(s)
    e.driver.action = lambda state: ("list_files", {})
    with pytest.raises(GFError) as exc:
        e.run(flagship())
    assert exc.value.code == "EXECUTION_TIMEOUT"
    rid = exc.value.details["failed_run_id"]
    assert s.events(rid)[-1]["kind"] == "RUN_FAILED"
    with pytest.raises(GFError):
        e.replay(rid)
