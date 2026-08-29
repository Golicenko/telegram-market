import json
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


WEBAPP_DIR = Path(__file__).resolve().parents[2] / "webapp"


def read_frontend_build() -> str:
    try:
        value = json.loads((WEBAPP_DIR / "build-info.json").read_text(encoding="utf-8")).get("build")
        return str(value).strip() or "af-91ee69159db0"
    except (OSError, ValueError, TypeError, AttributeError):
        return "af-91ee69159db0"


FRONTEND_BUILD = read_frontend_build()


def versioned_webapp_url(public_url: str) -> str:
    parts = urlsplit(public_url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["af_build"] = FRONTEND_BUILD
    return urlunsplit((parts.scheme, parts.netloc, parts.path or "/", urlencode(query), parts.fragment))
