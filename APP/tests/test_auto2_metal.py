"""Metal second pass through session execute_intent, table choices and cold reload.

The Insight is compiled from its finalized sheet. Synthetic hostile actions
provide exact pending save consequences; no live engine state is edited.
"""
import json

import pytest

from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests import auto_worker1_support as H

INSIGHT = "insight.hard-meridian-breathing"


def table_fight(tmp_path, monkeypatch, ability="STR", hazard="prone", *, owned=True,
                dc=100, primary="Qi", drain=False, repeat=False, already_restrained=False):
    original = H.sheet

    def sheet(*args, **kwargs):
        doc = original(*args, **kwargs)
        if owned:
            doc.setdefault("spheres_and_talents", {})["cultivation_insight_record_ids"] = [INSIGHT]
        return doc

    monkeypatch.setattr(H, "sheet", sheet)
    effect = ({"type": "forced_movement", "direction": "away", "distance_ft": 5}
              if hazard == "forced_movement" else
              {"type": "condition", "condition": hazard, "duration": "until_start_of_next_turn"})
    if repeat:
        effect = {**effect, "duration": "one_minute", "repeat_save": {"ability": ability, "when": "end"}}
    cause = [{"type": "save", "ability": ability, "on_fail": [effect], "on_success": []}]
    c, t, m = H.fight(tmp_path, [], cause=cause, cause_save_dc=dc, left_resource=primary,
                      spheres=("tianxia.sphere.metal",) if owned else (),
                      right_spheres=("tianxia.sphere.metal",) if owned else (),
                      prepare=[{"type": "condition", "condition": "restrained", "applies_to": "self",
                                "duration": "one_minute"}] if already_restrained else
                              [{"type": "spend_resource", "resource_id": "resource:core.qi",
                                "flat": 100, "applies_to": "self"}] if drain else [],
                      prepare_target="SELF")
    if drain or already_restrained:
        H.resolve(lambda answers: H.act(t, m, "Prepare", answers))
    H.turn(t, m, H.RIGHT)
    return c, t, m


def cause(t, m, *, accept=True, source="Cause"):
    answers, prompts = [], []
    for _ in range(8):
        result = H.act(t, m, source, answers, target_id=H.LEFT if source == "Cause" else None)
        if result["status"] != "REACTION_REQUIRED":
            assert result["status"] == "COMMITTED", result
            return prompts
        prompt = result["reaction"]
        assert prompt["context"]["reaction_source_id"] == "reaction:typed." + INSIGHT, prompt
        prompts.append(prompt)
        answers.append({**prompt["context"], "selection": "USE" if accept else "DECLINE"})
    raise AssertionError("too many prompts")


def cold(c, m):
    before = c._load_session(m).engine.state.model_dump(mode="json")
    fresh = CombatService(H.ROOT, c.userdata_root)
    loaded = fresh._load_session(m)
    assert loaded.engine.state.model_dump(mode="json") == before
    assert loaded.verify()["status"] == "PASS"
    assert loaded.mechanical.replay()["status"] == "PASS"
    return fresh, TabletopService(fresh, c.userdata_root), loaded.engine


@pytest.mark.parametrize("ability", ["STR", "CON"])
@pytest.mark.parametrize("hazard", ["forced_movement", "prone", "grappled", "restrained"])
def test_hard_meridian_all_printed_hazards_once_per_scene(tmp_path, monkeypatch, ability, hazard):
    c, t, m = table_fight(tmp_path, monkeypatch, ability, hazard)
    before = c._load_session(m).engine.state.actors[H.LEFT].model_copy(deep=True)
    prompts = cause(t, m)
    assert prompts
    assert "You must use the new result" in str(prompts)
    assert "once in this fight" in str(prompts)
    assert "no Action or Reaction" in str(prompts)
    c, t, e = cold(c, m)
    owner = e.state.actors[H.LEFT]
    assert owner.resources["resource:core.qi"] == before.resources["resource:core.qi"] - 1
    assert owner.reaction_available == before.reaction_available
    assert owner.action_available == before.action_available
    assert owner.bonus_action_available == before.bonus_action_available
    rewrites = [v for v in e.events if v.event_type == "D20_REWRITTEN" and v.source_definition_id == INSIGHT]
    assert len(rewrites) == 1
    rewritten = rewrites[0].payload
    assert rewritten["operation"] == "reroll"
    saves = [v for v in e.events if v.event_type == "SAVE_ROLLED" and v.actor_id == H.LEFT]
    assert saves[-1].payload["natural_result"] == rewritten["result"]["natural_result"]
    assert saves[-1].payload["total"] == rewritten["result"]["total"]
    assert saves[-1].payload["success"] is False  # new failure is binding; no second reroll
    assert not cause(t, m)
    H.turn(t, m, H.LEFT)
    H.turn(t, m, H.RIGHT)
    assert not cause(t, m)
    _, _, e = cold(c, m)
    assert len([v for v in e.events if v.event_type == "D20_REWRITTEN" and v.source_definition_id == INSIGHT]) == 1
    assert not any(v.event_type == "GM_RIDER" and INSIGHT in json.dumps(v.model_dump(mode="json")) for v in e.events)


