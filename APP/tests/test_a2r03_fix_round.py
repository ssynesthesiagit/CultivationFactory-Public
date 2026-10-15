"""Stopped-run regressions at the compiled-action and real table boundaries."""
import pytest
import copy
from pathlib import Path

# These shipped inputs are loaded dynamically by the compiler. Declare exact
# dependencies so the public test export contains the same rules as the app.
FOUNDATION_BLOCK_INPUTS = (
    Path("combat/rules/feature_blocks.d/beast_echo.json"),
    Path("combat/rules/feature_blocks.d/sacred_body.json"),
)
CANONICAL_SOURCE_INPUTS = (
    Path("authority/typed_mechanics/reviewed_final.d/riders_c4.json"),
    Path("authority/typed_mechanics/reviewed_final.d/a2_berserker.json"),
    Path("authority/typed_mechanics/reviewed_final.d/support.json"),
    Path("authority/typed_mechanics/reviewed_final.d/auto5_spirit.json"),
)

from combat.factory_compiler import compile_character
from tests.test_a2r11_foundations import (
    FIGHTER, SERVICE_FOE, SERVICE_ALLY, SACRED_BARE, MARROW_BARE, PULSE, ECHO,
    _sacred, _marrow, _doc, _first_feature, _service_fight, _until,
    _candidate, _play, _engine, _act, _answer_for,
)

COMPANION = "actor:factory.a2r03-bonded"


def _play_picked(table, mid, candidate, pick):
    """Answer each prompt independently, preserving native OA/guard decisions."""
    answers, prompts = [], []
    for _ in range(30):
        result = _act(table, mid, candidate, answers)
        if result['status'] == 'COMMITTED':
            return result, prompts
        assert result['status'] == 'REACTION_REQUIRED', result
        prompt = result['reaction']
        prompts.append(prompt)
        answers.append(_answer_for(prompt, pick(prompt)))
    raise AssertionError('too many prompts')


def _add_companion(bundles):
    owner = next(b for b in bundles if b["actor_id"] == FIGHTER)
    ally = next(b for b in bundles if b["actor_id"] == SERVICE_ALLY)
    template = copy.deepcopy(ally["actor_template"])
    template.update(entity_id=COMPANION, owner_id=FIGHTER, display_name="bonded companion",
                    primary_combatant=False, action_ids=[], reaction_ids=[])
    owner["summons"].append({"actor_id": COMPANION, "actor_template": template,
        "action_catalog": [], "typed_passives": [], "typed_reactions": [],
        "summon": {"owner": FIGHTER, "group": "test:a2r03_bond", "source": "test:a2r03_bond",
                   "arrives": "start", "command": "free", "command_range_ft": 60,
                   "range_ft": 60, "concentration": False, "expected_damage": 0}})


def _prepare_pressure(ability, dc, condition, held=0):
    """Seal a deterministic hostile test technique before match creation."""
    def prepare(bundles):
        owner = next(b for b in bundles if b["actor_id"] == FIGHTER)
        for resource in owner["actor_template"]["resources"]:
            if resource["resource_id"] in {PULSE, ECHO}:
                resource["initial"] = held
        foe = next(b for b in bundles if b["actor_id"] == SERVICE_FOE)
        action = copy.deepcopy(next(a for a in foe["action_catalog"]
                                    if a["display_name"] == "Unarmed Strike"))
        action.update(source_definition_id="action:test.a2r03_pressure", display_name="Body pressure",
                      resolution_kind="TYPED", target_kind="HOSTILE_ENTITY", economy="ACTION")
        action["parameters"] = {"typed": {"source": "test:a2r03_pressure", "numbers": {"save_dc": dc},
            "duration": {"kind": "rounds", "amount": 1}, "riders": [], "effects": [
                {"type": "save", "ability": ability.lower(), "applies_to": "target",
                 "on_success": [], "on_fail": [{"type": "condition", "condition": condition,
                                                "applies_to": "target"}]}]}}
        foe["action_catalog"].append(action)
        foe["actor_template"]["action_ids"].append(action["source_definition_id"])
    return prepare


