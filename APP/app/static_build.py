"""Deploy-safe table assets (owner 2026-10-21, after a stale cached table client broke a fight).

Every table page and ES module is served with a per-deploy version: each relative (or /static/) module import and each
.js/.css asset link in tabletop/*.html and tabletop/*.js gets ``?v=<build>``. The build id changes whenever the server
code, the table files or the server process change, so a reload never mixes old and new files.

Every API response carries ``X-Factory-Build: <build>``. A table page compares it with its own build (its module URL's
``?v=``) and reloads itself with a banner when they differ (APP/static/tabletop/build-check.js).

Source files keep their plain ``?v=`` tags; the stamp is applied only when the file is served. Users of this module:
APP/app/api.py (the tabletop middleware and the /tabletop page).
"""
from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

BUILD_HEADER = "X-Factory-Build"
TABLE_DIR = Path("static") / "tabletop"

# import ... from "./x.js?v=y"  |  import("/static/tabletop/x.js")  |  import "./x.js"
_MODULE_SPEC = re.compile(r'''(\b(?:from|import)\s*\(?\s*)(["'])((?:\.{1,2}/|/static/)[^"'\n?]*?\.m?js)(?:\?[^"'\n]*)?\2''')
# <script src="...js"> and <link href="...css">
_ASSET_LINK = re.compile(r'''((?:src|href)=["'])([^"'?#<>]+\.(?:m?js|css))(?:\?[^"'<>]*)?(["'])''')
_TABLE_SUFFIXES = {".js", ".mjs", ".html", ".css"}
_CONTENT_TYPES = {".js": "text/javascript", ".mjs": "text/javascript", ".html": "text/html", ".css": "text/css"}


def stamp_source(text: str, build: str, suffix: str) -> str:
    """Return ``text`` with every module import (JS) or script/css link (HTML) pointing at ``?v=<build>``."""
    if suffix == ".html":
        return _ASSET_LINK.sub(lambda m: f"{m.group(1)}{m.group(2)}?v={build}{m.group(3)}", text)
    if suffix in (".js", ".mjs"):
        return _MODULE_SPEC.sub(lambda m: f"{m.group(1)}{m.group(2)}{m.group(3)}?v={build}{m.group(2)}", text)
    return text


def compute_build(app_dir: Path, nonce: str) -> str:
    """Build id: APP/app/*.py, the table files and a per-process nonce (restarts count as a deploy)."""
    digest = hashlib.sha256(nonce.encode())
    for path in sorted((app_dir / "app").glob("*.py")) + sorted((app_dir / TABLE_DIR).rglob("*")):
        if path.is_file() and (path.suffix in _TABLE_SUFFIXES or path.suffix == ".py"):
            digest.update(str(path.relative_to(app_dir)).encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


class StaticBuild:
    """Serves stamped table pages/modules and names the build for the X-Factory-Build header."""

    def __init__(self, app_dir: Path, nonce: str | None = None):
        self.app_dir = Path(app_dir).resolve()
        self.static_dir = self.app_dir / "static"
        self.build = compute_build(self.app_dir, nonce or os.urandom(8).hex())
        self._cache: dict[Path, tuple[tuple[int, int], str]] = {}

    def _stamped(self, path: Path) -> str:
        stat = path.stat()
        key = (stat.st_mtime_ns, stat.st_size)
        cached = self._cache.get(path)
        if cached and cached[0] == key:
            return cached[1]
        text = stamp_source(path.read_text(encoding="utf-8"), self.build, path.suffix)
        self._cache[path] = (key, text)
        return text

    def response_for(self, url_path: str):
        """A Response for a table page or module path, or None when the path is not one of ours."""
        from fastapi.responses import Response  # local import keeps this module importable without FastAPI

        table_root = (self.app_dir / TABLE_DIR).resolve()
        if url_path == "/tabletop":
            target = table_root / "tabletop.html"
        elif url_path.startswith("/static/tabletop/"):
            target = (self.static_dir / url_path[len("/static/"):]).resolve()
        else:
            return None
        if target.suffix not in _TABLE_SUFFIXES or not target.is_relative_to(table_root) or not target.is_file():
            return None
        headers = {"Cache-Control": "no-cache", BUILD_HEADER: self.build}
        return Response(self._stamped(target), media_type=f"{_CONTENT_TYPES[target.suffix]}; charset=utf-8",
                        headers=headers)
