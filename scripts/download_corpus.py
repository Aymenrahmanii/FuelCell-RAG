"""Download the public documents listed in data/sources.yaml into data/raw/.

Already-downloaded files are skipped. The SHA-256 of each file is recorded in
data/sources.lock.yaml on first download and verified on every later run, so a silently changed
upstream file is caught.
"""

import argparse
import hashlib
import sys
import urllib.request
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
REQUIRED = ("id", "url", "title", "publisher", "licence", "doc_type")


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def download(url: str, target: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "fcrag-corpus/0.1"})
    tmp = target.with_suffix(target.suffix + ".part")
    with urllib.request.urlopen(request, timeout=60) as response, tmp.open("wb") as out:
        while block := response.read(1 << 20):
            out.write(block)
    tmp.replace(target)


def sync(manifest: Path, out_dir: Path) -> int:
    data: dict[str, Any] = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
    sources: list[dict[str, Any]] = data.get("sources") or []
    lock_path = manifest.with_suffix(".lock.yaml")
    lock: dict[str, str] = {}
    if lock_path.exists():
        lock = yaml.safe_load(lock_path.read_text(encoding="utf-8")) or {}
    out_dir.mkdir(parents=True, exist_ok=True)
    failures = 0
    changed = False

    for src in sources:
        missing = [field for field in REQUIRED if not src.get(field)]
        if missing:
            print(f"SKIP {src.get('id', '?')}: missing {', '.join(missing)}")
            failures += 1
            continue

        target = out_dir / f"{src['id']}.pdf"
        if not target.exists():
            try:
                download(src["url"], target)
            except OSError as exc:
                print(f"FAIL {src['id']}: {exc}")
                failures += 1
                continue

        digest = sha256_of(target)
        expected = lock.get(src["id"])
        if expected and expected != digest:
            print(f"FAIL {src['id']}: checksum changed (locked {expected[:12]}...)")
            failures += 1
            continue
        if not expected:
            lock[src["id"]] = digest
            changed = True
        print(f"OK   {src['id']}")

    if changed:
        lock_path.write_text(yaml.safe_dump(dict(sorted(lock.items()))), encoding="utf-8")
    print(f"{len(sources) - failures}/{len(sources)} documents ready in {out_dir}")
    return 1 if failures else 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=REPO_ROOT / "data" / "sources.yaml")
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "data" / "raw")
    args = parser.parse_args()
    sys.exit(sync(args.manifest, args.out))


if __name__ == "__main__":
    main()
