"Regression for refreshing the live lighting inputs after an ambient edit."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_ambient_update_replaces_engine_arena_and_invalidates_light_cache():
    service = (ROOT / "combat/tabletop_service.py").read_text(encoding="utf-8")
    setter = service.split("def set_match_ambient(", 1)[1].split("\n    def _map_section(", 1)[0]

    assert "engine.battlefield_document = copy.deepcopy(arena)" in setter
    assert "self._light_cache.pop(match_id, None)" in setter
