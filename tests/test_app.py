from io import BytesIO

import pytest

from app import create_app


@pytest.fixture
def client(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "SIMULATION_MODE": True,
            "BACKUP_DIR": str(tmp_path / "backups"),
        }
    )
    with app.test_client() as test_client:
        yield test_client


def test_dashboard_and_health_endpoint_use_simulation(client):
    page = client.get("/")
    health = client.get("/health")
    status = client.get("/api/status")

    assert page.status_code == 200
    assert b"AWS EC2 BACKUP AND RECOVERY USING AMAZON S3" in page.data
    assert health.get_json() == {"status": "ok", "mode": "simulation"}
    assert status.get_json()["mode"] == "simulation"
    assert status.get_json()["backup_count"] == 0


def test_upload_list_restore_and_delete_local_backup(client):
    upload = client.post(
        "/api/backups",
        data={"file": (BytesIO(b"sample backup contents"), "notes.txt")},
        content_type="multipart/form-data",
    )

    assert upload.status_code == 201
    assert upload.get_json()["mode"] == "simulation"
    backup_key = upload.get_json()["key"]

    history = client.get("/api/backups").get_json()["backups"]
    assert len(history) == 1
    assert history[0]["filename"] == "notes.txt"
    assert history[0]["size"] == len(b"sample backup contents")

    restored = client.get(f"/api/backups/{backup_key}/restore")
    assert restored.status_code == 200
    assert restored.data == b"sample backup contents"
    assert "notes.txt" in restored.headers["Content-Disposition"]

    deleted = client.delete(f"/api/backups/{backup_key}")
    assert deleted.status_code == 200
    assert client.get("/api/backups").get_json()["backups"] == []


@pytest.mark.parametrize(
    "upload_data, expected_status",
    [
        ({}, 400),
        ({"file": (BytesIO(b""), "empty.txt")}, 400),
        ({"file": (BytesIO(b"x"), "../../bad.txt")}, 201),
    ],
)
def test_upload_validation_and_filename_sanitization(client, upload_data, expected_status):
    response = client.post(
        "/api/backups", data=upload_data, content_type="multipart/form-data"
    )

    assert response.status_code == expected_status
    if expected_status == 201:
        backup = client.get("/api/backups").get_json()["backups"][0]
        assert backup["filename"] == "bad.txt"


def test_restore_and_delete_reject_unsafe_keys(client):
    assert client.get("/api/backups/../../secrets/restore").status_code == 404
    assert client.delete("/api/backups/not-a-backup-key").status_code == 404


def test_missing_backup_returns_not_found(client):
    missing_key = "a" * 32 + "__missing.txt"
    assert client.get(f"/api/backups/{missing_key}/restore").status_code == 404
    assert client.delete(f"/api/backups/{missing_key}").status_code == 404