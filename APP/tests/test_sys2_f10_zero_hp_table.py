"""Synthetic table scripts for SYS2's two zero-HP replacements.

The stimulus is a training blow, not an invented character ability. Both
scripts use identical saved bundles, seed and damage; only the owner's pick
differs. Every request and answer travels through TabletopService.act.
"""
import json

import pytest

from combat import ext
from combat.canonical import canonical_sha256
from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import ActionDefinition, EconomyKind
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.test_auto_bodya import BODY_REFINING_SHEET, ROOT
from tests.test_sys2_f9_zero_hp_choice_transport import CHOICE, PATH, transport_authority

OWNER = "actor:factory.sys2-owner"
FOE = "actor:factory.sys2-foe"
BLOOD = PATH + "blood_pump"
IRON = "tianxia.subpath.body.iron_shirt.feature.invincible_iron"
STAMINA = "resource:core.stamina"
BLOW = "action:test.sys2.training_blow"


def fixture(root, monkeypatch):
    authority = transport_authority()
    sheet = {**BODY_REFINING_SHEET,
             "identity": {**BODY_REFINING_SHEET["identity"], "cultivation_level": 18},
             "path_and_subpath": {"path_feature_record_ids": [BLOOD, IRON]}}
    owner = compile_character(sheet, actor_id=OWNER, typed_authority=authority,
                              reaction_plan={"ask": True})
    foe = compile_character({**sheet, "path_and_subpath": {"path_feature_record_ids": []}},
                            actor_id=FOE, typed_authority=authority)
    assert {r["feature_id"] for r in owner["typed_reactions"]
            if r.get("kind") == "drop_to_zero"} == {BLOOD, IRON}

    def blow(ctx, effect):
        ctx.engine._commit_damage(ctx.engine.state.actors[OWNER], 65, "FORCE",
                                 ctx.source, ctx.actor.entity_id, ctx.intent, reaction_depth=0)

    ext.effects()
    monkeypatch.setitem(ext._EFFECTS, "sys2_training_blow", blow)
    action = ActionDefinition(source_definition_id=BLOW, display_name="Training blow",
        owner_id=FOE, economy=EconomyKind.ACTION, resolution_kind="TYPED",
        target_kind="HOSTILE_ENTITY", range_ft=5,
        parameters={"typed": {"effects": [{"type": "sys2_training_blow"}],
                              "numbers": {}, "riders": []}})
    foe["action_catalog"].append(action.model_dump(mode="json"))
    foe["actor_template"]["action_ids"].append(BLOW)
    foe.pop("bundle_sha256")
    foe["bundle_sha256"] = canonical_sha256(foe)
    combat = CombatService(ROOT, root)
    table = TabletopService(combat, root)
    mid = combat._finish_factory_match([owner, foe], [OWNER, FOE],
        {OWNER: "team:a", FOE: "team:b"},
        {OWNER: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"],
        [OWNER], [FOE], control_modes={OWNER: "MANUAL", FOE: "MANUAL"},
        match_seed="SYS2-CHOICE", display_name="SYS2 choice regression",
        maximum_rounds=10)["match_id"]
    for _ in range(3):
        menu = table.state(mid)["menu"]
        if menu["actor_id"] == FOE:
            break
        result = table.act(mid, menu["end_turn"], menu["decision_id"],
                           menu["state_version"], 0, [])
        assert result["status"] == "COMMITTED", result
    else:
        pytest.fail("Training opponent never got its turn")
    return combat, table, mid


def script(root, monkeypatch, pick):
    combat, table, mid = fixture(root, monkeypatch)
    engine = combat._load_session(mid).engine
    candidate = next(c for c in engine.legal_candidates()
                     if c.source_definition_id == BLOW and OWNER in c.target_ids)
    menu = table.state(mid)["menu"]
    answers, prompts = [], []
    before = engine.state.model_dump(mode="json")
    for _ in range(6):
        result = table.act(mid, candidate.candidate_id, menu["decision_id"],
                           menu["state_version"], 0, answers)
        if result["status"] != "REACTION_REQUIRED":
            assert result["status"] == "COMMITTED", result
            break
        prompt = result["reaction"]
        prompts.append(prompt)
        assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
        options = (prompt.get("choice") or {}).get("options") or []
        choice_id = prompt["context"]["reaction_source_id"]
        if choice_id == CHOICE:
            assert len(options) == 2, prompt
            selected = next(o["id"] for o in options if pick in json.dumps(o))
        else:
            assert choice_id.startswith("choice:life.survive:"), prompt
            selected = "use"
        answers.append({**prompt["context"], "selection": "USE", "option_ids": [selected]})
    else:
        pytest.fail("Choice did not commit")
    assert [p["context"]["reaction_source_id"] for p in prompts].count(CHOICE) == 1
    assert "Training blow" in json.dumps(prompts)
    fresh = CombatService(ROOT, root)._load_session(mid)
    assert fresh.engine.state.model_dump(mode="json") == combat._load_session(mid).engine.state.model_dump(mode="json")
    assert fresh.verify()["status"] == "PASS"
    assert fresh.mechanical.replay()["status"] == "PASS"
    actor = fresh.engine.state.actors[OWNER]
    resolved = [e.source_definition_id for e in fresh.engine.events
                if e.event_type == "REACTION_RESOLVED" and (e.payload or {}).get("kind") == "drop_to_zero"]
    expected = IRON if pick == "Invincible Iron" else BLOOD
    assert resolved == [expected]
    assert actor.resources[STAMINA] == before["actors"][OWNER]["resources"][STAMINA] - 6
    assert actor.resources["resource:uses.reaction:typed." + expected] == 0
    other = BLOOD if expected == IRON else IRON
    assert actor.resources["resource:uses.reaction:typed." + other] == 1
    return {"pick": pick, "hp": actor.current_hp, "resolved": resolved,
            "stamina": actor.resources[STAMINA],
            "conditions": sorted(c.condition_id for c in actor.conditions.values()),
            "verify": "PASS", "replay": "PASS"}


def test_owner_pick_changes_the_saved_table_outcome(tmp_path, monkeypatch, capsys):
    iron = script(tmp_path / "script-1", monkeypatch, "Invincible Iron")
    blood = script(tmp_path / "script-2", monkeypatch, "Blood Pump")
    # Both printed replacements leave 1 HP. Invincible Iron additionally
    # activates Iron Wall and its until-next-turn protections; it does not heal.
    assert iron["hp"] == blood["hp"] == 1
    assert iron["conditions"] != blood["conditions"]
    with capsys.disabled():
        print("SYS2 BDIFF " + json.dumps({"script-1": iron, "script-2": blood}, sort_keys=True))
