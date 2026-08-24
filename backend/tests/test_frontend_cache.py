import pytest
from starlette.requests import Request
from starlette.responses import Response

from app import main
from app.frontend import FRONTEND_BUILD, versioned_webapp_url


def make_request(path: str, query: str = "") -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "scheme": "https",
        "server": ("market.example", 443),
        "path": path,
        "query_string": query.encode(),
        "headers": [(b"host", b"market.example")],
    })


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


@pytest.mark.asyncio
async def test_stable_botfather_url_redirects_to_the_current_build_and_preserves_context():
    response = await main.frontend_entry(make_request("/", "start=deal_1&af_build=old"))

    assert response.status_code == 307
    assert response.headers["cache-control"].startswith("no-store")
    assert response.headers["location"].startswith("https://market.example/")
    assert "start=deal_1" in response.headers["location"]
    assert f"af_build={FRONTEND_BUILD}" in response.headers["location"]


@pytest.mark.asyncio
async def test_current_build_entry_serves_index_without_another_redirect():
    response = await main.frontend_entry(make_request("/", f"af_build={FRONTEND_BUILD}"))

    assert response.status_code == 200
    assert response.path.name == "index.html"