def _add_scoped_test_attack(bundles, actor_id, source_id, *, display_name="Body pressure",
                            action_id="action:test.a2r03_scoped_attack"):
    actor = next(bundle for bundle in bundles if bundle["actor_id"] == actor_id)
    action = copy.deepcopy(next(row for row in actor["action_catalog"]
                                if row["display_name"] == "Unarmed Strike"))
    action.update(source_definition_id=action_id, display_name=display_name, owner_id=actor_id)
    action["parameters"]["typed"]["source"] = source_id
    actor["action_catalog"].append(action)
    actor["actor_template"]["action_ids"].append(action_id)


def test_frame_and_pulse_and_pressure_method_commit_and_reload_at_the_table(tmp_path, monkeypatch):
    combat, table, mid = _service_fight(tmp_path, monkeypatch, _sacred(), SACRED_BARE,
                                       prepare=_prepare_pressure("CON", 16, "poisoned"))
    def pick(prompt):
        options = [o['id'] for o in prompt.get('choice', {}).get('options', [])]
        return 'step:3,5' if 'step:3,5' in options else 'move' if 'move' in options else 'DECLINE'
    _, prompts = _play_picked(table, mid, _candidate(table, mid, "Body pressure", FIGHTER), pick)
    cold = _engine(combat, mid)
    fighter = cold.state.actors[FIGHTER]
    assert fighter.maximum_hp == 512  # Golden Blood Root's 3 * PB, replacing Frame's 2 * PB
    save = next(e for e in reversed(cold.events) if e.event_type == "SAVE_ROLLED")
    assert save.payload["success"] is True  # 10 + CON 2 + Frame 4
    assert fighter.resources[PULSE] == 1
    assert any("Pressure Becomes Method" in str(p) for p in prompts)
    assert fighter.position.model_dump() != {"x": 3, "y": 6, "z": 0}
    assert any(e.event_type == "MOVEMENT_COMMITTED" and e.actor_id == FIGHTER for e in cold.events)


def test_refuse_heaven_lock_pays_a_prior_pulse_on_a_failed_table_save(tmp_path, monkeypatch):
    combat, table, mid = _service_fight(tmp_path, monkeypatch, _sacred(), SACRED_BARE,
                                       prepare=_prepare_pressure("CON", 20, "poisoned", held=1))
    _, prompts = _play(table, mid, _candidate(table, mid, "Body pressure", FIGHTER), answer="USE")
    cold = _engine(combat, mid)
    assert any("Refuse Heaven-Lock" in str(p) for p in prompts)
    save = next(e for e in reversed(cold.events) if e.event_type == "SAVE_ROLLED")
    assert save.payload["success"] is True
    assert any(e.event_type == "RESOURCE_SPENT" and e.actor_id == FIGHTER
               and e.payload.get("resource_id") == PULSE for e in cold.events)


def test_beast_sense_witness_is_free_and_survives_a_table_commit(tmp_path, monkeypatch):
    def prepare(bundles):
        _prepare_pressure("WIS", 16, "frightened", held=1)(bundles)
        foe = next(bundle for bundle in bundles if bundle["actor_id"] == SERVICE_FOE)
        body_pressure = next(row for row in foe["action_catalog"]
                             if row["display_name"] == "Body pressure")
        body_pressure["parameters"]["typed"]["source"] = "TAL_BRUTE_MOUNTAIN_MOVING_PALM"

    combat, table, mid = _service_fight(tmp_path, monkeypatch, _marrow(), MARROW_BARE,
                                       prepare=prepare)
    _, prompts = _play(table, mid, _candidate(table, mid, "Body pressure", FIGHTER), answer="USE")
    cold = _engine(combat, mid)
    assert any("Beast-Sense Witness" in str(p) for p in prompts)
    save = next(e for e in reversed(cold.events) if e.event_type == "SAVE_ROLLED")
    assert save.payload["success"] is True
    assert cold.state.actors[FIGHTER].resources[ECHO] == 0
    assert cold.state.actors[FIGHTER].reaction_available is True


def test_guard_trigger_filter_is_inert_for_unrelated_reactions():
    from combat.ext.beast_echo_marrow import marrow_pack_guard_trigger
    from tests.test_a2r11_foundations import _duel, M_GUARD, ME, FOE
    engine = _duel([M_GUARD], _marrow())
    assert marrow_pack_guard_trigger(engine, engine.state.actors[ME], engine.state.actors[FOE],
                                     engine.state.actors[ME], {"feature_id": "opportunity_attack"}) is None