@pytest.mark.parametrize("case", ["missing", "DEX", "WIS", "unrelated", "success", "empty_pool"])
def test_hard_meridian_ineligible_saves_are_inert(tmp_path, monkeypatch, case):
    c, t, m = table_fight(tmp_path, monkeypatch,
        ability=case if case in ("DEX", "WIS") else "STR",
        hazard="frightened" if case == "unrelated" else "prone",
        owned=case != "missing", dc=-100 if case == "success" else 100,
        drain=case == "empty_pool")
    before = c._load_session(m).engine.state.actors[H.LEFT].resources.copy()
    assert not cause(t, m)
    _, _, e = cold(c, m)
    assert not any(v.event_type == "D20_REWRITTEN" and v.source_definition_id == INSIGHT for v in e.events)
    assert e.state.actors[H.LEFT].resources == before


@pytest.mark.parametrize("primary,pool", [("Qi", "resource:core.qi"), ("Stamina", "resource:core.stamina")])
def test_declining_preserves_payment_and_scene_use_on_cold_reload(tmp_path, monkeypatch, primary, pool):
    c, t, m = table_fight(tmp_path, monkeypatch, primary=primary)
    before = c._load_session(m).engine.state.actors[H.LEFT].resources[pool]
    assert cause(t, m, accept=False)
    c, t, e = cold(c, m)
    assert e.state.actors[H.LEFT].resources[pool] == before
    assert not any(v.event_type == "D20_REWRITTEN" and v.source_definition_id == INSIGHT for v in e.events)
    assert cause(t, m)
    _, _, e = cold(c, m)
    assert e.state.actors[H.LEFT].resources[pool] == before - 1


def test_successful_new_result_is_authoritative(tmp_path, monkeypatch):
    c, t, m = table_fight(tmp_path, monkeypatch, dc=16)
    assert cause(t, m, accept=False)  # deterministic first die totals 14
    H.turn(t, m, H.LEFT)
    H.turn(t, m, H.RIGHT)  # expire the earlier Prone before the next hazard
    assert cause(t, m)  # next save totals 6, reroll totals 19
    _, _, e = cold(c, m)
    saves = [v for v in e.events if v.event_type == "SAVE_ROLLED" and v.actor_id == H.LEFT]
    assert saves[-1].payload["success"] is True
    assert not any(v.condition_id == "condition:typed.prone" for v in e.state.actors[H.LEFT].conditions.values())


def test_native_repeat_save_has_the_same_optional_reroll(tmp_path, monkeypatch):
    c, t, m = table_fight(tmp_path, monkeypatch, hazard="restrained", repeat=True, dc=16)
    assert cause(t, m, accept=False)
    c, t, _ = cold(c, m)
    H.turn(t, m, H.LEFT)
    assert cause(t, m, source="end")
    _, _, e = cold(c, m)
    assert not any(v.condition_id == "condition:typed.restrained" for v in e.state.actors[H.LEFT].conditions.values())
    assert len([v for v in e.events if v.event_type == "D20_REWRITTEN" and v.source_definition_id == INSIGHT]) == 1


def test_existing_restraint_does_not_qualify_an_unrelated_save(tmp_path, monkeypatch):
    c, t, m = table_fight(tmp_path, monkeypatch, hazard="frightened", already_restrained=True)
    assert not cause(t, m)
    _, _, e = cold(c, m)
    assert not any(v.event_type == "D20_REWRITTEN" and v.source_definition_id == INSIGHT for v in e.events)
