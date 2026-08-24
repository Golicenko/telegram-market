from starlette.requests import Request
from starlette.responses import Response

from app import main
from app.frontend import FRONTEND_BUILD, versioned_webapp_url


def make_request(path: str, query: str = "") -> Request:
    return Request({"type": "http", "method": "GET", "path": path, "query_string": query.encode(), "headers": []})


def test_index_is_never_cached():
    response = Response()
    main.set_frontend_cache_headers(make_request("/"), response)
    assert response.headers["cache-control"] == "no-store, no-cache, must-revalidate, max-age=0"
    assert response.headers["pragma"] == "no-cache"
    assert response.headers["x-autoflow-frontend-build"] == main.FRONTEND_BUILD


def test_only_current_versioned_assets_are_immutable():
    current = Response()
    main.set_frontend_cache_headers(make_request("/js/app.js", f"v={main.FRONTEND_BUILD}"), current)
    assert current.headers["cache-control"] == "public, max-age=31536000, immutable"

    stale = Response()
    main.set_frontend_cache_headers(make_request("/js/app.js", "v=old-build"), stale)
    assert stale.headers["cache-control"] == "no-cache, must-revalidate"


def test_telegram_entry_url_is_versioned_without_changing_domain_or_path():
    url = versioned_webapp_url("https://market.example/app?start=deal_1")
    assert url.startswith("https://market.example/app?")
    assert "start=deal_1" in url
    assert f"af_build={FRONTEND_BUILD}" in url