@pytest.mark.parametrize("source_id", [
    "TAL_BRUTE_MOUNTAIN_MOVING_PALM",
    "TAL_BERSERKER_BERSERK",
    "TAL_BEASTMASTERY_BEAST_TAMER",
    "TAL_SPIRIT_COMPANIONS_BINDING_SEAL",
])
def test_beast_echo_scope_accepts_shipped_canonical_talent_sources(source_id):
    """The canonical talent IDs are the sources sealed by the compiler."""
    import json
    from combat.ext.beast_echo_marrow import in_scope

    records = {}
    for path in CANONICAL_SOURCE_INPUTS:
        records.update(json.loads(path.read_text()).get("mechanics", {}))
    assert source_id in records
    assert in_scope(source_id)
    assert in_scope("tianxia.talent.brute.mountain_moving_palm")
    assert not in_scope("TAL_SABER_MOUNTAIN_MOVING_PALM")
    assert not in_scope("unrelated-brute-ish-source")
    assert not in_scope("wrapper:TAL_BRUTE_MOUNTAIN_MOVING_PALM")

    from types import SimpleNamespace
    from combat.ext import beast_echo_marrow as marrow
    from tests.test_a2r11_foundations import _duel, _marrow, M_GUARD, M_WITNESS, FOE
    engine = _duel([M_GUARD, M_WITNESS], _marrow(), ally_mids=[])
    engine.d20_context = lambda: {"source_id": source_id}
    assert marrow._witness_scope(engine, SimpleNamespace(named=()))
    engine._active_action_source_id = source_id
    assert marrow._scope_source(engine, engine.state.actors[FOE])
    engine._active_action_source_id = f"action:typed.test.{source_id}"
    assert marrow._scope_source(engine, engine.state.actors[FOE])
    engine._active_action_source_id = f"wrapper:{source_id}"
    assert not marrow._scope_source(engine, engine.state.actors[FOE])


def test_refined_pack_marrow_range_is_distinct_from_bonded_pair_eligibility():
    """The bonded pair can still use Strike at any range; only Refined is capped."""
    from combat.ext import beast_echo_marrow as marrow
    from combat.gate2_runtime_models import Position
    from tests.test_a2r11_foundations import _duel, M_STRIKE, M_MARROW, ME, FOE, ALLY, give, script, attack

    engine = _duel([M_STRIKE, M_MARROW], _marrow(), ally_mids=[])
    owner, target, companion = (engine.state.actors[key] for key in (ME, FOE, ALLY))
    companion.summon = {"owner": ME, "group": "test:bond", "status": "present",
                        "commanded": True, "range_ft": 60, "command_range_ft": 60}
    owner.position = Position(x=3, y=6, z=0)
    target.position = Position(x=4, y=6, z=0)
    give(engine, ME, pack_echo=0)
    script(engine, [10, 4])
    attack(engine, ME, FOE, bonus=8, source_id="action:test.prior_hit")
    assert any(event.event_type == "DAMAGE_COMMITTED" and event.actor_id == ME
               and FOE in event.target_ids for event in engine.events)
    give(engine, ME, pack_echo=1)

    companion.position = Position(x=9, y=6, z=0)  # exactly 30 feet
    assert marrow._pair_near(engine, owner, companion, 30)  # ordinary Pair remains legal
    assert marrow._refined_pack_marrow_qualifies(engine, owner, companion, target)
    companion.position = Position(x=10, y=6, z=0)  # 35 feet
    assert marrow._pair_near(engine, owner, companion, 30)  # bonded companion exception remains
    assert not marrow._refined_pack_marrow_qualifies(engine, owner, companion, target)


