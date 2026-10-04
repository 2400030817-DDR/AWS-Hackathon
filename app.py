"""Back up files explicitly uploaded through the dashboard to S3 or locally."""

from __future__ import annotations

import io
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, render_template, request, send_file
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.utils import secure_filename

LOGGER = logging.getLogger(__name__)
MAX_UPLOAD_BYTES = 16 * 1024 * 1024
BACKUP_KEY_PATTERN = re.compile(r"[0-9a-f]{32}__[A-Za-z0-9_.-]{1,180}\Z")


class LocalStorage:
    """Filesystem-backed storage used when AWS is not configured."""

    mode = "simulation"

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)

    def list_backups(self) -> list[dict[str, Any]]:
        backups = []
        for path in self.directory.iterdir():
            if path.is_file() and BACKUP_KEY_PATTERN.fullmatch(path.name):
                stat = path.stat()
                backups.append(
                    {
                        "key": path.name,
                        "filename": path.name.split("__", 1)[1],
                        "size": stat.st_size,
                        "last_modified": datetime.fromtimestamp(
                            stat.st_mtime, timezone.utc
                        ).isoformat(),
                    }
                )
        return sorted(backups, key=lambda item: item["last_modified"], reverse=True)

    def save(self, stream: Any, key: str, content_type: str) -> None:
        del content_type
        destination = self.directory / key
        with destination.open("wb") as output:
            while chunk := stream.read(1024 * 1024):
                output.write(chunk)

    def read(self, key: str) -> tuple[Any, str]:
        content = io.BytesIO((self.directory / key).read_bytes())
        return content, key.split("__", 1)[1]

    def delete(self, key: str) -> None:
        (self.directory / key).unlink()


class S3Storage:
    """S3-backed storage using Boto3's standard credential chain."""

    mode = "s3"

    def __init__(self, client: Any, bucket: str) -> None:
        self.client = client
        self.bucket = bucket

    def list_backups(self) -> list[dict[str, Any]]:
        backups = []
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket):
            for item in page.get("Contents", []):
                key = item["Key"]
                if BACKUP_KEY_PATTERN.fullmatch(key):
                    backups.append(
                        {
                            "key": key,
                            "filename": key.split("__", 1)[1],
                            "size": item["Size"],
                            "last_modified": item["LastModified"].astimezone(
                                timezone.utc
                            ).isoformat(),
                        }
                    )
        return sorted(backups, key=lambda item: item["last_modified"], reverse=True)

    def save(self, stream: Any, key: str, content_type: str) -> None:
        self.client.upload_fileobj(
            stream,
            self.bucket,
            key,
            ExtraArgs={"ContentType": content_type or "application/octet-stream"},
        )

    def read(self, key: str) -> tuple[Any, str]:
        response = self.client.get_object(Bucket=self.bucket, Key=key)
        body = response["Body"]
        content = io.BytesIO(body.read())
        body.close()
        return content, key.split("__", 1)[1]

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)


def _make_storage(app: Flask) -> LocalStorage | S3Storage:
    local_storage = lambda: LocalStorage(Path(app.config["BACKUP_DIR"]))
    if app.config.get("SIMULATION_MODE") is True:
        return local_storage()

    bucket = app.config.get("S3_BUCKET_NAME")
    if not bucket:
        return local_storage()

    try:
        import boto3

        session = boto3.Session(region_name=app.config.get("AWS_REGION"))
        if session.get_credentials() is None:
            LOGGER.info("AWS credentials were not found; using simulation mode.")
            return local_storage()
        return S3Storage(session.client("s3"), bucket)
    except Exception:
        LOGGER.warning("AWS could not be initialized; using simulation mode.", exc_info=True)
        return local_storage()


