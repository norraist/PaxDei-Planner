import bootstrap  # noqa: F401

import json
from pathlib import Path

from paxdei_planner.bundle import BundleManifest
from paxdei_ui.update_service import BundleUpdateWorker


class _FakeResponse:
    def __init__(self, payload=None, chunks=None) -> None:
        self._payload = payload
        self._chunks = chunks or []

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self._payload

    def iter_content(self, chunk_size: int = 1024):
        yield from self._chunks

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def _write_manifest(path: Path, version: str) -> None:
    payload = {
        "version": version,
        "generated_at": "",
        "files": {},
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def test_update_worker_no_update(monkeypatch, tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    _write_manifest(manifest_path, "1")

    def fake_get(url, timeout=30, stream=False):
        return _FakeResponse(
            payload={"version": "1", "generated_at": "", "files": {}},
        )

    monkeypatch.setattr("paxdei_ui.update_service.requests.get", fake_get)

    worker = BundleUpdateWorker(
        bundle_root=tmp_path / "bundle",
        manifest_path=manifest_path,
        manifest_url="https://example.com/manifest.json",
        archive_url="https://example.com/bundle.zip",
    )

    download_called = {"called": False}

    def _download_and_extract() -> None:
        download_called["called"] = True

    monkeypatch.setattr(worker, "_download_and_extract", _download_and_extract)

    finished = []
    worker.finished.connect(lambda success, message: finished.append((success, message)))

    worker.run()

    assert finished == [(False, "Data bundle already up to date.")]
    assert download_called["called"] is False


def test_update_worker_downloads_on_new_version(monkeypatch, tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    _write_manifest(manifest_path, "1")

    worker = BundleUpdateWorker(
        bundle_root=tmp_path / "bundle",
        manifest_path=manifest_path,
        manifest_url="https://example.com/manifest.json",
        archive_url="https://example.com/bundle.zip",
    )

    monkeypatch.setattr(
        worker,
        "_fetch_manifest",
        lambda: BundleManifest.from_payload({"version": "2", "generated_at": "", "files": {}}),
    )

    download_called = {"called": False}

    def _download_and_extract() -> None:
        download_called["called"] = True

    monkeypatch.setattr(worker, "_download_and_extract", _download_and_extract)

    finished = []
    worker.finished.connect(lambda success, message: finished.append((success, message)))

    worker.run()

    assert finished == [(True, "Updated data bundle to 2.")]
    assert download_called["called"] is True