def test_canonical_scope_source_still_requires_owned_generation_and_valid_scope():
    from combat.ext import beast_echo_marrow as marrow
    from combat.typed_executor import Context
    from tests.test_a2r11_foundations import _duel, M_GENERATE, ME, FOE, give, amount

    source = "TAL_BRUTE_MOUNTAIN_MOVING_PALM"
    for features, candidate_source, expected in (
        ([M_GENERATE], source, 1),
        ([], source, 0),  # owning no Foundation row leaves the plug-in inert
        ([M_GENERATE], "TAL_SABER_MOUNTAIN_MOVING_PALM", 0),  # wrong sphere/source
    ):
        engine = _duel(features, _marrow(), ally_mids=[])
        give(engine, ME, pack_echo=0)
        actor, target = engine.state.actors[ME], engine.state.actors[FOE]
        action = next(iter(engine.action_catalog.values()))
        ctx = Context(engine, actor, action, None, {"source": candidate_source}, [target], target, {})
        marrow.pack_echo_generation(ctx, target, "weapon")
        assert amount(engine, ME, "pack_echo") == expected


def test_canonical_brute_source_generates_then_spends_echo_through_table_reload(tmp_path, monkeypatch):
    def prepare(bundles):
        owner = next(bundle for bundle in bundles if bundle["actor_id"] == FIGHTER)
        for resource in owner["actor_template"]["resources"]:
            if resource["resource_id"] == ECHO:
                resource["initial"] = 0
        _add_scoped_test_attack(bundles, FIGHTER, "TAL_BRUTE_MOUNTAIN_MOVING_PALM")

    combat, table, mid = _service_fight(tmp_path, monkeypatch, _marrow(), MARROW_BARE,
                                       ally=True, prepare=prepare)
    _until(table, mid, FIGHTER, answer="DECLINE")
    first = _candidate(table, mid, "Body pressure", SERVICE_FOE)
    _play(table, mid, first)
    after_generation = _engine(combat, mid)
    assert after_generation.state.actors[FIGHTER].resources[ECHO] == 1
    hp_after_first = after_generation.state.actors[SERVICE_FOE].current_hp
    _play(table, mid, table.state(mid)["menu"]["end_turn"])
    _until(table, mid, FIGHTER, answer="DECLINE")
    _, prompts = _play(table, mid, _candidate(table, mid, "Body pressure", SERVICE_FOE),
                       answer="strike")
    cold = _engine(combat, mid)
    assert any("Pack-Marrow Strike" in str(prompt) for prompt in prompts)
    spent = [event for event in cold.events if event.event_type == "RESOURCE_SPENT"
             and event.actor_id == FIGHTER
             and event.payload.get("resource_id") == ECHO]
    assert spent and cold.state.actors[FIGHTER].resources[ECHO] == 1
    assert hp_after_first - cold.state.actors[SERVICE_FOE].current_hp == 7  # hit damage 3 + Strike PB 4


def test_guard_recognizes_canonical_brute_source_on_a_nonbeast_attacker(tmp_path, monkeypatch):
    def prepare(bundles):
        owner = next(bundle for bundle in bundles if bundle["actor_id"] == FIGHTER)
        for resource in owner["actor_template"]["resources"]:
            if resource["resource_id"] == ECHO:
                resource["initial"] = 1
        _add_scoped_test_attack(bundles, SERVICE_FOE, "TAL_BRUTE_MOUNTAIN_MOVING_PALM",
                                display_name="Mountain-Moving Palm",
                                action_id="action:typed.test.TAL_BRUTE_MOUNTAIN_MOVING_PALM")

    combat, table, mid = _service_fight(tmp_path, monkeypatch, _marrow(), MARROW_BARE,
                                       prepare=prepare)
    candidate = _candidate(table, mid, "Mountain-Moving Palm", FIGHTER)
    _, prompts = _play(table, mid, candidate, answer="USE")
    cold = _engine(combat, mid)
    assert any("Marrow Pack Guard" in str(prompt) for prompt in prompts)
    assert cold.state.actors[FIGHTER].resources[ECHO] == 0


