"""Sense explanations are a table projection, derived again after commit/reload."""
import pytest

from combat.canonical import canonical_sha256
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.r1i_service_support import OWNER, FOE, SECOND, candidate, fixture


@pytest.mark.parametrize("sense", ["spiritual_sense", "tremorsense", "blindsight"])
def test_known_without_sight_projection_after_commit_reload(tmp_path, sense):
    def grant(bundles):
        owner = bundles[0]
        owner["senses"] = {"rows": [{"sense": sense, "range_ft": 30, "when": "always"}]}
        action = next(a for a in owner["action_catalog"] if a["display_name"] == "Seed-Thorn Strike")
        action["parameters"]["typed"]["effects"] = [
            {"type": "condition", "condition": "blinded", "applies_to": "self", "expires_on": "UNTIL_REMOVED"},
        ]
        owner.pop("bundle_sha256", None)
        owner["bundle_sha256"] = canonical_sha256(owner)

    combat, table, mid, _, commit = fixture(tmp_path, ["TAL_VERDANT_GROWTH_SEED_THORN_STRIKE"],
        positions={OWNER: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}, SECOND: {"x": 15, "y": 6}},
        bundle_transform=grant, seed="SENSEDTOKEN-" + sense)
    before = table.state(mid, fog=True)["fog_perception"][OWNER]
    assert FOE in before["creatures"]
    assert FOE not in before["sensed_creatures"]
    commit(candidate(table, mid, "Seed-Thorn Strike", FOE))
    for current in (table, TabletopService(CombatService(combat.source_root, tmp_path), tmp_path)):
        fog = current.state(mid, fog=True)["fog_perception"]
        row = fog[OWNER]
        assert FOE in row["creatures"]
        if sense == "blindsight":
            # The printed rule counts Blindsight as sight; it reveals terrain too.
            # The look still explains that this Blinded viewer senses the creature.
            assert [4, 6] in row["cells"]
        else:
            assert [4, 6] not in row["cells"]
        assert row["sensed_creatures"][FOE] == [sense]
        assert OWNER not in row["sensed_creatures"]
        assert SECOND not in row["creatures"]
        assert SECOND not in row["sensed_creatures"]
        assert FOE not in fog[FOE]["sensed_creatures"]
        assert OWNER not in fog[FOE]["sensed_creatures"]
    assert combat._load_session(mid).mechanical.replay()["status"] == "PASS"


def test_large_creature_visible_through_footprint_is_not_labelled_sensed(tmp_path, monkeypatch):
    combat, table, mid, _, _ = fixture(tmp_path, [],
        positions={OWNER: {"x": 3, "y": 5}, FOE: {"x": 4, "y": 7}, SECOND: {"x": 15, "y": 5}},
        wide=True, seed="SENSEDTOKEN-large-footprint-sight")
    session = combat._load_session(mid)
    engine = session.engine
    target = engine.state.actors[FOE]
    target.transformed_size_category = "Large"
    # The corner wall hides the target's anchor while another footprint cell
    # has an unobstructed ray from the viewer.
    engine.grid.opaque.add((3, 6))

    from combat.senses import perceives_cell, physical_sight
    from combat.gate2_runtime_models import Position
    viewer = engine.state.actors[OWNER]
    assert not perceives_cell(engine, viewer, target.position)
    assert perceives_cell(engine, viewer, Position(x=5, y=7))
    assert physical_sight(engine, viewer, target)
    monkeypatch.setattr(table, "_load_state_session", lambda _match_id: session)

    row = table.state(mid, fog=True)["fog_perception"][OWNER]
    assert FOE in row["creatures"]
    assert FOE not in row["sensed_creatures"]


@pytest.mark.parametrize(("sense", "expected_sensed"), [
    ("spiritual_sense", True),
    ("truesight", False),
])
def test_unblinded_concealed_creature_uses_alternate_sense_unless_truesight_sees_it(
        tmp_path, monkeypatch, sense, expected_sensed):
    def grant(bundles):
        owner = bundles[0]
        owner["senses"] = {"rows": [{"sense": sense, "range_ft": 30, "when": "always"}]}
        owner.pop("bundle_sha256", None)
        owner["bundle_sha256"] = canonical_sha256(owner)

    combat, table, mid, _, _ = fixture(tmp_path, [],
        positions={OWNER: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}, SECOND: {"x": 15, "y": 6}},
        bundle_transform=grant, seed="SENSEDTOKEN-unblinded-invisible")
    session = combat._load_session(mid)
    engine = session.engine
    engine._apply_condition(engine.state.actors[FOE], "condition:typed.invisible", "test:sensed-token",
                            FOE, expires_on="UNTIL_REMOVED", data={})
    monkeypatch.setattr(table, "_load_state_session", lambda _match_id: session)

    row = table.state(mid, fog=True)["fog_perception"][OWNER]
    assert FOE in row["creatures"]
    if expected_sensed:
        assert row["sensed_creatures"][FOE] == [sense]
    else:
        assert FOE not in row["sensed_creatures"]
    assert OWNER not in row["sensed_creatures"]


