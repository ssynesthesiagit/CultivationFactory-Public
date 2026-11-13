"""Journey fact admission is GM-only and has no unauthenticated HTTP route."""
from tests.h1_support import ROOT


def test_journey_fact_http_route_is_not_exposed(tmp_path):
    # This local API has no GM sign-in, so GM-only journey admission stays a service seam.
    # The table's owner fact route (/api/tabletop/matches/{id}/facts) is a separate, token-guarded producer.
    from app.api import create_app
    from app.core import Settings
    app = create_app(Settings.from_env(ROOT, tmp_path))
    paths = [getattr(r, 'path', '') for r in app.routes]
    assert not [p for p in paths if '/journeys/' in p and p.endswith('/facts')]