def test_canonical_brute_scope_enables_state_technique_rider_only_for_eligible_source(monkeypatch):
    from types import SimpleNamespace
    from combat.ext import beast_echo_marrow as marrow, needle
    from tests.test_a2r11_foundations import _duel, M_STATE, ME, give, use

    engine = _duel([M_STATE], _marrow(), ally_mids=[])
    give(engine, ME, pack_echo=1)
    use(engine, "Beast-Echo Marrow State")
    actor = engine.state.actors[ME]
    calls = []
    monkeypatch.setattr(needle, "ask", lambda *args, **kwargs: calls.append(args[4]) or [])
    action = SimpleNamespace(costs=(("resource:core.qi", 1),))
    ctx = SimpleNamespace(engine=engine, actor=actor, action=action,
                          typed={"source": "TAL_BRUTE_MOUNTAIN_MOVING_PALM"})
    marrow.state_technique_move(ctx)
    assert calls == ["choice:needle.beast_echo_state_move"]
    actor.turn_flags.pop("beast_echo_state_move", None)
    ctx.typed["source"] = "TAL_SABER_MOUNTAIN_MOVING_PALM"
    marrow.state_technique_move(ctx)
    assert "beast_echo_state_move" not in actor.turn_flags


def test_frame_lookup_uses_the_generic_rows_feature_id():
    from combat.ext.foundation_sacred_body import frame_row
    from tests.test_a2r11_foundations import _duel, FRAME, ME
    engine = _duel([FRAME], _sacred("Awakened"))
    row = frame_row(engine, engine.state.actors[ME])
    assert row is not None and row["feature_id"] == FRAME
    assert row["bonus"] == 4


def test_companion_echo_table_save_pays_psychic_damage_and_clears_its_roll_marker(tmp_path, monkeypatch):
    def prepare(bundles):
        _prepare_pressure("WIS", 22, "frightened", held=1)(bundles)
        _add_companion(bundles)
    combat, table, mid = _service_fight(tmp_path, monkeypatch, _marrow(), MARROW_BARE,
                                       ally=True, prepare=prepare,
                                       positions={FIGHTER: {"x": 4, "y": 7}})
    _, prompts = _play(table, mid, _candidate(table, mid, "Body pressure", COMPANION), answer="USE")
    cold = _engine(combat, mid)
    assert any("Companion Echo" in str(p) for p in prompts)
    assert cold.state.actors[FIGHTER].current_hp == 490
    assert any(e.event_type == "DAMAGE_COMMITTED" and e.source_definition_id.endswith(".companion_echo")
               for e in cold.events)
    assert cold.state.actors[FIGHTER].resources[ECHO] == 0
    assert cold.state.actors[FIGHTER].reaction_available is True
    assert not cold.state.actors[FIGHTER].turn_flags.get(f"beast_echo_witnessed:{COMPANION}")


def test_marrow_pack_guard_and_companion_echo_protect_the_companion_at_the_table(tmp_path, monkeypatch):
    def prepare(bundles):
        _prepare_pressure("WIS", 22, "frightened", held=1)(bundles)
        _add_companion(bundles)
    combat, table, mid = _service_fight(tmp_path, monkeypatch, _marrow(), MARROW_BARE,
                                       ally=True, foe_creature_types=("Beast",), prepare=prepare,
                                       positions={FIGHTER: {"x": 4, "y": 7}})
    _, prompts = _play(table, mid, _candidate(table, mid, "Unarmed Strike", COMPANION), answer="USE")
    cold = _engine(combat, mid)
    assert any("Marrow Pack Guard" in str(p) for p in prompts)
    assert cold.state.actors[FIGHTER].resources[ECHO] == 0
    damage = [e for e in cold.events if e.event_type == "DAMAGE_COMMITTED"
              and COMPANION in e.target_ids]
    assert damage and damage[-1].payload["hp_damage"] == 0


def test_pack_marrow_improves_an_allied_table_hit_after_the_owner_damaged_the_target(tmp_path, monkeypatch):
    combat, table, mid = _service_fight(tmp_path, monkeypatch, _marrow(), MARROW_BARE, ally=True,
                                       prepare=_prepare_pressure("WIS", 22, "frightened", held=1))
    combat.set_controller_mode(mid, actor_id=SERVICE_ALLY, controller_mode="MANUAL")
    _until(table, mid, FIGHTER, answer="DECLINE")
    # Keep the prior Echo for the ally by declining the fighter's paid hit rider.
    _play(table, mid, _candidate(table, mid, "Unarmed Strike", SERVICE_FOE))
    _play(table, mid, table.state(mid)["menu"]["end_turn"])
    _until(table, mid, SERVICE_ALLY, answer="DECLINE")
    _, prompts = _play(table, mid, _candidate(table, mid, "Unarmed Strike", SERVICE_FOE), answer="strike")
    cold = _engine(combat, mid)
    assert any("Pack-Marrow Strike" in str(p) for p in prompts)
    bonus = [e for e in cold.events if e.event_type == "DAMAGE_COMMITTED" and e.actor_id == FIGHTER
             and SERVICE_FOE in e.target_ids]
    assert bonus[-1].payload["hp_damage"] == 8  # Strike PB + Pack Marrow PB