@pytest.mark.parametrize("sense,environment,extra_sense,invisible,expected_sensed", [
    (sense, environment, None, False, True)
    for sense in ("spiritual_sense", "blindsight")
    for environment in ("smoke", "fog", "darkness")
] + [
    ("spiritual_sense", "smoke", "truesight", True, True),
    ("truesight", "darkness", None, True, False),
    ("darkvision", "darkness", None, False, False),
    (None, None, None, False, False),
])
def test_sight_only_environmental_projection_after_commit_reload(
        tmp_path, sense, environment, extra_sense, invisible, expected_sensed):
    """Alternate senses retain combat sight without leaking into visual presentation.

    A hostile creature creates the obstruction through a table action. Check
    fresh reloads too, so the area, condition and derived explanation follow the
    same persisted fight rather than a substituted perception dictionary.
    """
    from combat import senses, zones

    def prepare(bundles):
        bundles[0]["senses"] = {"rows": [
            {"sense": name, "range_ft": 30, "when": "always"}
            for name in (sense, extra_sense) if name
        ]}
        foe = bundles[1]
        action = next(a for a in foe["action_catalog"] if a["display_name"] == "Seed-Thorn Strike")
        typed = action["parameters"]["typed"]
        typed["effects"] = ([{"type": "condition", "condition": "invisible", "applies_to": "self",
                              "expires_on": "UNTIL_REMOVED"}] if invisible else [])
        if environment:
            typed["effects"].append({"type": "zone"})
            typed["zone_spec"] = {
                "name": "Darkness" if environment == "darkness" else "Smoke" if "smoke" in environment else "Fog",
                "centered_on_self": True, "shape": "sphere", "size_ft": 5,
                "obscured": "heavy", "duration": {"kind": "rounds", "amount": 5},
                **({"visual": {"darkness": True}} if environment == "darkness" else {}),
            }
        for bundle in bundles[:2]:
            bundle.pop("bundle_sha256", None)
            bundle["bundle_sha256"] = canonical_sha256(bundle)

    combat, table, mid, _, commit = fixture(tmp_path, [],
        foe_talents=["TAL_VERDANT_GROWTH_SEED_THORN_STRIKE"], wide=True,
        positions={OWNER: {"x": 3, "y": 6}, FOE: {"x": 6, "y": 6}, SECOND: {"x": 15, "y": 6}},
        bundle_transform=prepare, seed="SENSEDTOKEN-environment")
    while table.state(mid)["menu"]["actor_id"] != FOE:
        commit(table.state(mid)["menu"]["end_turn"])
    commit(candidate(table, mid, "Seed-Thorn Strike", OWNER))

    for current in (table, TabletopService(CombatService(combat.source_root, tmp_path), tmp_path)):
        engine = current.combat._load_session(mid).engine
        viewer, target = engine.state.actors[OWNER], engine.state.actors[FOE]
        assert senses.perceives(engine, viewer, target, locate_concealed=True)
        assert senses.perceives(engine, viewer, target, locate_concealed=True, sight_only=False)
        assert senses.ordinary_sight_perceives(engine, viewer, target) is (not expected_sensed)
        assert not zones.hidden_from(engine, viewer, target)
        if environment:
            assert zones.hidden_from(engine, viewer, target, sight_only=True) is expected_sensed
        row = current.state(mid, fog=True)["fog_perception"][OWNER]
        assert FOE in row["creatures"]
        if expected_sensed:
            assert row["sensed_creatures"][FOE] == [sense]
        else:
            assert FOE not in row["sensed_creatures"]
        assert OWNER not in row["sensed_creatures"]
    assert combat._load_session(mid).mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("sense,obstruction,expected_sensed", [
    ("spiritual_sense", "wall", True), ("blindsight", "wall", True),
    ("blindsight", "observer", True), ("truesight", "observer", False),
])
def test_sight_only_filter_reaches_wall_and_observer_policy(
        tmp_path, monkeypatch, sense, obstruction, expected_sensed):
    from combat import senses, zones
    from combat.gate2_runtime_models import Position, ZoneState

    def grant(bundles):
        owner = bundles[0]
        owner["senses"] = {"rows": [{"sense": sense, "range_ft": 30, "when": "always"}]}
        owner.pop("bundle_sha256", None)
        owner["bundle_sha256"] = canonical_sha256(owner)

    combat, table, mid, _, _ = fixture(tmp_path, [], wide=True,
        positions={OWNER: {"x": 3, "y": 6}, FOE: {"x": 6, "y": 6}, SECOND: {"x": 15, "y": 6}},
        bundle_transform=grant, seed="SENSEDTOKEN-wall")
    session = combat._load_session(mid)
    engine = session.engine
    center = Position(x=4, y=6)
    wall = ZoneState(zone_id="zone:test:sensed-wall", source_definition_id="test:sensed-wall", owner_id=FOE,
        center=center, radius_cells=0, affected_cells=(center,), concentration_link=False,
        created_round=engine.state.round_number,
        trigger_profile={"kind": zones.KIND,
                         **({"wall": {"material": "smoke", "obscures": "any"}} if obstruction == "wall" else {})})
    engine.state.zones[wall.zone_id] = wall
    viewer, target = engine.state.actors[OWNER], engine.state.actors[FOE]
    if obstruction == "observer":
        engine._apply_condition(viewer, "condition:typed.zone_view_restriction", "test:restriction", FOE,
            expires_on="UNTIL_REMOVED", data={"zone_source": "test:sensed-wall", "preserve_senses": [sense]})
    assert senses.physical_sight(engine, viewer, target)
    assert senses.perceives(engine, viewer, target, locate_concealed=True)
    assert not zones.hidden_from(engine, viewer, target)
    assert zones.hidden_from(engine, viewer, target, sight_only=True) is expected_sensed
    monkeypatch.setattr(table, "_load_state_session", lambda _mid: session)
    row = table.state(mid, fog=True)["fog_perception"][OWNER]
    if expected_sensed:
        assert row["sensed_creatures"][FOE] == [sense]
    else:
        assert FOE not in row["sensed_creatures"]


