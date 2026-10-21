"""Pulse Thread Memory through table choices, committed damage and cold reload.

Synthetic free actions only seal, wound, heal and supply Temporary HP. Real
Read the Pulse is compiled from the owner's Life sphere and printed authority.
Finite-cap fixtures seal a represented cap; current ordinary seals are uncapped.
"""
import json
from pathlib import Path

import pytest

from combat.ext.pulse_thread_memory import FEATURE, CHOICE
from combat.ext.mind_hidden_eye import LEARNED
from combat.history_feed import concealed_condition_instances
from combat.typed_executor import bears_mark
from tests.auto_worker1_support import LEFT, RIGHT, ALLY, act, action_sender, fight, reload, resolve, turn


def test_native_capacity_fixture_has_its_source_feature_mapping():
    """The compiler loads this file dynamically; keep it in public snapshots."""
    root = Path(__file__).resolve().parents[1]
    blocks = json.loads((root / "combat/rules/feature_blocks.d/insights7.json").read_text())
    assert blocks["features"][FEATURE]["block"] == "pulse_thread_memory"


def fixture(tmp_path, *, owns=True, damage=7, cap=None, reaction_ask=True):
    def sheet_edit(doc, aid):
        if aid == LEFT:
            doc["spheres_and_talents"]["cultivation_insight_record_ids"] = [FEATURE] if owns else []
    def bundle_edit(bundle):
        if cap is not None and bundle["actor_id"] == LEFT:
            next(row for row in bundle["typed_passives"] if row["block"] == "mark_caps")["caps"]["pulse seal"] = cap
    extras = [("Seal", {"target_kind": "ANY_CREATURE", "effects": [
        {"type": "mark", "mark": "Pulse Seal", "applies_to": "target", "duration": {"kind": "until_removed"}}]}),
        ("Heal", {"target_kind": "ANY_CREATURE", "effects": [
        {"type": "healing", "flat": 100, "applies_to": "target"}]}),
        ("Ward", {"target_kind": "ANY_CREATURE", "effects": [
        {"type": "temp_hp", "flat": 20, "applies_to": "target"}]})]
    combat, table, mid = fight(tmp_path, ["LIFE_BASE_READ_THE_PULSE"], spheres=["tianxia.sphere.life"], sheet_edit=sheet_edit,
        bundle_edit=bundle_edit, extra_actions=extras, ally=True, maximum_rounds=15,
        cause=[{"type": "damage", "flat": damage, "applies_to": "target", "damage_types": ["force"]}],
        cause_target="ANY_CREATURE", reaction_ask=reaction_ask)
    return combat, table, mid


def send(combat, table, mid, label, target=ALLY, *, ai=False, picks=None):
    controller = combat.controller
    try:
        return resolve(action_sender(combat, table, mid, label, target_id=target, ai=ai), picks)
    finally:
        if ai:
            combat.controller = controller
            combat.set_controller_mode(mid, actor_id=LEFT, controller_mode="MANUAL")


def fresh(combat, mid):
    engine = reload(combat, mid)
    session = combat._load_session(mid)
    assert session.verify()["status"] == "PASS"
    assert session.mechanical.replay()["status"] == "PASS"
    return engine


def readings(engine):
    return [condition for condition in engine.state.actors[ALLY].conditions.values()
            if condition.source_definition_id == FEATURE and condition.condition_id == LEARNED]


@pytest.mark.parametrize("ai", [False, True])
@pytest.mark.parametrize("hurt", [False, True])
def test_reading_is_optional_yes_no_and_survives_healing_and_cold_reload(tmp_path, ai, hurt):
    combat, table, mid = fixture(tmp_path, reaction_ask=not ai)
    send(combat, table, mid, "Seal")
    turn(table, mid, RIGHT)
    if hurt:
        resolve(lambda answers: act(table, mid, "Cause", answers, target_id=ALLY))
    turn(table, mid, LEFT)
    send(combat, table, mid, "Heal")
    assert fresh(combat, mid).state.actors[ALLY].current_hp == 1000
    before = fresh(combat, mid).state.actors[LEFT].resources["resource:core.qi"]
    _, prompts = send(combat, table, mid, "Read the Pulse", ai=ai)
    entries = readings(fresh(combat, mid))
    assert len(entries) == 1
    assert entries[0].data["value"] == ("Took damage" if hurt else "Took no damage")
    assert entries[0].source_actor_id == LEFT
    assert fresh(combat, mid).state.actors[LEFT].resources["resource:core.qi"] == before
    engine = fresh(combat, mid)
    assert entries[0].instance_id in concealed_condition_instances(engine.state.model_dump(mode="json"))
    assert not any(event.source_definition_id == FEATURE and event.payload.get("log")
                   for event in engine.events)
    if not ai:
        assert any(p["context"]["reaction_source_id"] == CHOICE for p in prompts)
        assert "Pulse-Thread Memory" in str(prompts) and "Read the Pulse" in str(prompts)
        result = next(p for p in prompts if p["context"]["reaction_source_id"] == CHOICE + "_result")
        assert result["context"]["reactor_id"] == LEFT
        assert f"Visitor has {'taken damage' if hurt else 'taken no damage'}" in str(result)
    else:
        assert not prompts  # a fully automatic creature settles its own choice


def test_declining_reveals_no_damage_history(tmp_path):
    combat, table, mid = fixture(tmp_path)
    send(combat, table, mid, "Seal")
    turn(table, mid, RIGHT)
    turn(table, mid, LEFT)
    _, prompts = send(combat, table, mid, "Read the Pulse", picks={CHOICE: []})
    assert prompts and not readings(fresh(combat, mid))
    assert any("Read the Pulse:" in str(event.payload) for event in fresh(combat, mid).events)


