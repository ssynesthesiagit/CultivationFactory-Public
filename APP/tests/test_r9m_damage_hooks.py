"""Integration: the shared damage-roll hook carries every owner's context once.

The round19 and lane9 contracts previously accepted incompatible argument
counts. These controls combine real compiled abilities, and retain table
commit/reload coverage for the once-per-roll Bitter Dregs contribution.
"""
import pytest

from combat.ext import fate_riders as fate
from tests import test_riders_lane3 as alchemy


@pytest.mark.parametrize("wheel_bonus", [0, 2])
def test_bitter_area_and_turning_wheel_share_one_damage_roll(wheel_bonus):
    engine = alchemy._bitter_arena(extra=True)
    actor = engine.state.actors[alchemy.ME]
    if wheel_bonus:
        # Evented fixture prerequisite: a previously granted ally Auspice.
        engine._apply_condition(actor, fate.WHEEL, fate.WHEEL_ID, alchemy.ME,
                                expires_on="UNTIL_REMOVED",
                                data={"kind": "attack", "bonus": wheel_bonus, "face": 2})
    foe = engine.state.actors[alchemy.H.FOE]
    other = engine.state.actors[alchemy.F2]
    hp = [foe.current_hp, other.current_hp]
    events = alchemy._act(engine, alchemy.ME, "Field Formula: Numbing Smoke + Bitter Dregs",
                          destination=foe.position)
    rolls = alchemy.H._payloads(events, "DAMAGE_ROLLED")
    assert len(rolls) == 1
    assert rolls[0]["modifier"] == 3 + 4 + wheel_bonus
    assert [old - target.current_hp for old, target in zip(hp, [foe, other])] == [rolls[0]["total"]] * 2
    assert actor.resources[alchemy.DREG] == 1
    assert not getattr(engine, "_ext_failures_logged", set())


def test_force_mantle_and_turning_wheel_keep_their_separate_roll_limits():
    from combat import typed_executor as X
    from tests import test_auto_lane4 as dice_script
    from tests.test_riders_lane10 import SWF, F

    _, engine, actor, foe = SWF.fight(F + "FORCE_MANTLE", extras=(F + "IMPACT",))
    SWF.cast(engine, "Force Mantle")
    engine._apply_condition(actor, fate.WHEEL, fate.WHEEL_ID, actor.entity_id,
                            expires_on="UNTIL_REMOVED", data={"kind": "attack", "bonus": 2, "face": 2})
    action = next(a for a in engine.action_catalog.values()
                  if a.owner_id == actor.entity_id and a.display_name == "Impact")
    ctx = X.Context(engine, actor, action, None, action.parameters["typed"], [foe], foe)
    # Damage-effect vocabulary fixture isolates the non-weapon Force roll seam.
    # Actual Impact attacks remain covered by the lane10 tests.
    first = {"type": "damage", "dice": {"count": 1, "sides": 8}, "damage_types": ["force"]}
    second = {**first}
    dice_script._script(engine, [3, 4])
    assert X._damage_roll(ctx, first) == (3 + actor.proficiency_bonus + 2, "FORCE")
    assert X._damage_roll(ctx, first) == (3 + actor.proficiency_bonus + 2, "FORCE")
    assert X._damage_roll(ctx, second) == (4 + 2, "FORCE")
    assert len(SWF.rolls(engine, "DAMAGE")) == 2
    assert not getattr(engine, "_ext_failures_logged", set())


def test_bitter_table_damage_bonus_survives_commit_and_reload(tmp_path):
    from combat.gate4_persistence import Gate4Persistence
    from combat.canonical import canonical_sha256

    H = alchemy.H
    bundles = tuple(alchemy.compile_character(H._sheet("tianxia.sphere.alchemy",
        [alchemy.BITTER, "TAL_ALCHEMY_BINDING_DREGS"] if actor_id == alchemy.ME else [],
        H.AXE_KIT, dc=alchemy.FAIL, cl=10), actor_id=actor_id)
        for actor_id in (alchemy.ME, H.FOE))
    persistence = Gate4Persistence(H.ROOT, tmp_path / "damage-contract-table")
    session = persistence.create_match(match_seed="a", typed_bundles=bundles,
        roster_setup={"primary_actor_ids": [alchemy.ME, H.FOE],
                      "team_by_actor": {alchemy.ME: "team:a", H.FOE: "team:b"}},
        genesis_setup={alchemy.ME: {"placement": {"x": 3, "y": 6},
                                  "resources": {alchemy.DREG: 2, alchemy.STOCK: 0}},
                       H.FOE: {"placement": {"x": 4, "y": 6}}})

    def submit(candidate):
        session.submit_intent(H.ActionIntent(intent_id=f"damage-contract-{session.engine.state.event_sequence}",
            decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
            state_version=candidate.state_version, actor_id=candidate.actor_id,
            target_ids=candidate.target_ids, destination=candidate.destination),
            primary_decision_record=None, reaction_provider=None)

    while session.engine.state.current_actor_id != alchemy.ME:
        submit(next(c for c in session.engine.legal_candidates()
                    if str(getattr(c.kind, "value", c.kind)) == "END_TURN"))
    start = len(session.engine.events)
    before_hp = session.engine.state.actors[H.FOE].current_hp
    position = session.engine.state.actors[H.FOE].position
    submit(next(c for c in session.engine.legal_candidates()
                if c.display_name.startswith("Field Formula: Numbing Smoke + Bitter Dregs at ")
                and c.destination == position))
    damage = H._payloads(session.engine.events[start:], "DAMAGE_ROLLED")
    assert len(damage) == 1 and damage[0]["modifier"] == 7
    assert before_hp - session.engine.state.actors[H.FOE].current_hp == damage[0]["total"]
    digest = canonical_sha256(session.engine.state.model_dump(mode="json"))
    loaded = persistence.load_match(session.match_id)
    assert canonical_sha256(loaded.engine.state.model_dump(mode="json")) == digest
    assert loaded.engine.state.actors[alchemy.ME].resources[alchemy.DREG] == 1
    assert H._payloads(loaded.engine.events[start:], "DAMAGE_ROLLED") == damage
