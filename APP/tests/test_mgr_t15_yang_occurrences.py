"""Yang review regressions: real table choices, committed benefits and cold replay.

Synthetic setup actions install the printed benefits; they do not depend on
private rule prose to classify a death trigger on the public test export.
"""
import pytest

from combat.canonical import canonical_sha256
from combat.ext.yang_sun_marks import DAWN, LIFE, MANTLE, FORCE, KINDLE, EXCEPTION
from combat.ext.yang_recovery import ROUND
from combat.typed_executor import bears_mark
from combat.posture import prone_conditions
from tests.worker2_support import (
    OWNER, ALLY, FOE, fixture, candidate, settle, turn, reload, sealed_native_attack,
)


def benefit_setup(source, *, prone=False, attack_bonus=100, count=1):
    def transform(bundles):
        bundle = bundles[0]
        action = next(a for a in bundle["action_catalog"] if a["source_definition_id"].endswith(KINDLE))
        effects = action["parameters"]["typed"]["effects"]
        if prone:
            effects.append({"type": "condition", "condition": "prone", "applies_to": "target"})
            effects.append({"type": "yang_immediate_stand"})
        effects.append({"type": "yang_completion_exception", "source": source, "applies_to": "ally"})
        # Synthetic occupied round slot is installed as part of the same real action.
        # Passive turn flags are not arbitrary persisted objects.
        bundle.pop("bundle_sha256", None)
        bundle["bundle_sha256"] = canonical_sha256(bundle)
        sealed_native_attack(bundles[1], "Review strike", attack_bonus=attack_bonus,
                             count=0, sides=6, modifier=count, attacks=2)
        # Explicit public mechanical row, retaining the real Mantle compiler transform.
        from combat.ext.yang_sun_marks import force_mantle_damage
        row = {"feature_id": FORCE, "kind": "hit", "numbers": {"cl": 15, "key_mod": 2},
               "effects": [{"type": "spend_mark", "mark": "Kindled Mark"},
                           {"type": "damage", "dice": {"count": 3, "sides": 6},
                            "formula": "key_ability_modifier"}]}
        if any(r["effects"] and any(e.get("type") == "yang_completion_damage" for e in r["effects"])
               for r in bundle["typed_reactions"] if r["feature_id"] == FORCE):
            row = force_mantle_damage(row, {"owned_ids": [MANTLE]})
        bundle["typed_reactions"] = [r for r in bundle["typed_reactions"] if r["feature_id"] != FORCE] + [row]
        bundle.pop("bundle_sha256", None)
        bundle["bundle_sha256"] = canonical_sha256(bundle)
    return transform


@pytest.mark.parametrize("recipient", [ALLY, FOE])
@pytest.mark.parametrize("answer", ["accept", "refuse"])
def test_mantle_link_requires_recipient_consent_and_includes_other_teams(tmp_path, recipient, answer):
    combat, table, mid = fixture(tmp_path, [MANTLE], named=True, positions={
        OWNER: {"x": 3, "y": 6}, ALLY: {"x": 4, "y": 6}, FOE: {"x": 5, "y": 6}})
    settle(table, mid, candidate(combat, mid, "Completing Flame Mantle").candidate_id)
    turn(table, mid, ALLY)
    turn(table, mid, OWNER)
    prompts = settle(table, mid, candidate(combat, mid, "Kindle the Rising", target=OWNER).candidate_id,
                     picks={"choice:needle.mantle_link": recipient, "choice:willing.consent": answer})
    consent = [p for p in prompts if p["context"]["reaction_source_id"] == "choice:willing.consent"]
    assert consent and consent[0]["context"]["reactor_id"] == recipient
    engine = reload(tmp_path, mid)
    assert bears_mark(engine.state.actors[recipient], OWNER, "Kindled Mark") is (answer == "accept")
    assert not bears_mark(engine.state.actors[recipient], OWNER, "Overkindled Mark")


@pytest.mark.parametrize("stand", [True, False])
def test_dawn_optional_stand_is_the_recipients_table_choice(tmp_path, stand):
    combat, table, mid = fixture(tmp_path, [DAWN], named=True,
                                bundle_transform=benefit_setup(DAWN, prone=True))
    prompts = settle(table, mid, candidate(combat, mid, "Kindle the Rising", target=ALLY).candidate_id,
                     picks={"choice:needle.dawn_stand": "stand" if stand else None})
    chosen = [p for p in prompts if p["context"]["reaction_source_id"] == "choice:needle.dawn_stand"]
    assert chosen and chosen[0]["context"]["reactor_id"] == ALLY
    assert bool(prone_conditions(reload(tmp_path, mid).state.actors[ALLY])) is not stand


