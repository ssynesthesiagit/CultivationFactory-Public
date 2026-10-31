"""Defensive Discipline ownership and lifetime through real table commits/reloads."""
import pytest

from combat.canonical import canonical_sha256
from combat.ext import defensive_disciplines as disciplines
from combat.gate2_rolls import DeterministicRollAuthority
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, ME, FOE, bundle
from tests.r1i_service_support import force_ai_candidate
from tests.test_auto3_foundations import TEMPERED, CULTIVATED

BLAST = "Scripture Prison"


def fixture(tmp_path, monkeypatch, *, feature=TEMPERED, primary="Stamina"):
    def die(roller, sides):
        counter = roller.counter
        roller.counter += 1
        return min(10, sides), counter

    monkeypatch.setattr(DeterministicRollAuthority, "_die", die)
    defender = bundle([feature], primary=primary)
    defender["actor_template"].update(display_name="Defender", initiative_bonus=-1000, maximum_hp=500)
    defender.pop("bundle_sha256", None)
    defender["bundle_sha256"] = canonical_sha256(defender)
    attacker = bundle(["tianxia.talent.ink.scripture_prison"], actor_id=FOE, dc=14)
    attacker["actor_template"].update(display_name="Ink caster", initiative_bonus=1000, maximum_hp=500)
    attacker.pop("bundle_sha256", None)
    attacker["bundle_sha256"] = canonical_sha256(attacker)
    combat = CombatService(ROOT, tmp_path)
    session = combat.persistence.create_match(match_seed="SPH-foundations-r1", typed_bundles=(defender, attacker),
        roster_setup={"primary_actor_ids": [ME, FOE], "team_by_actor": {ME: "team:a", FOE: "team:b"},
                      "starting_positions": {ME: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}}})
    mid = session.match_id
    combat._read_metadata(mid, session)
    for actor in (ME, FOE):
        combat.set_controller_mode(mid, actor_id=actor, controller_mode="MANUAL")
    table = TabletopService(combat, tmp_path)
    assert table.state(mid)["menu"]["actor_id"] == FOE
    assert not any(row.get("ask") for row in session.engine.typed_reaction_rows[ME])
    return combat, table, mid


def reload(tmp_path, mid):
    combat = CombatService(ROOT, tmp_path)
    session = combat._load_session(mid)
    assert session.mechanical.replay()["status"] == "PASS"
    return combat, TabletopService(combat, tmp_path), session.engine


def act(combat, table, mid, cid, answers=(), *, auto=False):
    if auto:
        return table.auto_step(mid, 0, list(answers))
    menu = table.state(mid)["menu"]
    return table.act(mid, cid, menu["decision_id"], menu["state_version"], 0, list(answers))


@pytest.mark.parametrize("auto", [False, True], ids=["player-turn", "AI-turn"])
def test_manual_auto_reaction_owner_keeps_discipline_after_turn_and_reload(tmp_path, monkeypatch, auto):
    combat, table, mid = fixture(tmp_path, monkeypatch)
    cid = next(c["candidate_id"] for c in combat.decision(mid)["context"]["legal_candidates"]
               if c["display_name"] == BLAST and ME in c["target_ids"])
    if auto:
        force_ai_candidate(combat, mid, FOE, cid)
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    result = act(combat, table, mid, cid, auto=auto)
    assert result["status"] == "REACTION_REQUIRED", result
    prompt = result["reaction"]
    assert prompt["context"]["reactor_id"] == ME
    assert {o["id"] for o in prompt["choice"]["options"]} == {"STR", "DEX", "CON"}
    assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
    answer = {**prompt["context"], "selection": "USE", "option_ids": ["DEX"]}
    # Reopen the service during the pause. Gate 5 owns reaction routing throughout.
    fresh = CombatService(ROOT, tmp_path)
    if auto:
        fresh.controller = combat.controller
    combat, table = fresh, TabletopService(fresh, tmp_path)
    result = act(combat, table, mid, cid, [answer], auto=auto)
    assert result["status"] == "COMMITTED", result
    combat, table, engine = reload(tmp_path, mid)
    assert disciplines.chosen(engine, engine.state.actors[ME], TEMPERED) == "DEX"
    assert engine.state.actors[ME].resources["resource:core.stamina"] == 29
    for actor in (FOE, ME):
        combat.set_controller_mode(mid, actor_id=actor, controller_mode="MANUAL")
    # End the attacker's turn, crossing the owner's start; commit/reload again.
    assert act(combat, table, mid, table.state(mid)["menu"]["end_turn"])["status"] == "COMMITTED"
    combat, table, engine = reload(tmp_path, mid)
    assert engine.state.current_actor_id == ME
    assert disciplines.chosen(engine, engine.state.actors[ME], TEMPERED) == "DEX"
    assert act(combat, table, mid, table.state(mid)["menu"]["end_turn"])["status"] == "COMMITTED"
    cid = next(c["candidate_id"] for c in combat.decision(mid)["context"]["legal_candidates"]
               if c["display_name"] == BLAST and ME in c["target_ids"])
    assert act(combat, table, mid, cid)["status"] == "COMMITTED"  # no second discipline prompt
    _, _, engine = reload(tmp_path, mid)
    assert disciplines.chosen(engine, engine.state.actors[ME], TEMPERED) == "DEX"
    assert len([c for c in engine.state.actors[ME].conditions.values() if c.condition_id == disciplines.RECORD]) == 1


