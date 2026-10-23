"""Review regressions using committed native procedures and cold table replay."""
from types import SimpleNamespace
from pathlib import Path
import json

import pytest

from combat import ext, senses, stealth
from combat.ability_checks import SOUND_RELIANCE, VISUAL_CONCEALMENT
from combat.ext.ironclad_smoke import TRACE_CONDITION, soot_scent_trace
from combat.ext.smoke_sound_residual import sound_hiding_denied
from combat.typed_executor import mark_condition_id
from tests.worker2_support import OWNER, ALLY, FOE, fixture, reload, settle, turn
from tests.test_a2r04_smoke_sound import (
    _echoes_fixture, _foe_turn, _resonance_on_hold, _smoke_fixture, SMOKE_FEATURE_BLOCKS,
)
from tests.test_a2r04_mirror_contract import hold, directions

# The compiler enumerates feature_blocks.d dynamically. Name the shipped
# ownership input explicitly so the public-CI dependency closure includes it.
MIRROR_FEATURE_BLOCKS = SMOKE_FEATURE_BLOCKS


@pytest.mark.parametrize("choice,cid", [
    ("lose_reaction", "condition:typed.reaction_denied"),
    ("echo_confusion", "condition:typed.echo_confusion"),
])
def test_echoes_survives_caster_turn_until_holders_next_turn(tmp_path, choice, cid):
    _, table, mid = _echoes_fixture(tmp_path)
    _foe_turn(table, mid, choice)
    engine = reload(tmp_path, mid)
    original = next(c for c in engine.state.actors[FOE].conditions.values() if c.condition_id == cid)
    turn(table, mid, OWNER)
    engine = reload(tmp_path, mid)
    assert original.instance_id in engine.state.actors[FOE].conditions
    turn(table, mid, FOE)
    engine = reload(tmp_path, mid)
    # A fresh failed zone save can apply a new instance; the original must end.
    assert original.instance_id not in engine.state.actors[FOE].conditions


@pytest.mark.parametrize("basis,denied", [
    ((SOUND_RELIANCE,), True),
    ((VISUAL_CONCEALMENT,), False),
    ((VISUAL_CONCEALMENT, SOUND_RELIANCE), False),
])
def test_sound_hiding_blocks_native_hide_and_existing_benefits_only_for_sound(tmp_path, monkeypatch, basis, denied):
    _, table, mid = fixture(tmp_path, [], seed="REVIEW-SOUND-HIDING")

    def trigger(engine):
        owner, foe = engine.state.actors[OWNER], engine.state.actors[FOE]
        # A blinded observer permits native Hide without granting any special
        # sense. Clear the blindness before checking the existing Hidden mask.
        for actor in engine.state.actors.values():
            if actor.team_id != foe.team_id:
                engine._apply_condition(actor, "condition:typed.blinded", "test:blind", actor.entity_id,
                                        expires_on="UNTIL_REMOVED")
        assert stealth.hide(engine, foe, 50, "test:hide", basis=basis)
        sound_hiding_denied(SimpleNamespace(engine=engine, actor=owner, target=foe), {})
        engine._apply_condition(foe, "condition:typed.check_mode", "test:advantage", foe.entity_id,
                                expires_on="UNTIL_REMOVED", data={"rule": {"check_mode": {"Stealth": "ADVANTAGE"}}})
        for actor in engine.state.actors.values():
            engine._remove_condition(actor, "condition:typed.blinded", "test:unblind")

    _resonance_on_hold(monkeypatch)(trigger)
    hold(table, mid, tmp_path)
    engine = reload(tmp_path, mid)
    owner, foe = engine.state.actors[OWNER], engine.state.actors[FOE]
    iid = stealth.hidden(foe)
    assert iid is not None
    assert (iid in senses.masked_conditions(engine, owner, foe).get(FOE, set())) is denied
    assert senses.finds(engine, owner, foe) is denied
    from combat.typed_executor import check_modes
    assert check_modes(foe, "DEX", "Stealth", engine=engine, hazards=basis) == {"ADVANTAGE"}

    # A second native attempt in a separate committed transaction must be denied
    # even with a guaranteed-success skill total, while visual hiding succeeds.
    def retry(engine):
        foe = engine.state.actors[FOE]
        stealth.reveal(engine, foe, "test:retry", "retry")
        for actor in engine.state.actors.values():
            if actor.team_id != foe.team_id:
                engine._apply_condition(actor, "condition:typed.blinded", "test:blind", actor.entity_id,
                                        expires_on="UNTIL_REMOVED")
        assert stealth.hide(engine, foe, 50, "test:retry", basis=basis) is (not denied)

    # Replace the first Hold producer, rather than chaining monkeypatch wrappers.
    # Hold spends the current actor's remaining movement, so use an ally's
    # fresh turn for the second fixture transaction, before the caster's next turn.
    turn(table, mid, ALLY)
    monkeypatch.undo()
    _resonance_on_hold(monkeypatch)(retry)
    hold(table, mid, tmp_path)
    assert bool(stealth.hidden(reload(tmp_path, mid).state.actors[FOE])) is (not denied)