def test_ai_predator_choice_keeps_both_legal_options(monkeypatch):
    from combat.ext import beast_echo_marrow, needle
    from combat.typed_executor import Context
    from tests.test_a2r11_foundations import _duel, M_PREDATOR, ME, FOE
    engine = _duel([M_PREDATOR], _marrow())
    engine.typed_control_modes = {ME: "LOCAL_AUTO"}
    seen = []
    original = needle.ask
    def ask(*args, **kwargs):
        seen.append((args[5], kwargs))
        return original(*args, **kwargs)
    monkeypatch.setattr(needle, "ask", ask)
    action = next(iter(engine.action_catalog.values()))
    ctx = Context(engine, engine.state.actors[ME], action, None, {}, [engine.state.actors[FOE]])
    beast_echo_marrow.predator_answer(engine, ctx.actor, engine.state.actors[FOE], ctx)
    assert seen[0][0] == ["temp_hp", "move"]
    assert "automatic_options" not in seen[0][1]
    assert seen[0][1]["preferred"] == ["temp_hp"]


def test_state_witness_quotes_do_not_spend_the_pairs_round_bonus():
    from types import SimpleNamespace
    from combat.ext import beast_echo_marrow as marrow
    from tests.test_a2r11_foundations import _duel, M_STATE, ME, ALLY, use, give
    engine = _duel([M_STATE], _marrow(), ally_mids=[])
    give(engine, ME, pack_echo=1)
    use(engine, "Beast-Echo Marrow State")
    actor = engine.state.actors[ME]
    holder = SimpleNamespace(actor=actor, numbers={"pb": 4})
    roll = SimpleNamespace(roller=actor, roll=SimpleNamespace(roll_id="test:first"))
    assert marrow._witness_bonus(engine, holder, roll) == 8
    assert marrow._witness_bonus(engine, holder, roll) == 8
    assert marrow.PAIR_BUDGET not in actor.turn_flags
    marrow._witness_used(engine, holder, roll)
    assert marrow._witness_bonus(engine, holder, roll) == 8
    roll.roll.roll_id = "test:next"
    assert marrow._witness_bonus(engine, holder, roll) == 4


def test_close_ranged_hits_cannot_use_saint_body_rebuke():
    from types import SimpleNamespace
    from combat.ext.foundation_sacred_body import saint_body_rebuke
    from combat.typed_executor import Context
    from tests.test_a2r11_foundations import _duel, REBUKE, ME, FOE, give
    engine = _duel([REBUKE], _sacred())
    give(engine, ME, golden_sea_pulse=1)
    actor, target = engine.state.actors[ME], engine.state.actors[FOE]
    action = next(iter(engine.action_catalog.values()))
    ctx = Context(engine, actor, action, None, {"source": "test:ranged"}, [target])
    ctx.hit_snapshots = {"sacred_body_rebuke": 1}
    ctx.attack_notice = SimpleNamespace(hit=True, melee=False)
    before = target.current_hp
    saint_body_rebuke(ctx, target, "weapon")
    assert actor.resources[PULSE] == 1
    assert target.current_hp == before


def test_golden_blood_mark_waits_for_an_eligible_save():
    from combat.ext.foundation_sacred_body import guard_advantage_and_wake, GUARD_ADVANTAGE
    from tests.test_a2r11_foundations import _duel, BLOOD, ME, FOE
    engine = _duel([BLOOD], _sacred())
    actor = engine.state.actors[ME]
    engine._apply_condition(actor, GUARD_ADVANTAGE, "test:guard", ME,
                            expires_on="START_OF_SOURCE_NEXT_TURN", data={"source": FOE})
    rc = {"source_actor_id": FOE, "named": []}
    assert guard_advantage_and_wake(engine, actor, "CON", 10, "test:save", rc) is None
    assert any(c.condition_id == GUARD_ADVANTAGE for c in actor.conditions.values())
    rc["named"] = ["poisoned"]
    assert guard_advantage_and_wake(engine, actor, "CON", 10, "test:save", rc) == "ADVANTAGE"
    assert not any(c.condition_id == GUARD_ADVANTAGE for c in actor.conditions.values())


