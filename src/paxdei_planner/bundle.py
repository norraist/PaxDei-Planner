from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Mapping, Optional


DEFAULT_BUNDLE_DIR = "data_bundle"


@dataclass(frozen=True, slots=True)
class BundleFile:
    """Metadata for a file contained inside the bundle."""

    path: str
    size: int
    sha256: str

    @classmethod
    def from_mapping(cls, path: str, payload: Mapping[str, object]) -> "BundleFile":
        size = int(payload.get("size", 0) if isinstance(payload, Mapping) else 0)
        sha = str(payload.get("sha256", "")) if isinstance(payload, Mapping) else ""
        return cls(path=path, size=size, sha256=sha)


@dataclass(frozen=True, slots=True)
class BundleManifest:
    """Describes the logical contents of a data bundle."""

    version: str
    generated_at: str
    files: Dict[str, BundleFile]

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> "BundleManifest":
        version = str(payload.get("version", "0"))
        generated_at = str(payload.get("generated_at", ""))
        files: Dict[str, BundleFile] = {}
        for rel, meta in payload.get("files", {}).items():
            if not isinstance(meta, Mapping):
                continue
            files[rel] = BundleFile.from_mapping(rel, meta)
        return cls(version=version, generated_at=generated_at, files=files)

    @classmethod
    def load(cls, path: Path) -> "BundleManifest":
        if not path.exists():
            raise FileNotFoundError(f"Bundle manifest missing: {path}")
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, Mapping):
            raise ValueError(f"Invalid manifest JSON at {path}")
        return cls.from_payload(payload)


class DataBundle:
    """Helper to resolve and validate bundle paths."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        manifest_path = self.root / "manifest.json"
        self.manifest = BundleManifest.load(manifest_path)

    def resolve(self, relative: str) -> Path:
        """Return the absolute path for a file tracked in the bundle."""
        if relative.startswith("/") or relative.startswith("\\"):
            raise ValueError("Bundle paths must be relative")
        return self.root / relative

    def iter_files(self) -> Iterable[Path]:
        for rel in self.manifest.files:
            yield self.resolve(rel)

    def verify(self) -> Dict[str, str]:
        """Return a mapping of relative path -> checksum mismatch (empty when clean)."""
        problems: Dict[str, str] = {}
        for rel, meta in self.manifest.files.items():
            abs_path = self.resolve(rel)
            if not abs_path.exists():
                problems[rel] = "missing"
                continue
            if meta.sha256:
                digest = compute_sha256(abs_path)
                if digest.lower() != meta.sha256.lower():
                    problems[rel] = f"checksum mismatch (expected {meta.sha256}, got {digest})"
        return problems


def compute_sha256(path: Path) -> str:
    """Return the hex SHA-256 digest for a file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def discover_bundle_root(start: Optional[Path] = None) -> Path:
    """Return the best-effort bundle root based on cwd/module path."""
    candidates: list[Path] = []
    if start:
        candidates.append(start)
        candidates.append(start / DEFAULT_BUNDLE_DIR)
    cwd = Path.cwd()
    candidates.append(cwd / DEFAULT_BUNDLE_DIR)
    candidates.append(cwd)
    module_root = Path(__file__).resolve().parents[2]
    candidates.append(module_root / DEFAULT_BUNDLE_DIR)
    for candidate in candidates:
        manifest = candidate / "manifest.json"
        if manifest.exists():
            return candidate
    # fall back to cwd even if manifest missing; callers will raise later
    fallback = cwd / DEFAULT_BUNDLE_DIR
    return fallback