@pytest.mark.parametrize("rule,expected", [
    ({"check_mode": {"DEX": "ADVANTAGE"}}, "ADVANTAGE"),
    ({"check_mode": {"ALL": "DISADVANTAGE"}}, "DISADVANTAGE"),
    ({"check_mode": {"Stealth": "ADVANTAGE"}}, "ADVANTAGE"),
])
def test_soot_escape_uses_shared_modes_and_skill_floor(tmp_path, monkeypatch, rule, expected):
    _, table, mid = fixture(tmp_path, ["TAL_SMOKE_SOOT_SCENT_TRAIL"], owner_dc=19,
                            seed="REVIEW-SOOT-CHECK")

    def trigger(engine):
        owner, foe = engine.state.actors[OWNER], engine.state.actors[FOE]
        soot_scent_trace(SimpleNamespace(engine=engine, actor=owner, target=foe, source="test:soot"), {})
        engine._apply_condition(foe, "condition:typed.check_mode", "test:mode", FOE,
                                expires_on="UNTIL_REMOVED", data={"rule": rule})
        engine._apply_condition(foe, "condition:typed.d20_floor", "test:floor", FOE,
                                expires_on="UNTIL_REMOVED",
                                data={"rule": {"d20_floor": {"floor": 20, "abilities": ["DEX"]}}})

    _resonance_on_hold(monkeypatch)(trigger)
    hold(table, mid, tmp_path)
    turn(table, mid, FOE)
    engine = reload(tmp_path, mid)
    assert any(c.condition_id == TRACE_CONDITION for c in engine.state.actors[OWNER].conditions.values())
    before = engine.state.event_sequence
    settle(table, mid, table.state(mid)["menu"]["end_turn"],
           picks={"choice:needle.soot_scent_escape": "first"})
    engine = reload(tmp_path, mid)
    event = next(e for e in engine.events if e.sequence > before and e.event_type == "CHECK_ROLLED"
                 and e.payload.get("against") == OWNER)
    rolled = event.payload["actor"]
    assert rolled["mode"] == expected
    assert rolled["natural_result"] < 20  # proves the floor, rather than a lucky die, caused success
    assert rolled["total"] == 20 + rolled["modifier"]
    assert event.payload["success"]
    assert not any(c.condition_id == TRACE_CONDITION for c in engine.state.actors[OWNER].conditions.values())


@pytest.mark.parametrize("independent", [None, "visual", "unscoped"])
def test_real_hide_loses_only_sound_qualified_advantage(tmp_path, monkeypatch, independent):
    """The ordinary table Hide path must consume the denial without special arguments."""
    from tests.h1_support import sheet

    foe_sheet = sheet([])
    foe_sheet["ability_scores_and_statistics"]["skills"] = [{"skill": "Stealth", "bonus": 50}]
    _, table, mid = fixture(tmp_path, [], foe_sheet=foe_sheet, seed="REVIEW-NATIVE-SOUND")

    def trigger(engine):
        owner, foe = engine.state.actors[OWNER], engine.state.actors[FOE]
        sound_hiding_denied(SimpleNamespace(engine=engine, actor=owner, target=foe), {})
        engine._apply_condition(foe, "condition:typed.check_mode", "test:sound_advantage", FOE,
                                expires_on="UNTIL_REMOVED",
                                data={"rule": {"check_mode": {"Stealth": "ADVANTAGE"},
                                               "hazards": [SOUND_RELIANCE]}})
        if independent:
            rule = {"check_mode": {"Stealth": "ADVANTAGE"}}
            if independent == "visual":
                rule["hazards"] = [VISUAL_CONCEALMENT]
            engine._apply_condition(foe, "condition:typed.check_mode", "test:independent", FOE,
                                    expires_on="UNTIL_REMOVED", data={"rule": rule})
        for actor in engine.state.actors.values():
            if actor.team_id != foe.team_id:
                engine._apply_condition(actor, "condition:typed.blinded", "test:blind", actor.entity_id,
                                        expires_on="UNTIL_REMOVED")

    _resonance_on_hold(monkeypatch)(trigger)
    hold(table, mid, tmp_path)
    turn(table, mid, FOE)
    engine = reload(tmp_path, mid)
    before = engine.state.event_sequence
    action = next(c for c in engine.legal_candidates() if c.display_name == "Hide")
    settle(table, mid, action.candidate_id)
    engine = reload(tmp_path, mid)
    event = next(e for e in engine.events if e.sequence > before and e.event_type == "CHECK_ROLLED"
                 and e.actor_id == FOE and e.payload.get("check") == "Stealth")
    assert event.payload["actor"]["mode"] == ("ADVANTAGE" if independent else "NORMAL")
    assert stealth.hidden(engine.state.actors[FOE]) is not None


