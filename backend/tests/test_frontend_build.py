import json

from scripts import build_webapp


def test_build_script_stamps_all_assets_with_one_content_hash(tmp_path, monkeypatch):
    webapp = tmp_path / "webapp"
    (webapp / "css").mkdir(parents=True)
    (webapp / "js").mkdir()
    (webapp / "css" / "style.css").write_text("body{}", encoding="utf-8")
    (webapp / "js" / "api.js").write_text("api", encoding="utf-8")
    (webapp / "js" / "app.js").write_text("app", encoding="utf-8")
    index = webapp / "index.html"
    index.write_text(
        '<meta name="autoflow-build" content="source">'
        '<link href="css/style.css?v=old">'
        '<script src="js/api.js?v=old"></script>'
        '<script src="js/app.js?v=old"></script>',
        encoding="utf-8",
    )
    assets = (webapp / "css" / "style.css", webapp / "js" / "api.js", webapp / "js" / "app.js")
    monkeypatch.setattr(build_webapp, "WEBAPP", webapp)
    monkeypatch.setattr(build_webapp, "INDEX", index)
    monkeypatch.setattr(build_webapp, "ASSETS", assets)

    build_id = build_webapp.calculate_build_id()
    build_webapp.stamp_index(build_id)

    stamped = index.read_text(encoding="utf-8")
    assert stamped.count(f"v={build_id}") == 3
    assert f'content="{build_id}"' in stamped
    assert json.loads((webapp / "build-info.json").read_text(encoding="utf-8")) == {"build": build_id}

    # Stamped values are normalized before hashing, so a second build of the
    # same sources keeps exactly the same identifier.
    assert build_webapp.calculate_build_id() == build_id


def test_html_only_change_creates_a_new_build_id(tmp_path, monkeypatch):
    webapp = tmp_path / "webapp"
    (webapp / "css").mkdir(parents=True)
    (webapp / "js").mkdir()
    assets = (webapp / "css" / "style.css", webapp / "js" / "api.js", webapp / "js" / "app.js")
    for asset in assets:
        asset.write_text(asset.name, encoding="utf-8")
    index = webapp / "index.html"
    index.write_text(
        '<meta name="autoflow-build" content="old"><main>Первая версия</main>'
        '<link href="css/style.css?v=old"><script src="js/api.js?v=old"></script>'
        '<script src="js/app.js?v=old"></script>',
        encoding="utf-8",
    )
    monkeypatch.setattr(build_webapp, "WEBAPP", webapp)
    monkeypatch.setattr(build_webapp, "INDEX", index)
    monkeypatch.setattr(build_webapp, "ASSETS", assets)

    first = build_webapp.calculate_build_id()
    index.write_text(index.read_text(encoding="utf-8").replace("Первая версия", "Новая версия"), encoding="utf-8")
    assert build_webapp.calculate_build_id() != first
