"""Frontend assets are served with module-safe MIME types (Windows can map .js to text/plain) and no auth."""


def test_frontend_assets_have_module_safe_types(client):
    for path, expected in (("/static/app.js", "text/javascript"), ("/static/lib/api.js", "text/javascript"),
                           ("/static/app.css", "text/css"), ("/static/theme.css", "text/css"),
                           ("/static/favicon.svg", "image/svg+xml")):
        r = client.get(path)
        assert r.status_code == 200, path
        assert r.headers["content-type"].startswith(expected), (path, r.headers["content-type"])
        assert r.headers["x-content-type-options"] == "nosniff"


def test_unknown_asset_is_404(client):
    assert client.get("/static/nope.js").status_code == 404