def test_nonowner_keeps_ordinary_diagnosis_without_prompt_or_history(tmp_path):
    combat, table, mid = fixture(tmp_path, owns=False)
    send(combat, table, mid, "Seal")
    _, prompts = send(combat, table, mid, "Read the Pulse")
    assert not prompts and not readings(fresh(combat, mid))


def test_first_reading_cannot_use_the_seal_it_just_placed(tmp_path):
    combat, table, mid = fixture(tmp_path)
    _, prompts = send(combat, table, mid, "Read the Pulse")
    assert not prompts and not readings(fresh(combat, mid))
    assert bears_mark(fresh(combat, mid).state.actors[ALLY], LEFT, "Pulse Seal")
    turn(table, mid, RIGHT)
    turn(table, mid, LEFT)
    _, prompts = send(combat, table, mid, "Read the Pulse")
    assert any(p["context"]["reaction_source_id"] == CHOICE for p in prompts)
    assert len(readings(fresh(combat, mid))) == 1


@pytest.mark.parametrize("owns,expected", [(False, 1), (True, 2)])
def test_finite_seal_capacity_adds_exactly_one_and_refreshes_without_duplicates(tmp_path, owns, expected):
    combat, table, mid = fixture(tmp_path, owns=owns, cap=1)
    for target in (LEFT, ALLY, RIGHT, RIGHT):
        send(combat, table, mid, "Seal", target=target)
    engine = fresh(combat, mid)
    assert sum(bears_mark(actor, LEFT, "Pulse Seal") for actor in engine.state.actors.values()) == expected
    assert bears_mark(engine.state.actors[RIGHT], LEFT, "Pulse Seal")


def test_no_new_cap_is_imposed_on_current_uncapped_seals(tmp_path):
    combat, table, mid = fixture(tmp_path)
    for target in (LEFT, ALLY, RIGHT):
        send(combat, table, mid, "Seal", target=target)
    engine = fresh(combat, mid)
    assert all(bears_mark(actor, LEFT, "Pulse Seal") for actor in engine.state.actors.values())


def test_finite_capacity_and_private_reading_coexist_after_reload(tmp_path):
    combat, table, mid = fixture(tmp_path, cap=1)
    for target in (LEFT, RIGHT, ALLY):
        send(combat, table, mid, "Seal", target=target)
    turn(table, mid, RIGHT)
    turn(table, mid, LEFT)
    _, prompts = send(combat, table, mid, "Read the Pulse")
    engine = fresh(combat, mid)
    assert sum(bears_mark(actor, LEFT, "Pulse Seal") for actor in engine.state.actors.values()) == 2
    assert len(readings(engine)) == 1
    assert readings(engine)[0].instance_id in concealed_condition_instances(engine.state.model_dump(mode="json"))
    assert sum(p["context"]["reaction_source_id"] == CHOICE for p in prompts) == 1
    assert sum(p["context"]["reaction_source_id"] == CHOICE + "_result" for p in prompts) == 1
    assert not any(event.source_definition_id == FEATURE and event.payload.get("log") for event in engine.events)


def test_existing_seal_without_a_previous_recorded_turn_stays_unknown(tmp_path):
    combat, table, mid = fixture(tmp_path)
    send(combat, table, mid, "Seal")
    _, prompts = send(combat, table, mid, "Read the Pulse")
    assert not prompts
    assert not readings(fresh(combat, mid))


def test_damage_absorbed_by_temporary_hp_still_counts_as_damage(tmp_path):
    combat, table, mid = fixture(tmp_path)
    send(combat, table, mid, "Seal")
    send(combat, table, mid, "Ward")
    turn(table, mid, RIGHT)
    resolve(lambda answers: act(table, mid, "Cause", answers, target_id=ALLY))
    turn(table, mid, LEFT)
    send(combat, table, mid, "Read the Pulse")
    engine = fresh(combat, mid)
    assert engine.state.actors[ALLY].current_hp == 1000
    assert readings(engine)[-1].data["value"] == "Took damage"


def test_zero_damage_does_not_count(tmp_path):
    combat, table, mid = fixture(tmp_path, damage=0)
    send(combat, table, mid, "Seal")
    turn(table, mid, RIGHT)
    resolve(lambda answers: act(table, mid, "Cause", answers, target_id=ALLY))
    turn(table, mid, LEFT)
    send(combat, table, mid, "Read the Pulse")
    assert readings(fresh(combat, mid))[-1].data["value"] == "Took no damage"


def test_last_turn_window_expires_old_damage_after_two_owner_turns(tmp_path):
    combat, table, mid = fixture(tmp_path)
    send(combat, table, mid, "Seal")
    turn(table, mid, RIGHT)
    resolve(lambda answers: act(table, mid, "Cause", answers, target_id=ALLY))
    for _ in range(2):
        turn(table, mid, LEFT)
        turn(table, mid, RIGHT)
    turn(table, mid, LEFT)
    send(combat, table, mid, "Read the Pulse")
    assert readings(fresh(combat, mid))[-1].data["value"] == "Took no damage"


def test_remote_reading_requires_existing_seal_and_uses_same_choice(tmp_path):
    combat, table, mid = fixture(tmp_path)
    engine = fresh(combat, mid)
    assert not any(candidate.display_name == "Read the Pulse (Pulse Seal)" and ALLY in candidate.target_ids
                   for candidate in engine.legal_candidates())
    send(combat, table, mid, "Seal")
    turn(table, mid, RIGHT)
    turn(table, mid, LEFT)
    _, prompts = send(combat, table, mid, "Read the Pulse (Pulse Seal)")
    assert any(p["context"]["reaction_source_id"] == CHOICE for p in prompts)
    assert readings(fresh(combat, mid))[-1].data["value"] == "Took no damage"
