"""Court's one free strike finishes the real Dodge transaction and replays."""
import copy

import pytest

from combat.canonical import canonical_sha256
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests import test_riders_lane2 as fist
from tests.r1i_service_support import force_ai_candidate
from tests.test_lock_choices import install

ME, FOE, ROOT = fist.ME, fist.FOE, fist.ROOT


def fight(tmp_path, case):
    sheet = fist.A._sheet(fist.IRON_FIST, [fist.COURT, fist.FLURRY], [], cl=12)
    if case == "combined":
        sheet["spheres_and_talents"]["learned_talent_record_ids"].append(
            "tianxia.subpath.body.black_thorn_demon_body.feature.calamity_briar_incarnation")
    if case == "extra":
        sheet["path_and_subpath"]["path_feature_record_ids"] = ["tianxia.path.body_refining.feature.extra_attack"]
    owner = compile_character(sheet,
                              actor_id=ME, reaction_plan={"ask": True})
    if case == "extra":
        natural = next(a for a in owner["action_catalog"] if a["display_name"] == fist.STRIKE)
        assert any(e.get("count", 1) > 1 for e in natural["parameters"]["typed"]["effects"] if e.get("type") == "attack")
    foe = compile_character(fist.A._sheet(None, [], fist.KIT), actor_id=FOE)
    for bundle in (owner, foe):
        # Dodge is forfeited at Speed 0; Court needs a mobile owner to retain it.
        bundle["actor_template"].update(maximum_hp=1 if bundle is foe and case in {"terminal", "auto_terminal"} else 400,
            armor_class=0, speed_ft=30 if bundle is owner else 0,
            initiative_bonus=100 if bundle is owner else -100)
        for action in bundle["action_catalog"]:
            if action["display_name"] == fist.STRIKE:
                action["parameters"]["typed"]["numbers"]["attack_bonus"] = 100
            if case == "legacy" and bundle is owner:
                for row in (action["parameters"].get("typed") or {}).get("effects") or []:
                    row.pop("dodge_strike", None)
        bundle.pop("bundle_sha256", None)
        bundle["bundle_sha256"] = canonical_sha256(bundle)
    combat = CombatService(ROOT, tmp_path)
    session = combat.persistence.create_match(match_seed="C17-COURT-DODGE", typed_bundles=(owner, foe),
        roster_setup={"primary_actor_ids": [ME, FOE], "team_by_actor": {ME: "team:a", FOE: "team:b"},
            "starting_positions": {ME: {"x": 3, "y": 6}, FOE: {"x": 8 if case == "range" else
                7 if case == "combined" else 5 if case == "reach" else 4, "y": 6}}})
    table = TabletopService(combat, tmp_path)
    if case == "combined":
        state = table.state(session.match_id)
        candidate = next(c for c in session.engine.legal_candidates()
                         if c.display_name == "Calamity Briar Incarnation")
        assert table.act(session.match_id, candidate.candidate_id, state["menu"]["decision_id"],
                         state["menu"]["state_version"], state["last_sequence"])["status"] == "COMMITTED"
        assert table.act(session.match_id, table.state(session.match_id)["menu"]["end_turn"],
                         table.state(session.match_id)["menu"]["decision_id"],
                         table.state(session.match_id)["menu"]["state_version"],
                         table.state(session.match_id)["last_sequence"])["status"] == "COMMITTED"
        while table.state(session.match_id)["menu"]["actor_id"] != ME:
            state = table.state(session.match_id)
            assert table.act(session.match_id, state["menu"]["end_turn"], state["menu"]["decision_id"],
                             state["menu"]["state_version"], state["last_sequence"])["status"] == "COMMITTED"
    if case != "inactive":
        candidate = next(c for c in combat._load_session(session.match_id).engine.legal_candidates()
                         if c.display_name == "Court of One Hundred Forms")
        menu = table.state(session.match_id)["menu"]
        assert table.act(session.match_id, candidate.candidate_id, menu["decision_id"], menu["state_version"], 0)["status"] == "COMMITTED"
    return combat, table, session.match_id


@pytest.mark.parametrize("case", ["use", "auto", "decline", "terminal", "auto_terminal", "extra", "reach", "range", "combined", "inactive", "legacy"])
def test_court_dodge_choice_one_strike_costs_reload_replay(monkeypatch, tmp_path, case):
    install(monkeypatch, "d20_result", lambda *args: {
        "source_id": "test:hit", "operation": "replace", "natural_result": 20})
    combat, table, mid = fight(tmp_path, case)
    engine = combat._load_session(mid).engine
    before = engine.state.model_dump(mode="json")
    owner_before = copy.deepcopy(engine.state.actors[ME])
    sequence = engine.state.event_sequence
    menu = table.state(mid)["menu"]
    candidate = next(c for c in engine.legal_candidates() if c.source_definition_id == "system:combat.dodge")
    args = (mid, candidate.candidate_id, menu["decision_id"], menu["state_version"], 0)
    if case in {"auto", "auto_terminal"}:
        force_ai_candidate(combat, mid, ME, candidate.candidate_id)
        result = table.auto_step(mid, 0)
    else:
        result = table.act(*args)
    answers = []
    if case in {"use", "decline", "terminal", "extra", "reach", "combined"}:
        assert result["status"] == "REACTION_REQUIRED", result
        prompt = result["reaction"]
        assert prompt["context"]["reaction_source_id"] == "choice:needle.iron_court_dodge"
        text = str(prompt)
        assert "Court of One Hundred Forms" in text and "Dodge" in text
        assert "Unarmed Strike" in text and "no additional" in text
        assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
        answers.append({**prompt["context"], "selection": "DECLINE" if case == "decline" else "USE",
                        "option_ids": [] if case == "decline" else [FOE]})
        # Reopen the service while the Dodge transaction is paused.
        combat = CombatService(ROOT, tmp_path)
        table = TabletopService(combat, tmp_path)
        result = table.act(*args, answers)
    # Independent optional Opening follow-ups retain their normal choice transport.
    while result["status"] == "REACTION_REQUIRED":
        answers.append({**result["reaction"]["context"], "selection": "DECLINE", "option_ids": []})
        result = table.act(*args, answers)
    assert result["status"] == "COMMITTED", result
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    owner = loaded.engine.state.actors[ME]
    events = [e for e in loaded.engine.events if e.sequence > sequence]
    strikes = [e for e in events if e.event_type == "ATTACK_ROLLED" and e.actor_id == ME]
    makes_strike = case in {"use", "auto", "terminal", "auto_terminal", "extra", "reach", "combined"}
    assert len(strikes) == int(makes_strike)
    assert any(e.event_type == "DAMAGE_COMMITTED" and FOE in e.target_ids for e in events) == makes_strike
    assert not owner.turn_flags.get("iron_flurry_ready")
    assert owner.resources == owner_before.resources
    assert not owner.action_available and owner.bonus_action_available == owner_before.bonus_action_available
    assert owner.reaction_available == owner_before.reaction_available
    assert owner.movement_remaining_ft == owner_before.movement_remaining_ft
    assert any(c.condition_id == "condition:core.dodge" for c in owner.conditions.values())
    assert (loaded.engine.state.terminal_result is not None) == (case in {"terminal", "auto_terminal"})
    assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"
