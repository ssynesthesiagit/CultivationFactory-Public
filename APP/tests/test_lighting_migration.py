"""Printed ability light inventory and S3 source-shape regression."""
import json
from pathlib import Path
from types import SimpleNamespace

from combat.ext.radiance import HEAVENLY, _bright

ROOT = Path(__file__).resolve().parents[1]


def test_light_source_inventory_matches_printed_authority_and_has_valid_radii():
    rows = json.loads((ROOT / "combat/rules/light_sources.json").read_text())["sources"]
    # Public CI redacts record prose, so this contract uses stable exported mechanic
    # identifiers and the structured radii rather than asserting private text fragments.
    authority = json.loads((ROOT / "authority/typed_mechanics/rules_text.json").read_text())
    assert len(rows) == 17
    assert len({row["mechanic"] for row in rows}) == len(rows)
    for row in rows:
        assert row["mechanic"] in authority
        assert type(row["bright_ft"]) is int and type(row["dim_ft"]) is int
        assert 0 <= row["bright_ft"] <= row["dim_ft"]
        assert row["follows"] in {"self", "zone", "target", "targets", "summon"}
    assert {row["mechanic"]: (row["bright_ft"], row["dim_ft"]) for row in rows}[
        "tianxia.talent.radiance.heavenly_radiance"] == (120, 240)


def test_heavenly_radiance_printed_bright_radius_is_120():
    rows = {row["mechanic"]: row for row in json.loads(
        (ROOT / "combat/rules/light_sources.json").read_text())["sources"]}
    assert rows["tianxia.talent.radiance.heavenly_radiance"]["bright_ft"] == 120
    assert rows["tianxia.talent.radiance.heavenly_radiance"]["dim_ft"] == 240


def test_wick_body_light_has_no_dim_ring():
    source = (ROOT / "combat/ext/wax_reactions.py").read_text()
    assert '"bright_ft": LIGHT_RADIUS_FT, "dim_ft": LIGHT_RADIUS_FT' in source


def test_heavenly_suppression_requires_owners_bright_radius(monkeypatch):
    from combat import lighting

    from combat.lighting import LightSource

    monkeypatch.setattr(lighting, "_square", lambda engine: 5)
    monkeypatch.setattr(lighting, "_Rays", lambda engine: SimpleNamespace(
        disc=lambda sx, sy, radius: SimpleNamespace(clear=lambda x, y: True)))
    target = SimpleNamespace(active=True, entity_id="target", conditions={}, modifiers={}, concentration=None)
    ownerless = SimpleNamespace(active=True, actors={}, state=SimpleNamespace(actors={}),
                                grid=SimpleNamespace(width=40, height=40))
    ownerless._actor_cells = lambda actor: [(30, 30)]
    assert _bright(ownerless, target) is False

    owner = SimpleNamespace(active=True, entity_id="sun", conditions={}, modifiers={}, concentration=None)
    owner.conditions = {"radiance": SimpleNamespace(source_definition_id=HEAVENLY, source_actor_id="sun")}
    source = LightSource(f"radiance:{HEAVENLY}:sun", "Heavenly Radiance", frozenset({(0, 0)}), 120, 240)
    monkeypatch.setattr(lighting, "sources", lambda engine: (source,))
    outside = SimpleNamespace(active=True, actors={"sun": owner}, state=SimpleNamespace(actors={"sun": owner}),
                              grid=SimpleNamespace(width=40, height=40))
    outside._actor_cells = lambda actor: [(0, 0)] if actor is owner else [(30, 30)]
    assert _bright(outside, target) is False

    inside = SimpleNamespace(active=True, actors={"sun": owner}, state=SimpleNamespace(actors={"sun": owner}),
                             grid=SimpleNamespace(width=40, height=40))
    inside._actor_cells = lambda actor: [(0, 0)] if actor is owner else [(24, 0)]
    assert _bright(inside, target) is True