@pytest.mark.parametrize("override", [False, True])
def test_mirror_reuses_mark_duration_application_and_notifications(tmp_path, monkeypatch, override):
    declared = json.loads((Path(__file__).resolve().parents[1] / MIRROR_FEATURE_BLOCKS).read_text())
    assert declared["features"]["TAL_SMOKE_SMOKE_MIRROR_TRAIL"]["block"] == "smoke_mirror_trail"
    _, table, mid = _smoke_fixture(tmp_path)
    from combat.ext.fight_ownership import owns_feature
    initial = reload(tmp_path, mid)
    assert owns_feature(initial, initial.state.actors[OWNER], "TAL_SMOKE_SMOKE_MIRROR_TRAIL")
    seen = []
    placements = []
    from combat import typed_executor
    original_mark = typed_executor.block_mark

    def record_mark(ctx, effect):
        placements.append((ctx.actor.entity_id, ctx.action.source_definition_id, effect))
        return original_mark(ctx, effect)

    monkeypatch.setattr(typed_executor, "block_mark", record_mark)
    original_run, original_strict = ext.run, ext.run_strict

    def run(name, *args, **kwargs):
        if name == "mark_duration" and args[1] == "Smoke Trace":
            return [{"kind": "minutes", "amount": 1}]
        if name == "mark_apply" and args[1].get("mark") == "Smoke Trace" and override:
            return [True]  # a legitimate placement override elects not to create a trace
        return original_run(name, *args, **kwargs)

    def strict(name, *args, **kwargs):
        if name == "mark_applied" and args[1] == "Smoke Trace":
            seen.append(args[2].entity_id)
        return original_strict(name, *args, **kwargs)

    monkeypatch.setattr(ext, "run", run)
    monkeypatch.setattr(ext, "run_strict", strict)
    # The owner-replacement adapter imports this public dispatcher by name.
    # Observe that legitimate application path as well as block_mark's fallback.
    from combat.ext import mark_choices
    monkeypatch.setattr(mark_choices, "run_strict", strict)

    def vanish(engine):
        engine._apply_condition(engine.state.actors[FOE], "condition:typed.invisible", "test:vanish", FOE,
                                expires_on="UNTIL_REMOVED")

    _resonance_on_hold(monkeypatch)(vanish)
    prompts = hold(table, mid, tmp_path)
    engine = reload(tmp_path, mid)
    marks = [c for c in engine.state.actors[FOE].conditions.values()
             if c.condition_id == mark_condition_id("Smoke Trace", OWNER)]
    catalog = [(a.source_definition_id, a.owner_id) for a in engine.action_catalog.values()
               if "smoke.place_trace" in a.source_definition_id]
    errors = [e.payload for e in engine.events if e.event_type == "GM_RIDER" and "failed:" in str(e.payload)]
    assert bool(marks) is (not override), f"Mirror mark presence: placements={placements}, catalog={catalog}, errors={errors}, prompts={len(prompts)}, override={override}"
    assert bool(directions(engine)) is (not override), f"Mirror direction presence: directions={directions(engine)}, override={override}"
    assert (FOE in seen) is (not override), f"Mirror notification: marks={marks}, seen={seen}, override={override}"
    if not override:
        assert marks[0].expires_on != "END_OF_MARKER_NEXT_TURN"
        assert directions(engine)[0].data["trace_instance_id"] == marks[0].instance_id
    assert not any(c.condition_id == "condition:typed.smoke_trace_round"
                   for c in engine.state.actors[OWNER].conditions.values())
