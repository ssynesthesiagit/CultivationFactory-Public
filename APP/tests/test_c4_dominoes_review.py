"""Dominoes must remain a separate, Prone-only shove through table replay.

Rider lane C16: Brutal Shove and Dominoes' free shove are the printed Strength (Athletics) contest (combat/ext/brute_shove.py), no
longer attack rolls; the shoved creatures here resist badly (low Athletics/Acrobatics, as foe_ac=0 made the attack hit), the
contest is a CHECK_ROLLED event, and a manual shover is asked "push or Prone" (it pushes here, as the printed choice allows).
"""
import pytest

from tests.r1i_service_support import fixture, candidate, force_ai_candidate, OWNER, FOE, SECOND, THIRD
from tests.test_r1i_round3 import resolve, reload
from tests.test_c4_protection_review import inherited_prompt_loader

BR = "TAL_BRUTE_"
PUSH = {"choice:needle.brutal_shove_result": "push", "choice:needle.brute_contest_skill": "Athletics"}
SHOVER, TARGET = "choice:needle.brutal_shove_result", "choice:needle.brute_contest_skill"


def asked(prompts):
    """The manual shover is asked push-or-Prone; a manual creature shoved may be asked its resisting skill ("The target chooses its
    skill")."""
    return {p["context"]["reaction_source_id"] for p in prompts}


def clumsy(*ids):
    """A bundle transform: these creatures resist a shove badly (Athletics and Acrobatics -50)."""
    from combat.canonical import canonical_sha256

    def transform(bundles):
        for bundle in bundles:
            if bundle["actor_id"] in ids:
                bundle["skills"] = {"Athletics": -50, "Acrobatics": -50}  # the sheet's skill bonuses (factory_compiler "skills")
                bundle.pop("bundle_sha256", None)
                bundle["bundle_sha256"] = canonical_sha256(bundle)
    return transform


def contests(engine, start, who):
    return [e for e in engine.events[start:] if e.event_type == "CHECK_ROLLED" and who in e.target_ids]


@pytest.mark.parametrize("ai_turn", [False, True])
def test_dominoes_one_shove_with_two_colliding_pushes_offers_one_followup(tmp_path, ai_turn):
    """The shove's own push and Court of the Moving Mountain's extra 5 feet both run into the second creature: one Dominoes free
    shove, not two (rider lane C16: the Brutal Shove contest has no attack count; was "distinct parent hits")."""
    combat, table, mid, send, commit = fixture(tmp_path,
        ["BRUTE_BASE_BRUTAL_SHOVE", BR + "DOMINOES", BR + "COURT_OF_THE_MOVING_MOUNTAIN"],
        foe_ac=0, seed="C4-DOMINOES", bundle_transform=clumsy(FOE, SECOND),
        positions={OWNER: {"x": 3, "y": 0}, FOE: {"x": 4, "y": 0}, SECOND: {"x": 5, "y": 0}})
    commit(candidate(table, mid, "Court of the Moving Mountain", OWNER))
    start = len(reload(tmp_path, mid).events)
    cid = candidate(table, mid, "Brutal Shove", FOE)
    if ai_turn:
        force_ai_candidate(combat, mid, OWNER, cid)
    before, prompts = resolve(combat, mid, send, cid, PUSH, auto=ai_turn)
    assert (SHOVER in asked(prompts)) == (not ai_turn)
    engine = reload(tmp_path, mid)
    parents, followups = contests(engine, start, FOE), contests(engine, start, SECOND)
    assert len(parents) == 1 and all(e.payload["success"] for e in parents)
    assert len(followups) == 1 and followups[0].source_definition_id.endswith(".granted.dominoes")
    assert engine.state.actors[SECOND].current_hp == before["actors"][SECOND]["current_hp"]
    assert engine.state.actors[SECOND].position.model_dump(mode="json") == before["actors"][SECOND]["position"]


