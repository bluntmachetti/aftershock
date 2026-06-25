"""Tests for the SPA caching policy (_CachingStaticFiles in web.py).

Guards the stale-bundle failure mode: a returning visitor must always revalidate index.html
(so it points at the current hashed bundle), while content-hashed assets cache for a year.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from aftershock.web import _CachingStaticFiles


def _client(tmp_path: Path) -> TestClient:
    (tmp_path / "index.html").write_text("<html><body>app</body></html>", encoding="utf-8")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "index-ABC123.js").write_text("console.log(1)", encoding="utf-8")
    (tmp_path / "favicon.svg").write_text("<svg/>", encoding="utf-8")
    app = FastAPI()
    app.mount("/", _CachingStaticFiles(directory=str(tmp_path), html=True), name="static")
    return TestClient(app)


def test_index_html_is_no_cache(tmp_path: Path) -> None:
    c = _client(tmp_path)
    root = c.get("/")
    assert root.status_code == 200
    assert root.headers["cache-control"] == "no-cache"
    # The explicit path resolves to the same policy.
    assert c.get("/index.html").headers["cache-control"] == "no-cache"


def test_hashed_assets_are_immutable(tmp_path: Path) -> None:
    c = _client(tmp_path)
    r = c.get("/assets/index-ABC123.js")
    assert r.status_code == 200
    cc = r.headers["cache-control"]
    assert "immutable" in cc and "max-age=31536000" in cc


def test_other_root_files_keep_default(tmp_path: Path) -> None:
    # Non-html, non-asset files (e.g. a favicon) are left on Starlette's default — no
    # Cache-Control, just etag/last-modified — so the policy targets only index + assets.
    c = _client(tmp_path)
    r = c.get("/favicon.svg")
    assert r.status_code == 200
    assert "cache-control" not in r.headers