def test_no_provider_preserves_default_without_recording_a_choice():
    from tests.test_auto3_foundations import _table, _blast

    engine, asked = _table(TEMPERED)
    engine.set_reaction_provider(None)
    before = len(engine.events)
    _blast(engine)
    assert not asked
    assert disciplines.chosen(engine, engine.state.actors[ME], TEMPERED) is None
    assert not [e for e in engine.events[before:] if e.payload.get("trigger") == "Defensive Discipline chosen"]


def test_proficiency_limitation_remains_visible():
    from tests.test_auto3_foundations import _gm_lines

    assert any("does not stack" in line and "proficiency" in line for line in _gm_lines(TEMPERED))


def test_additional_discipline_limitation_remains_visible():
    from tests.test_auto3_foundations import _gm_lines, NASCENT_SOUL

    assert any("not asked for yet" in line for line in _gm_lines(NASCENT_SOUL))


@pytest.mark.parametrize("feature,primary,name,uses_reaction", [
    (TEMPERED, "Stamina", "Tempered Response", False),
    (CULTIVATED, "Qi", "Cultivated Response", True),
])
def test_rendered_prompt_names_ability_trigger_creature_cost_and_limit(
        tmp_path, monkeypatch, feature, primary, name, uses_reaction):
    combat, table, mid = fixture(tmp_path, monkeypatch, feature=feature, primary=primary)
    cid = next(c["candidate_id"] for c in combat.decision(mid)["context"]["legal_candidates"]
               if c["display_name"] == BLAST and ME in c["target_ids"])
    result = act(combat, table, mid, cid)
    assert result["status"] == "REACTION_REQUIRED"
    prompt = result["reaction"]
    text = prompt["moment"]  # the sentence the table actually displays, not transport metadata
    assert prompt["reaction"] == name and prompt["action"] == BLAST
    assert prompt["affected"] == "Defender" and prompt["trigger_actor"] == "Ink caster"
    assert name in text and BLAST in text
    assert f"1 {primary}" in text and "cultivation energy" in text and "once per round" in text
    assert "costs no action or resource" in text and "for this fight" in text
    assert ("also uses your Reaction" if uses_reaction else "uses no action") in text
    assert combat._load_session(mid).engine.state.actors[ME].display_name in text
    answer = {**prompt["context"], "selection": "USE", "option_ids": ["DEX"]}
    # Table actions commit through session.mechanical.execute_intent, not the bare engine.
    assert act(combat, table, mid, cid, [answer])["status"] == "COMMITTED"
    _, _, engine = reload(tmp_path, mid)
    defender = engine.state.actors[ME]
    assert disciplines.chosen(engine, defender, feature) == "DEX"
    assert defender.resources[f"resource:core.{primary.lower()}"] == 29
    # Scripture Prison itself prevents Reactions on a successful save; final
    # availability cannot distinguish the response's action cost in this fixture.


def test_ai_owner_decides_automatically_and_keeps_choice_after_reload(tmp_path, monkeypatch):
    combat, table, mid = fixture(tmp_path, monkeypatch)
    combat.set_controller_mode(mid, actor_id=ME, controller_mode="LOCAL_AUTO")
    cid = next(c["candidate_id"] for c in combat.decision(mid)["context"]["legal_candidates"]
               if c["display_name"] == BLAST and ME in c["target_ids"])
    assert act(combat, table, mid, cid)["status"] == "COMMITTED"
    _, _, engine = reload(tmp_path, mid)
    assert disciplines.chosen(engine, engine.state.actors[ME], TEMPERED) == "CON"


def test_nonowner_has_no_discipline_question_or_record_in_service(tmp_path, monkeypatch):
    combat, table, mid = fixture(tmp_path, monkeypatch, feature="tianxia.path.body_refining.feature.iron_fist")
    cid = next(c["candidate_id"] for c in combat.decision(mid)["context"]["legal_candidates"]
               if c["display_name"] == BLAST and ME in c["target_ids"])
    assert act(combat, table, mid, cid)["status"] == "COMMITTED"
    _, _, engine = reload(tmp_path, mid)
    assert not [c for c in engine.state.actors[ME].conditions.values() if c.condition_id == disciplines.RECORD]
