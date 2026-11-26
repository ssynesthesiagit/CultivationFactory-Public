"""Journey fact admission is GM-only and has no unauthenticated HTTP route."""
from tests.h1_support import ROOT


def test_journey_fact_http_route_is_not_exposed(tmp_path):
    # This local API has no GM sign-in, so GM-only admission stays a service seam.
    from app.api import create_app
    from app.core import Settings
    app = create_app(Settings.from_env(ROOT, tmp_path))
    assert not [r for r in app.routes if getattr(r, 'path', '').endswith('/facts')]
