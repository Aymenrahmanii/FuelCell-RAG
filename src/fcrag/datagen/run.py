"""Generate the synthetic corpus, with ``manifest.yaml`` and ``facts.jsonl`` next to it."""

from pathlib import Path

from fcrag.datagen import cad, datasheet, drawing, excel, injection, requirements
from fcrag.datagen.common import GeneratedFile, write_manifest
from fcrag.truth import load_all

GENERATORS = (
    datasheet.build_all,
    excel.build_all,
    requirements.build_all,
    cad.build_all,
    drawing.build_all,
    injection.build_all,
)


def generate(systems_dir: Path, out_dir: Path) -> list[GeneratedFile]:
    out_dir.mkdir(parents=True, exist_ok=True)
    files: list[GeneratedFile] = []
    for system in load_all(systems_dir).values():
        for build in GENERATORS:
            files.extend(build(system, out_dir))
    write_manifest(out_dir, files)
    return files
