"""Stamp static frontend assets with a content-derived build identifier."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
WEBAPP = ROOT / "webapp"
INDEX = WEBAPP / "index.html"
ASSETS = (WEBAPP / "css" / "style.css", WEBAPP / "js" / "api.js", WEBAPP / "js" / "app.js")


def normalized_index_bytes() -> bytes:
    """Hash HTML changes without feeding the previously stamped build back into the digest."""
    html = INDEX.read_text(encoding="utf-8")
    html = re.sub(r'(<meta name="autoflow-build" content=")[^"]+(" */?>)', r'\g<1>BUILD\2', html)
    for asset_url in ("css/style.css", "js/api.js", "js/app.js"):
        html = re.sub(rf'({re.escape(asset_url)}\?v=)[^"&]+', rf'\g<1>BUILD', html)
    return html.encode("utf-8")


def calculate_build_id() -> str:
    digest = hashlib.sha256()
    digest.update(b"index.html")
    digest.update(normalized_index_bytes())
    for asset in ASSETS:
        digest.update(asset.relative_to(WEBAPP).as_posix().encode("utf-8"))
        digest.update(asset.read_bytes())
    return f"af-{digest.hexdigest()[:12]}"


def stamp_index(build_id: str) -> None:
    html = INDEX.read_text(encoding="utf-8")
    html = re.sub(r'(<meta name="autoflow-build" content=")[^"]+(" */?>)', rf"\g<1>{build_id}\2", html)
    for asset_url in ("css/style.css", "js/api.js", "js/app.js"):
        html = re.sub(rf'({re.escape(asset_url)}\?v=)[^"&]+', rf"\g<1>{build_id}", html)
    INDEX.write_text(html, encoding="utf-8")
    (WEBAPP / "build-info.json").write_text(json.dumps({"build": build_id}), encoding="utf-8")


if __name__ == "__main__":
    stamp_index(calculate_build_id())
