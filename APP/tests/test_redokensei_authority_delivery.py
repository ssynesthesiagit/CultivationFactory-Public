"""Integrated authority follows actual delivery, including off-turn table attacks."""
from types import SimpleNamespace

import pytest

from combat.ext import integrated_authority as ia
from tests import worker2_support as w
from tests.hunt12_support import hit_dice
from tests.test_redokensei_initiative_blade import BLADE, KIT

REFINED = ia.PREFIX + "refined_iron_fist"
HEAVENLY = ia.PREFIX + "heavenly_fist"


def test_integrated_blade_opportunity_force_commits_and_reloads(tmp_path, monkeypatch):
    hit_dice(monkeypatch)
    combat, table, mid = w.fixture(tmp_path, [], owner_features=[BLADE, REFINED, HEAVENLY],
        owner_path="Body Refining", primary="Stamina", cl=18, owner_kit=KIT,
        positions={w.OWNER: {"x": 3, "y": 6}, w.ALLY: {"x": 3, "y": 7},
                   w.FOE: {"x": 4, "y": 6}})
    w.turn(table, mid, w.FOE)
    engine = w.reload(tmp_path, mid)
    opportunity = next(a for a in engine.action_catalog.values() if a.owner_id == w.OWNER
                       and a.parameters.get("typed", {}).get("opportunity_of"))
    typed = opportunity.parameters["typed"]
    assert ".weapon.dao" in typed["opportunity_of"]
    assert typed["mundane"] is False
    assert typed["weapon"]["magical"] == typed["weapon"]["cultivation_powered"] == 1
    assert typed["weapon"]["adamantine"] == 1
    sequence = engine.state.event_sequence
    move = next(c for c in engine.legal_candidates() if c.kind == "MOVE" and c.destination
                and (c.destination.x, c.destination.y) == (6, 6))
    prompts = w.settle(table, mid, move.candidate_id, choices={
        "reaction:typed.opportunity_attack": "first",
        "choice:needle.heavenly_fist_type": "FORCE",
        "choice:needle.blade_fist": "speed"})
    assert any(p["context"]["reaction_source_id"] == "choice:needle.heavenly_fist_type"
               and "FORCE" in [o["id"] for o in p["choice"]["options"]] for p in prompts)
    engine = w.reload(tmp_path, mid)
    events = [e for e in engine.events if e.sequence > sequence]
    assert any(e.event_type == "ATTACK_ROLLED" and e.actor_id == w.OWNER
               and e.source_definition_id == opportunity.source_definition_id for e in events)
    damage = [e for e in events if e.event_type == "DAMAGE_COMMITTED"
              and e.actor_id == w.OWNER and e.target_ids == (w.FOE,)]
    assert damage and any(e.payload["damage_type"].upper() == "FORCE" for e in damage)


@pytest.mark.parametrize("field", ["delivered_by", "weapon_source_id"])
@pytest.mark.parametrize("feature", [REFINED, HEAVENLY])
def test_delivered_technique_uses_integrated_weapon_at_compile_and_runtime(field, feature):
    """Both public delivery fields must resolve to the same saved authority row."""
    from combat.gate2_runtime_models import ActionDefinition
    from combat.factory_compiler import compile_character
    from tests.h1_support import sheet

    doc = sheet([], cl=18, primary="Stamina", kit=KIT)
    doc["identity"]["path"] = "Body Refining"
    doc.setdefault("path_and_subpath", {})["path_feature_record_ids"] = [BLADE, feature]
    bundle = compile_character(doc, actor_id=w.OWNER)
    base = next(a for a in bundle["action_catalog"]
                if a["source_definition_id"].endswith(".weapon.dao"))
    import copy
    technique = copy.deepcopy(base)
    technique["source_definition_id"] = "action:test.delivered"
    technique["parameters"]["typed"][field] = base["source_definition_id"]
    technique["parameters"]["typed"]["mundane"] = True
    bundle["action_catalog"].append(technique)
    # Re-run the same compile provider on a synthetic delivered technique; no
    # history/private fixtures and no dependency on a particular sphere's art.
    info = {"owned_ids": [BLADE, feature], "numbers": {"cl": 18},
            "mechanics": {BLADE: {"effects": [
                {"type": "path_passive", "kind": "integrated_weapon", "group": "blade"}]}}}
    result = ia.authority_rows(bundle, info)
    action = ActionDefinition.model_validate(result["action_catalog"][-1])
    assert action.parameters["typed"]["mundane"] is False
    assert action.parameters["typed"]["weapon"]["cultivation_powered"] == 1
    engine = SimpleNamespace(action_catalog={
        a["source_definition_id"]: ActionDefinition.model_validate(a)
        for a in (base, result["action_catalog"][-1])},
        typed_passive_rows={w.OWNER: result["typed_passives"]},
        state=SimpleNamespace(state_version=0, event_sequence=0))
    # Historical catalogs without managed grips retain their wielding policy.
    actor = SimpleNamespace(entity_id=w.OWNER, conditions={}, turn_flags={})
    row = ia.weapon_row(engine, actor, action)
    assert row and row["weapon"] == base["source_definition_id"]
    assert row["heavenly"] == int(feature == HEAVENLY)