@pytest.mark.parametrize(("visual_sense", "expected_sensed"), [(None, True), ("truesight", False)])
def test_fruiting_body_blindsight_mask_is_not_visual(tmp_path, visual_sense, expected_sensed):
    """Fruiting Body can locate a poisoned Invisible creature without making it visible."""
    from combat import senses

    fruiting_body = "tianxia.tradition.spirit.mushroom_dreamwalker.feature.fruiting_body_of_the_dream"
    mycelial_dream = "tianxia.tradition.spirit.mushroom_dreamwalker.feature.mycelial_dream"

    def prepare(bundles):
        owner = next(bundle for bundle in bundles if bundle["actor_id"] == OWNER)
        if visual_sense:
            owner["senses"] = {"rows": [{"sense": visual_sense, "range_ft": 60, "when": "always"}]}
        foe = next(bundle for bundle in bundles if bundle["actor_id"] == FOE)
        action = next(a for a in foe["action_catalog"] if a["display_name"] == "Seed-Thorn Strike")
        action["parameters"]["typed"]["effects"].extend([
            {"type": "condition", "condition": "poisoned", "applies_to": "self", "expires_on": "UNTIL_REMOVED"},
            {"type": "condition", "condition": "invisible", "applies_to": "self", "expires_on": "UNTIL_REMOVED"},
        ])
        from combat.canonical import canonical_sha256
        for bundle in (owner, foe):
            bundle.pop("bundle_sha256", None)
            bundle["bundle_sha256"] = canonical_sha256(bundle)

    combat, table, mid, _, commit = fixture(tmp_path, [mycelial_dream, fruiting_body],
        owner_cl=18,
        owner_path="Spirit Awakening", owner_resource="Resonance",
        foe_talents=["TAL_VERDANT_GROWTH_SEED_THORN_STRIKE"],
        positions={OWNER: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}, SECOND: {"x": 15, "y": 6}},
        bundle_transform=prepare, seed="SENSEDTOKEN-fruiting-mask")
    commit(candidate(table, mid, "Fruiting Body of the Dream"))
    while table.state(mid)["menu"]["actor_id"] != FOE:
        commit(table.state(mid)["menu"]["end_turn"])
    commit(candidate(table, mid, "Seed-Thorn Strike", OWNER))

    for current in (table, TabletopService(CombatService(combat.source_root, tmp_path), tmp_path)):
        engine = current.combat._load_session(mid).engine
        viewer, target = engine.state.actors[OWNER], engine.state.actors[FOE]
        assert any(c.condition_id == "condition:typed.poisoned" for c in target.conditions.values())
        assert any(c.condition_id == "condition:typed.invisible" for c in target.conditions.values())
        assert senses.perceives(engine, viewer, target, locate_concealed=True)
        assert senses.ordinary_sight_perceives(engine, viewer, target) is (not expected_sensed)
        row = current.state(mid, fog=True)["fog_perception"][OWNER]
        if expected_sensed:
            assert row["sensed_creatures"][FOE] == ["blindsight"]
        else:
            assert FOE not in row["sensed_creatures"]
    assert combat._load_session(mid).mechanical.replay()["status"] == "PASS"
