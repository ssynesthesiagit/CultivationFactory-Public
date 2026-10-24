"""Hunt 74 service regressions: ally bookkeeping and player-owned hostile answers.

AI cases run auto_step with the existing fixture's scripted controller adapter:
the service chooses, previews, pauses and commits a deterministic hostile action.
They test controller integration, not the stock AI's preference for that action.
"""
import pytest

from combat.gate5_service import CombatService
from tests.h1_support import ROOT
from tests.r1i_service_support import fixture, candidate, force_ai_candidate, OWNER, FOE, SECOND
from tests.test_hunt74_support import REFLECTION, HEAL, PRISON_BARS, LIGHTNING_GOD_BODY

STITCH = "tianxia.talent.thread.surgeon_s_stitch"
CM = "TAL_LIGHTNING_CHARGED_COUNTERMEASURE"


def _until(table, mid, commit, actor):
    while table.state(mid)["menu"]["actor_id"] != actor:
        commit(table.state(mid)["menu"]["end_turn"])


def test_ally_stitch_heals_and_records_use_without_spending_recipients_reaction(tmp_path):
    combat, table, mid, send, commit = fixture(tmp_path, [REFLECTION, HEAL],
        foe_talents=[STITCH], allies=[FOE], seed="SOL84-STITCH")
    _until(table, mid, commit, FOE)
    # Healing Talisman/Surgeon's Stitch already own their support implementations.
    # This setup only changes initial HP; the support, mark and persistence are real.
    session = combat._load_session(mid)
    owner = session.engine.state.actors[OWNER]
    owner.current_hp = 250
    before = dict(owner.resources)
    result = send(candidate(table, mid, "Surgeon", OWNER))
    assert result["status"] == "COMMITTED", "beneficial stitching must not ask for a hostile response"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid).engine
    owner = loaded.state.actors[OWNER]
    assert owner.current_hp > 250
    assert owner.resources == before and owner.reaction_available
    assert any("surgeon" in c.condition_id.lower() for c in owner.conditions.values())
    assert not any(e.source_definition_id == REFLECTION and e.event_type == "REACTION_WINDOW_OPENED"
                   for e in loaded.events)


@pytest.mark.parametrize("auto_turn", [False, True])
@pytest.mark.parametrize("selection", ["USE", "DECLINE"])
@pytest.mark.parametrize("answer", ["reflection", "countermeasure"])
def test_hostile_ask_me_use_decline_on_manual_and_controller_turns(tmp_path, auto_turn, selection, answer):
    combat, table, mid, send, commit = fixture(tmp_path, [REFLECTION, HEAL],
        foe_talents=[PRISON_BARS], second_talents=[CM] if answer == "countermeasure" else (),
        seed="SOL84-HOSTILE", owner_dc=50)
    _until(table, mid, commit, FOE)
    # The service enforces Prison Bars' Charge prerequisite. Lash: Jolt is a
    # legal hostile supernatural attack without setup and triggers the same row.
    cid = candidate(table, mid, "Lightning Lash: Jolt", OWNER)
    if auto_turn:
        force_ai_candidate(combat, mid, FOE, cid)
    engine = combat._load_session(mid).engine
    before = engine.state.model_dump(mode="json")
    reactor = SECOND if answer == "countermeasure" else OWNER
    source = CM if answer == "countermeasure" else REFLECTION
    answers, prompts = [], []
    for _ in range(12):
        result = send(cid, answers, auto=auto_turn)
        if result["status"] == "COMMITTED":
            break
        assert result["status"] == "REACTION_REQUIRED", result
        prompt = result["reaction"]
        prompts.append(prompt)
        assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
        assert send(cid, answers, auto=auto_turn)["reaction"] == prompt
        context = prompt["context"]
        picked = selection if context["reaction_source_id"].endswith(source) else "USE"
        answers.append({**context, "selection": picked})
    assert result["status"] == "COMMITTED", result
    asked = [p for p in prompts if p["context"]["reaction_source_id"].endswith(source)]
    assert len(asked) == 1
    prompt = asked[0]
    assert prompt["context"]["reactor_id"] == reactor
    assert ("Charged Countermeasure" if answer == "countermeasure" else "Talisman Reflection") in prompt["reaction"]
    text = str(prompt)
    assert "Owner" in text
    assert ("Talisman Reflection" if answer == "countermeasure" else "Lightning Lash") in text
    loaded = CombatService(ROOT, tmp_path)._load_session(mid).engine
    actor = loaded.state.actors[reactor]
    qi = "resource:core.qi"
    assert actor.resources[qi] == before["actors"][reactor]["resources"][qi] - (
        (1 if answer == "countermeasure" else 5) if selection == "USE" else 0)
    assert actor.reaction_available == (selection == "DECLINE")
    resolved = [e for e in loaded.events if e.event_type == "REACTION_RESOLVED" and e.source_definition_id == source]
    assert bool(resolved) == (selection == "USE")
    if answer == "countermeasure":
        assert any(e.event_type == "SAVE_ROLLED" and e.source_definition_id == CM for e in loaded.events) == (selection == "USE")
    if answer == "reflection":
        prepared = "resource:named.prepared_talismans"
        assert actor.resources[prepared] == before["actors"][reactor]["resources"][prepared] - (selection == "USE")


def test_live_buff_restraint_survives_service_commit_and_reload(tmp_path):
    from combat.gate4_context import build_decision_context
    combat, table, mid, send, commit = fixture(tmp_path, [LIGHTNING_GOD_BODY], seed="SOL84-BUFF")
    commit(candidate(table, mid, "Lightning-God Body"))
    commit(table.state(mid)["menu"]["end_turn"])
    _until(table, mid, commit, OWNER)
    loaded = CombatService(ROOT, tmp_path)._load_session(mid).engine
    policy = combat.policies.for_actor(OWNER)[0]
    assert loaded.state.actors[OWNER].conditions and loaded.state.actors[OWNER].modifiers
    assert not any(c.source_definition_id == LIGHTNING_GOD_BODY
                   for c in build_decision_context(loaded, policy, for_ai=True).legal_candidates)