def create_app(test_config: dict[str, Any] | None = None) -> Flask:
    app = Flask(__name__)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("FLASK_SECRET_KEY", "local-development-key"),
        AWS_REGION=os.environ.get("AWS_REGION"),
        S3_BUCKET_NAME=os.environ.get("S3_BUCKET_NAME"),
        BACKUP_DIR=os.environ.get(
            "BACKUP_DIR", str(Path(app.root_path) / "backups")
        ),
        MAX_CONTENT_LENGTH=MAX_UPLOAD_BYTES,
        SIMULATION_MODE=None,
    )
    if test_config:
        app.config.update(test_config)

    storage = _make_storage(app)
    app.extensions["backup_storage"] = storage

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/health")
    def health():
        return jsonify({"status": "ok", "mode": storage.mode})

    @app.get("/api/status")
    def status():
        try:
            backups = storage.list_backups()
            return jsonify(
                {
                    "mode": storage.mode,
                    "backup_count": len(backups),
                    "last_backup": backups[0]["last_modified"] if backups else None,
                    "region": app.config.get("AWS_REGION") if storage.mode == "s3" else None,
                }
            )
        except Exception:
            LOGGER.exception("Could not load backup status.")
            return jsonify({"error": "Backup status is temporarily unavailable."}), 500

    @app.get("/api/backups")
    def list_backups():
        try:
            return jsonify({"backups": storage.list_backups()})
        except Exception:
            LOGGER.exception("Could not list backups.")
            return jsonify({"error": "Backup history is temporarily unavailable."}), 500

    @app.post("/api/backups")
    def upload_backup():
        uploaded = request.files.get("file")
        if uploaded is None or not uploaded.filename:
            return jsonify({"error": "Choose a file to back up."}), 400

        filename = secure_filename(uploaded.filename)
        if not filename:
            return jsonify({"error": "That filename is not valid."}), 400
        if len(filename) > 180:
            return jsonify({"error": "Filenames must be 180 characters or fewer."}), 400

        content = uploaded.stream.read(MAX_UPLOAD_BYTES + 1)
        if not content:
            return jsonify({"error": "Empty files cannot be backed up."}), 400
        if len(content) > MAX_UPLOAD_BYTES:
            return jsonify({"error": "Files must be 16 MB or smaller."}), 413

        key = f"{uuid.uuid4().hex}__{filename}"
        try:
            storage.save(io.BytesIO(content), key, uploaded.mimetype)
            return jsonify(
                {
                    "message": f"{filename} was backed up successfully.",
                    "key": key,
                    "mode": storage.mode,
                }
            ), 201
        except Exception:
            LOGGER.exception("Could not save uploaded backup.")
            return jsonify({"error": "The file could not be backed up."}), 500

    @app.get("/api/backups/<key>/restore")
    def restore_backup(key: str):
        if not BACKUP_KEY_PATTERN.fullmatch(key):
            return jsonify({"error": "That backup could not be found."}), 404
        try:
            stream, filename = storage.read(key)
            return send_file(
                stream,
                as_attachment=True,
                download_name=filename,
                mimetype="application/octet-stream",
            )
        except FileNotFoundError:
            return jsonify({"error": "That backup could not be found."}), 404
        except Exception:
            LOGGER.exception("Could not restore backup %s.", key)
            return jsonify({"error": "The backup could not be restored."}), 500

    @app.delete("/api/backups/<key>")
    def delete_backup(key: str):
        if not BACKUP_KEY_PATTERN.fullmatch(key):
            return jsonify({"error": "That backup could not be found."}), 404
        try:
            storage.delete(key)
            return jsonify({"message": "Backup deleted successfully."})
        except FileNotFoundError:
            return jsonify({"error": "That backup could not be found."}), 404
        except Exception:
            LOGGER.exception("Could not delete backup %s.", key)
            return jsonify({"error": "The backup could not be deleted."}), 500

    @app.errorhandler(RequestEntityTooLarge)
    def handle_file_too_large(_error: RequestEntityTooLarge):
        return jsonify({"error": "Files must be 16 MB or smaller."}), 413

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5000")), debug=False)