def test_frame_bonus_precedes_the_optional_failed_check_rescue():
    from combat.typed_executor import Context, run_effects
    from tests.test_a2r11_foundations import _duel, FRAME, ME, FOE, give, script, RESCUE
    engine = _duel([FRAME], _sacred("Awakened"))
    give(engine, ME, golden_sea_pulse=1)
    actor, target = engine.state.actors[ME], engine.state.actors[FOE]
    action = next(iter(engine.action_catalog.values()))
    effect = {"type": "contest_against", "harmful": True, "applies_to": "target",
              "actor_check": {"kind": "check", "ability": "STR", "skill": "Athletics",
                              "hazards": ["poisoned"]},
              "target_check": {"kind": "dc", "dc": 12}, "on_success": [], "on_fail": []}
    script(engine, [8])  # 8 + STR 2 + Frame 4 already succeeds
    run_effects(Context(engine, actor, action, None, {"source": "test:frame", "effects": [effect]},
                        [target], target), [effect])
    assert actor.resources[PULSE] == 1
    assert not any(e.event_type == "D20_REWRITTEN" and e.payload.get("source_id") == RESCUE
                   for e in engine.events)


@pytest.mark.parametrize("bare,foundation,label", [
    (SACRED_BARE, _sacred(), "Sacred Body Wake"),
    (MARROW_BARE, _marrow(), "Beast-Echo Marrow State"),
])
def test_state_actions_keep_the_owners_compiled_numbers(bare, foundation, label):
    bundle = compile_character(_doc([_first_feature(bare)], "fighter", foundation=foundation),
                               actor_id=FIGHTER)
    action = next(row for row in bundle["action_catalog"] if row["display_name"] == label)
    assert action["parameters"]["typed"]["numbers"]["cl"] == 10
    assert action["parameters"]["typed"]["numbers"]["pb"] == 4
    assert action["parameters"]["typed"]["numbers"]["con_mod"] == 2


def test_new_echo_cannot_pay_for_the_hit_that_generated_it_at_the_table(tmp_path, monkeypatch):
    combat, table, mid = _service_fight(tmp_path, monkeypatch, _marrow(), MARROW_BARE,
                                       ally=True, foe_creature_types=("Beast",))
    _until(table, mid, FIGHTER)
    _, prompts = _play(table, mid, _candidate(table, mid, "Unarmed Strike", SERVICE_FOE),
                       answer="temp_hp")
    assert any("Predator Answer" in str(prompt) for prompt in prompts)
    assert not any("Pack-Marrow Strike" in str(prompt) for prompt in prompts)
    cold = _engine(combat, mid)
    assert cold.state.actors[FIGHTER].resources[ECHO] == 1
    assert cold.state.actors[FIGHTER].temporary_hp == 4


@pytest.mark.parametrize("rider", ["push", "reactions", "frame"])
def test_rebuke_asks_for_every_rider_on_the_triggering_hit(tmp_path, monkeypatch, rider):
    combat, table, mid = _service_fight(tmp_path, monkeypatch, _sacred(), SACRED_BARE)
    _until(table, mid, FIGHTER)
    _, prompts = _play(table, mid, _candidate(table, mid, "Unarmed Strike", SERVICE_FOE),
                       answer=rider)
    choices = [prompt for prompt in prompts if "Saint-Body Rebuke" in str(prompt)]
    assert choices
    options = choices[-1]["choice"]["options"]
    assert {row["id"] for row in options} == {"push", "reactions", "frame"}
    cold = _engine(combat, mid)
    assert cold.state.actors[FIGHTER].resources[PULSE] == 0
    if rider == "push":
        assert cold._distance_actor_to_actor(cold.state.actors[FIGHTER],
                                            cold.state.actors[SERVICE_FOE]) > 5
    elif rider == "frame":
        assert any(c.condition_id == "condition:typed.saint_body_frame_advantage"
                   for c in cold.state.actors[FIGHTER].conditions.values())
