"""Exercise the real mobile route without sockets or browser dependencies."""

import asyncio
from pathlib import Path

from app.api import create_app
from app.core import Settings
from tests.h1_support import ROOT


def test_mobile_play_route_serves_configured_page(tmp_path):
    settings = Settings.from_env(ROOT, tmp_path)
    page = settings.root_dir / "static" / "play" / "play.html"
    # Verify real routing and its returned response; do not modify the live app/data.
    app = create_app(settings)
    route = next(route for route in app.routes if getattr(route, "path", None) == "/play")
    response = route.endpoint()
    assert response.path == page
    assert response.headers["cache-control"] == "no-cache"


def test_mobile_play_route_is_registered_separately_from_tabletop():
    app = create_app(Settings.from_env(ROOT, Path("/var/tmp/mobile-route-test")))
    routes = {getattr(route, "path", None) for route in app.routes}
    assert "/play" in routes
    assert "/tabletop" in routes
    assert "/tabletop/sheet" in routes