@pytest.mark.parametrize("source", [LIFE, DAWN])
@pytest.mark.parametrize("accept", [True, False])
@pytest.mark.parametrize("mantle", [True, False])
def test_first_occurrence_dispatches_real_force_once(tmp_path, source, accept, mantle):
    combat, table, mid = fixture(tmp_path, [source, *([MANTLE] if mantle else [])],
                                bundle_transform=benefit_setup(source), named=True,
                                positions={OWNER: {"x": 3, "y": 6}, ALLY: {"x": 4, "y": 6}, FOE: {"x": 5, "y": 6}})
    settle(table, mid, candidate(combat, mid, "Kindle the Rising", target=ALLY).candidate_id)
    turn(table, mid, ALLY)
    prompts = settle(table, mid, candidate(combat, mid, "Review strike", target=FOE).candidate_id,
                     picks={"choice:needle.yang_aim_attack": None,
                            "choice:needle.completion_force": "force" if accept else None})
    choices = [p for p in prompts if p["context"]["reaction_source_id"] == "choice:needle.completion_force"]
    assert len(choices) == 1  # declining the first occurrence never offers the second hit
    engine = reload(tmp_path, mid)
    ally, owner = engine.state.actors[ALLY], engine.state.actors[OWNER]
    assert not any(c.condition_id == EXCEPTION for c in ally.conditions.values())
    assert bears_mark(ally, OWNER, "Kindled Mark") is not accept
    bonus = [e for e in engine.events if e.event_type == "DAMAGE_COMMITTED"
             and e.source_definition_id == FORCE]
    assert bool(bonus) is accept
    assert owner.turn_flags.get(ROUND) != engine.state.round_number


def test_life_ignores_a_non_damaging_hit_then_answers_nonattack_damage(tmp_path):
    from combat.ext import states
    from combat.typed_executor import run_effects

    combat, table, mid = fixture(tmp_path, [LIFE, MANTLE], bundle_transform=benefit_setup(LIFE, count=0),
                                positions={OWNER: {"x": 3, "y": 6}, ALLY: {"x": 4, "y": 6}, FOE: {"x": 5, "y": 6}})
    settle(table, mid, candidate(combat, mid, "Kindle the Rising", target=ALLY).candidate_id)
    turn(table, mid, ALLY)
    settle(table, mid, candidate(combat, mid, "Review strike", target=FOE).candidate_id,
           picks={"choice:needle.yang_aim_attack": None})
    engine = reload(tmp_path, mid)
    ally, foe = engine.state.actors[ALLY], engine.state.actors[FOE]
    assert any(c.condition_id == EXCEPTION for c in ally.conditions.values())
    # Non-attack typed packet, not the confirmed-hit helper.
    engine._active_intent = None
    ctx = states.context(engine, ally, "test:save_damage", [foe])
    run_effects(ctx, [{"type": "damage", "amount": 1, "applies_to": "target"}])
    assert not any(c.condition_id == EXCEPTION for c in ally.conditions.values())
    assert not bears_mark(ally, OWNER, "Kindled Mark")
    assert any(e.event_type == "DAMAGE_COMMITTED" and e.source_definition_id == FORCE for e in engine.events)


def test_dawn_miss_never_offers_or_pays_exception_aim(tmp_path, monkeypatch):
    from combat.ext import states, yang_recovery

    combat, table, mid = fixture(tmp_path, [DAWN], bundle_transform=benefit_setup(DAWN, attack_bonus=-100),
                                positions={OWNER: {"x": 3, "y": 6}, ALLY: {"x": 4, "y": 6}, FOE: {"x": 5, "y": 6}})
    settle(table, mid, candidate(combat, mid, "Kindle the Rising", target=ALLY).candidate_id)
    turn(table, mid, ALLY)
    engine = reload(tmp_path, mid)
    owner, ally, foe = (engine.state.actors[a] for a in (OWNER, ALLY, FOE))
    owner.turn_flags[ROUND] = engine.state.round_number
    def no_choice(*args, **kwargs):
        pytest.fail("occupied-slot Dawn Aim was offered before a qualifying hit/save")
    monkeypatch.setattr(yang_recovery.family, "choose", no_choice)
    assert yang_recovery._aim(states.context(engine, ally, "test:miss", [foe]), ally, target=foe) is None
    assert bears_mark(ally, OWNER, "Kindled Mark")
    assert any(c.condition_id == EXCEPTION for c in ally.conditions.values())
