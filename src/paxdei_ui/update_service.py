from __future__ import annotations

import tempfile
import zipfile
from pathlib import Path
from typing import Optional

import requests
from PySide6 import QtCore

from paxdei_planner.bundle import BundleManifest


class BundleUpdateWorker(QtCore.QObject):
    finished = QtCore.Signal(bool, str)
    progress = QtCore.Signal(str)

    def __init__(
        self,
        bundle_root: Path,
        manifest_path: Path,
        manifest_url: str,
        archive_url: str,
    ) -> None:
        super().__init__()
        self.bundle_root = bundle_root
        self.manifest_path = manifest_path
        self.manifest_url = manifest_url
        self.archive_url = archive_url

    @QtCore.Slot()
    def run(self) -> None:
        try:
            local_manifest = None
            try:
                local_manifest = BundleManifest.load(self.manifest_path)
            except FileNotFoundError:
                pass
            self.progress.emit("Checking remote manifest...")
            remote_manifest = self._fetch_manifest()
            if local_manifest and remote_manifest.version == local_manifest.version:
                self.finished.emit(False, "Data bundle already up to date.")
                return
            self.progress.emit(f"Downloading bundle {remote_manifest.version}...")
            self._download_and_extract()
            self.finished.emit(True, f"Updated data bundle to {remote_manifest.version}.")
        except Exception as exc:  # pragma: no cover - network errors handled at runtime
            self.finished.emit(False, str(exc))

    def _fetch_manifest(self) -> BundleManifest:
        resp = requests.get(self.manifest_url, timeout=30)
        resp.raise_for_status()
        payload = resp.json()
        return BundleManifest.from_payload(payload)

    def _download_and_extract(self) -> None:
        self.bundle_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir) / "bundle.zip"
            with requests.get(self.archive_url, stream=True, timeout=60) as resp:
                resp.raise_for_status()
                with tmp_path.open("wb") as handle:
                    for chunk in resp.iter_content(chunk_size=1024 * 512):
                        if chunk:
                            handle.write(chunk)
            with zipfile.ZipFile(tmp_path, "r") as archive:
                archive.extractall(self.bundle_root)


class DataUpdateService(QtCore.QObject):
    status_changed = QtCore.Signal(str)
    update_finished = QtCore.Signal(bool, str)

    def __init__(
        self,
        bundle_root: Path,
        manifest_path: Path,
        manifest_url: Optional[str],
        archive_url: Optional[str],
    ) -> None:
        super().__init__()
        self.bundle_root = bundle_root
        self.manifest_path = manifest_path
        self.manifest_url = manifest_url
        self.archive_url = archive_url
        self._thread: QtCore.QThread | None = None
        self._worker: BundleUpdateWorker | None = None

    def is_configured(self) -> bool:
        return bool(self.manifest_url and self.archive_url)

    @QtCore.Slot()
    def check_for_updates(self) -> None:
        if not self.is_configured():
            self.update_finished.emit(False, "Update URLs are not configured.")
            return
        if self._thread and self._thread.isRunning():
            return
        worker = BundleUpdateWorker(
            self.bundle_root,
            self.manifest_path,
            self.manifest_url or "",
            self.archive_url or "",
        )
        thread = QtCore.QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._handle_finished)
        worker.progress.connect(self.status_changed.emit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        self._thread = thread
        self._worker = worker
        self.status_changed.emit("Checking for updates...")
        thread.start()

    def _handle_finished(self, success: bool, message: str) -> None:
        if self._thread:
            self._thread.quit()
            self._thread.wait()
        self._thread = None
        self._worker = None
        self.update_finished.emit(success, message)
