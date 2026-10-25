"""Find source files and attach their metadata from the corpus manifests."""

import hashlib
import mimetypes
from pathlib import Path
from typing import Any

import yaml

from fcrag.models import SourceFile

GENERATED_MANIFEST = "manifest.yaml"
"""Written by the data generators next to the files they produce."""
GENERATOR_METADATA = {GENERATED_MANIFEST, "facts.jsonl"}
"""Generator bookkeeping, not documents."""

mimetypes.add_type("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".xlsx")
mimetypes.add_type("model/step", ".step")
mimetypes.add_type("model/step", ".stp")
mimetypes.add_type("application/xml", ".reqif")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def load_metadata(sources_manifest: Path, source_dirs: list[Path]) -> dict[str, dict[str, Any]]:
    """Metadata keyed by file name: public sources by ``<id>.pdf``, generated files as listed."""
    meta: dict[str, dict[str, Any]] = {}
    if sources_manifest.exists():
        data = yaml.safe_load(sources_manifest.read_text(encoding="utf-8")) or {}
        for src in data.get("sources") or []:
            meta[f"{src['id']}.pdf"] = {
                "doc_id": src["id"],
                "title": src.get("title"),
                "doc_type": src.get("doc_type"),
                "licence": src.get("licence"),
            }
    for directory in source_dirs:
        manifest = directory / GENERATED_MANIFEST
        if manifest.exists():
            data = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
            for entry in data.get("files") or []:
                meta[entry["file"]] = {k: v for k, v in entry.items() if k != "file"}
    return meta


def discover(source_dirs: list[Path], sources_manifest: Path) -> list[SourceFile]:
    meta = load_metadata(sources_manifest, source_dirs)
    files: list[SourceFile] = []
    for directory in source_dirs:
        if not directory.exists():
            continue
        for path in sorted(p for p in directory.rglob("*") if p.is_file()):
            if (
                path.name in GENERATOR_METADATA
                or path.name.startswith(".")
                or path.suffix == ".part"
            ):
                continue
            info = meta.get(path.name, {})
            mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            files.append(
                SourceFile(
                    path=path,
                    sha256=sha256_file(path),
                    mime_type=mime,
                    doc_id=info.get("doc_id", path.stem),
                    doc_version=info.get("doc_version", 1),
                    doc_type=info.get("doc_type"),
                    system=info.get("system"),
                    licence=info.get("licence"),
                    title=info.get("title"),
                    language=info.get("language"),
                    allowed_groups=info.get("allowed_groups", []),
                )
            )
    return files