@pytest.mark.parametrize("state", [None, "COURT_OF_THE_MOVING_MOUNTAIN", "SOVEREIGN_WEIGHT_INCARNATION"])
@pytest.mark.parametrize("ai_turn", [False, True])
@pytest.mark.parametrize("bowling", [False, True])
def test_dominoes_combined_shove_riders_table(tmp_path, state, ai_turn, bowling):
    talents = ["BRUTE_BASE_BRUTAL_SHOVE", BR + "DOMINOES", BR + "BREAK_DEFENSES", BR + "TAKEDOWN"]
    if state:
        talents.append(BR + state)
    if bowling:
        talents.append(BR + "BATTLEFIELD_BOWLING")
    combat, table, mid, send, commit = fixture(tmp_path, talents, foe_ac=0,
        seed="C4-DOMINOES", extra_foe=bowling, bundle_transform=clumsy(FOE, SECOND, THIRD),
        positions={OWNER: {"x": 3, "y": 0}, FOE: {"x": 4, "y": 0},
                   SECOND: {"x": 5, "y": 0}, **({THIRD: {"x": 6, "y": 0}} if bowling else {})})
    if state:
        label = {"COURT_OF_THE_MOVING_MOUNTAIN": "Court of the Moving Mountain",
                 "SOVEREIGN_WEIGHT_INCARNATION": "Sovereign Weight Incarnation"}[state]
        commit(candidate(table, mid, label, OWNER))
    start = len(reload(tmp_path, mid).events)
    cid = candidate(table, mid, "Brutal Shove + Takedown", FOE)
    if ai_turn:
        force_ai_candidate(combat, mid, OWNER, cid)
    before, prompts = resolve(combat, mid, send, cid, PUSH, auto=ai_turn)
    assert (SHOVER in asked(prompts)) == (not ai_turn)
    engine = reload(tmp_path, mid)
    for who in [SECOND, *([THIRD] if bowling else [])]:
        subject = engine.state.actors[who]
        assert subject.position.model_dump(mode="json") == before["actors"][who]["position"]
        assert subject.current_hp == before["actors"][who]["current_hp"]
        assert {c.condition_id for c in subject.conditions.values()} == {"condition:typed.prone"}
        assert not subject.modifiers  # Break Defenses must not attach to the free shove.
        shoves = contests(engine, start, who)
        assert len(shoves) == 1 and shoves[0].payload["success"]
        assert shoves[0].source_definition_id.endswith(".granted.dominoes")
        assert not any(e.event_type == "DAMAGE_COMMITTED" and who in e.target_ids for e in engine.events)


@pytest.mark.parametrize("ai_turn", [False, True])
def test_dominoes_crushing_choice_commit_reload_keeps_hammer_damage_separate(tmp_path, ai_turn):
    talents = ["BRUTE_BASE_BRUTAL_SHOVE", BR + "DOMINOES", BR + "HAMMER",
               BR + "CRUSHING_COLLISION", BR + "COURT_OF_THE_MOVING_MOUNTAIN", BR + "BREAK_DEFENSES"]
    combat, table, mid, send, commit = fixture(tmp_path, talents, foe_ac=0, seed="C4-DOMINOES", bundle_transform=clumsy(FOE, SECOND),
        positions={OWNER: {"x": 3, "y": 0}, FOE: {"x": 4, "y": 0}, SECOND: {"x": 5, "y": 0}})
    commit(candidate(table, mid, "Court of the Moving Mountain", OWNER))
    cid = candidate(table, mid, "Brutal Shove", FOE)
    if ai_turn:
        force_ai_candidate(combat, mid, OWNER, cid)
    before, prompts = resolve(combat, mid, send, cid, {"choice:needle.brute_crushing": "dazed", **PUSH}, auto=ai_turn)
    assert (SHOVER in asked(prompts)) == (not ai_turn)
    if not ai_turn:
        assert any("Crushing Collision" in str(prompt) for prompt in prompts)
    engine = reload(tmp_path, mid)
    subject = engine.state.actors[SECOND]
    assert subject.position.model_dump(mode="json") == before["actors"][SECOND]["position"]
    assert {c.condition_id for c in subject.conditions.values()} == {"condition:typed.prone"}
    assert not subject.modifiers
    # Original push effects can each collide; only Hammer may damage the
    # secondary creature, and the free shove adds zero damage.
    damage = [e for e in engine.events if e.event_type == "DAMAGE_COMMITTED" and SECOND in e.target_ids]
    rolls = [r for r in engine.rolls if r.reason == "HAMMER_IMPACT_COLLISION"]
    assert len(damage) == len(rolls) and damage
    assert all("BRUTE_BASE_BRUTAL_SHOVE" in e.source_definition_id for e in damage)
    assert before["actors"][SECOND]["current_hp"] - subject.current_hp == sum(r.total for r in rolls)
