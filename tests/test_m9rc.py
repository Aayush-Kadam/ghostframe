"""Release-focused regressions: exercise real routes, not only origin string helpers."""

import re
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from ghostframe.api import create_app


@pytest.mark.parametrize("port", [8765, 8879])
def test_bound_port_assets_branch_and_reload(tmp_path, port):
    origin = f"http://127.0.0.1:{port}"
    client = TestClient(create_app(str(tmp_path / "port.db")), base_url=origin)
    headers = {"origin": origin}
    page = client.get("/", headers=headers)
    assert page.status_code == 200
    asset = re.search(r'src="([^"]+\.js)"', page.text)[1]
    assert client.get(asset, headers=headers).status_code == 200
    assert client.get("/api/health", headers=headers).status_code == 200
    rid = client.post("/api/demo/run", headers=headers).json()["id"]
    parent = client.get(f"/api/runs/{rid}/export").json()["digest"]
    events = client.get(f"/api/runs/{rid}/events").json()["events"]
    event = next(e for e in events if e["kind"] == "TOOL_CALL_COMPLETED" and e["tool"] == "read_ticket")
    branch = client.post(
        f"/api/runs/{rid}/fork",
        headers=headers,
        json={
            "event_id": event["event_id"],
            "replacement": {"action": "delete", "target": "/documents/draft_report.txt"},
        },
    )
    assert branch.status_code == 200
    bid = branch.json()["branch_id"]
    assert branch.json()["comparison"]["branch_outcome"]["task_correct"] is True
    assert client.get(f"/api/branches/{bid}/comparison", headers=headers).status_code == 200
    assert client.get("/", headers=headers).status_code == 200
    assert client.get(f"/api/runs/{rid}/export").json()["digest"] == parent


@pytest.mark.parametrize(
    "origin",
    [
        "https://evil.example",
        "http://127.0.0.1:8765",
        "http://localhost:8879",
        "http://127.0.0.1:5173",
        "null",
        "http://127.0.0.1:8879/",
        "http://localhost.evil:8879",
        "http://user@127.0.0.1:8879",
    ],
)
def test_unauthorized_origin_never_writes(tmp_path, origin):
    client = TestClient(create_app(str(tmp_path / "denied.db")), base_url="http://127.0.0.1:8879")
    result = client.post("/api/demo/run", headers={"origin": origin})
    assert result.status_code == 403
    assert client.get("/api/runs").json() == []


@pytest.mark.parametrize(
    "host",
    [
        "localhost.evil:8879",
        "127.0.0.1.evil:8879",
        "user@localhost:8879",
        "localhost:8765",
        "localhost:65536",
        "testserver",
    ],
)
def test_invalid_network_host_never_writes(tmp_path, host):
    client = TestClient(create_app(str(tmp_path / "hosts.db")), base_url="http://127.0.0.1:8879")
    assert client.post("/api/demo/run", headers={"host": host}).status_code == 400
    assert client.get("/api/runs").json() == []


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "[::1]"])
def test_exact_loopback_names(tmp_path, host):
    origin = f"http://{host}:8879"
    client = TestClient(create_app(str(tmp_path / "names.db")), base_url=origin)
    assert client.get("/api/health", headers={"origin": origin}).status_code == 200


@pytest.mark.parametrize("port", ["0", "65536", "invalid", "1.5"])
def test_invalid_cli_port_rejected_before_storage(tmp_path, port):
    path = tmp_path / "never.db"
    result = subprocess.run(
        [sys.executable, "-m", "ghostframe.cli", "--db", str(path), "serve", "--port", port],
        text=True,
        check=False,
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 2
    assert "1 to 65535" in result.stderr
    assert not path.exists()


def test_development_origin_requires_opt_in(tmp_path):
    for enabled in [False, True]:
        client = TestClient(
            create_app(str(tmp_path / f"dev-{enabled}.db"), allow_dev_origin=enabled),
            base_url="http://127.0.0.1:8765",
        )
        response = client.post("/api/demo/run", headers={"origin": "http://127.0.0.1:5173"})
        assert response.status_code == (200 if enabled else 403)
        assert client.post("/api/demo/run", headers={"origin": "http://evil.example"}).status_code == 403
        assert "access-control-allow-origin" not in response.headers


def test_dev_configuration_is_explicit_boolean(tmp_path):
    with pytest.raises(ValueError):
        create_app(str(tmp_path / "invalid.db"), allow_dev_origin="true")
    assert not (tmp_path / "invalid.db").exists()
