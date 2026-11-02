"""P15: save-branch durations through shared execution and real table reloads.

The real Venom Pill has two different Poisoned outcomes. These tests assert the
initial save result before inspecting duration; a successful initial save must
keep its printed short condition without acquiring the failed branch's repeat.
The Heaven's Roar row is the mixed-duration counterexample: its Deafened row's
evidence also mentions a separate, shorter Concentration disadvantage.
"""

from copy import deepcopy

import pytest

from combat import typed_executor
from combat.ext import effect_durations, states
from combat.gate2_rolls import DeterministicRollAuthority
from combat.gate2_runtime_models import ActionDefinition, EconomyKind
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, ME, FOE, duel, mechanics, script
from tests.test_lock2_persistence import act
from tests.test_tabletop_hunt6 import LEFT, RIGHT, table_fight


POISON_PILL = "TAL_ALCHEMY_POISON_PILL"
VENOM_SUFFIX = POISON_PILL + "#opt0"
ROAR = "tianxia.subpath.qi.kiai_master.feature.heaven_s_roar"
POISONED = "condition:typed.poisoned"
DEAFENED = "condition:typed.deafened"
CONCENTRATION_MODE = "condition:typed.concentration_mode"


@pytest.fixture
def pin_dice(monkeypatch):
    """Pin draws by seed and counter, identically for preview, commit and reload.

    A consuming shared queue would let the table's preview change the committed
    outcome. The recorded counter instead identifies the same draw on every
    cloned engine. All other dice retain the production deterministic roller.
    """
    original = DeterministicRollAuthority._die
    pinned = {}

    def die(roller, sides):
        key = (roller.seed, roller.counter)
        if key not in pinned:
            return original(roller, sides)
        value = pinned[key]
        assert 1 <= value <= sides
        counter = roller.counter
        roller.counter += 1
        return value, counter

    monkeypatch.setattr(DeterministicRollAuthority, "_die", die)

    def pin(engine, values):
        for offset, value in enumerate(values):
            key = (engine.roller.seed, engine.roller.counter + offset)
            assert key not in pinned or pinned[key] == value
            pinned[key] = value

    return pin


def _reload(tmp_path, mid):
    return CombatService(ROOT, tmp_path)._load_session(mid)


def _condition(engine, condition_id, actor_id=RIGHT, source=None):
    rows = [condition for condition in engine.state.actors[actor_id].conditions.values()
            if condition.condition_id == condition_id
            and (source is None or condition.source_definition_id == source)]
    assert len(rows) <= 1, "a single application must not produce duplicate conditions"
    return rows[0] if rows else None


def _pill_saves(engine):
    return [event for event in engine.events
            if event.event_type == "SAVE_ROLLED" and event.actor_id == RIGHT
            and event.source_definition_id.endswith(VENOM_SUFFIX)]


def _assert_replay(loaded):
    replay = loaded.mechanical.replay()
    assert replay["status"] == "PASS"
    assert replay["state"] == loaded.engine.state.model_dump(mode="json", by_alias=True)


def _cast_pill(tmp_path, pin_dice, *, initial_success=False):
    combat, table, mid = table_fight(tmp_path, [POISON_PILL], ally_talents=[])
    before = combat._load_session(mid).engine
    # One real CON save followed by the actual six damage dice. Minimum damage
    # leaves the synthetic target alive for the duration and repeat-save checks.
    pin_dice(before, [20 if initial_success else 1, *([1] * 6)])
    state = table.state(mid)
    menu = state["menu"]
    assert menu["actor_id"] == LEFT
    group, = [group for group in menu["actions"]
              if group["source_definition_id"].endswith(VENOM_SUFFIX)]
    option, = [option for option in group["options"] if option["target_ids"] == [RIGHT]]
    result = table.act(mid, option["candidate_id"], menu["decision_id"],
                       menu["state_version"], state["last_sequence"])
    assert result["status"] == "COMMITTED", result
    loaded = _reload(tmp_path, mid)
    save, = _pill_saves(loaded.engine)
    assert save.payload["success"] is initial_success
    assert save.payload["natural_result"] == (20 if initial_success else 1)
    assert save.payload["reason"] == f"SAVE:{save.source_definition_id}:CON"
    assert loaded.engine.state.actors[RIGHT].active
    return table, mid, before, loaded


def _advance_to_target(table, tmp_path, mid):
    """Use actual end-turn buttons; target-start must not itself repeat an end save."""
    loaded = _reload(tmp_path, mid)
    count = len(_pill_saves(loaded.engine))
    for _ in loaded.engine.state.initiative_order:
        if table.state(mid)["menu"]["actor_id"] == RIGHT:
            return loaded
        assert act(table, mid, "end")["status"] == "COMMITTED"
        loaded = _reload(tmp_path, mid)
        assert len(_pill_saves(loaded.engine)) == count
        assert _condition(loaded.engine, POISONED) is not None
    raise AssertionError("target did not receive its next turn")


def test_venom_failed_save_commits_ten_round_duration_and_repeat_metadata(tmp_path, pin_dice):
    _table, mid, before, loaded = _cast_pill(tmp_path, pin_dice)
    condition = _condition(loaded.engine, POISONED)
    assert condition is not None
    assert effect_durations.parse_round(condition.expires_on) == (
        before.state.round_number + 10, before.state.current_slot_index)
    assert condition.data["repeat_save"] == {"ability": "CON", "when": "end", "dc": 16}
    assert condition.source_actor_id == LEFT

    # Recreate the service and read the journal from disk, keeping all serialized
    # fields rather than checking only a displayed condition name.
    reopened = _reload(tmp_path, mid)
    restored = _condition(reopened.engine, POISONED)
    assert restored.model_dump(mode="json") == condition.model_dump(mode="json")
    _assert_replay(reopened)


@pytest.mark.parametrize("repeat_succeeds", [False, True])
def test_venom_repeats_only_at_target_end_and_success_alone_removes(
        tmp_path, pin_dice, repeat_succeeds):
    table, mid, _before, applied = _cast_pill(tmp_path, pin_dice)
    original = _condition(applied.engine, POISONED).model_dump(mode="json")
    target_turn = _advance_to_target(table, tmp_path, mid)
    assert len(_pill_saves(target_turn.engine)) == 1
    assert _condition(target_turn.engine, POISONED).model_dump(mode="json") == original

    # Reopen both table and service before the repeat, so its behavior depends
    # on durable condition metadata rather than an in-memory cast context.
    service = CombatService(ROOT, tmp_path)
    table = TabletopService(service, tmp_path)
    pin_dice(target_turn.engine, [20 if repeat_succeeds else 1])
    assert act(table, mid, "end")["status"] == "COMMITTED"
    loaded = _reload(tmp_path, mid)
    saves = _pill_saves(loaded.engine)
    assert len(saves) == 2
    repeat = saves[-1]
    assert repeat.payload["reason"] == f"SAVE:{repeat.source_definition_id}:CON"
    assert repeat.payload["dc"] == 16
    assert repeat.payload["success"] is repeat_succeeds
    target_end = next(event for event in loaded.engine.events
                      if event.event_type == "TURN_ENDED" and event.actor_id == RIGHT
                      and event.sequence > repeat.sequence)
    assert target_end.sequence > repeat.sequence

    remaining = _condition(loaded.engine, POISONED)
    removals = [event for event in loaded.engine.events
                if event.event_type == "CONDITION_REMOVED"
                and event.payload.get("instance_id") == original["instance_id"]]
    if repeat_succeeds:
        assert remaining is None
        removal, = removals
        assert removal.actor_id == RIGHT and removal.target_ids == (RIGHT,)
        assert removal.payload["repeat_save"] is True
        assert removal.payload["checkpoint"] == "END_OF_TURN"
        assert repeat.sequence < removal.sequence < target_end.sequence
    else:
        assert remaining.model_dump(mode="json") == original
        assert not removals
    _assert_replay(loaded)


def test_venom_failed_repeats_keep_condition_until_exact_ten_round_cap(tmp_path, pin_dice):
    table, mid, before, loaded = _cast_pill(tmp_path, pin_dice)
    original = _condition(loaded.engine, POISONED).model_dump(mode="json")
    deadline = (before.state.round_number + 10, before.state.current_slot_index)
    repeat_count = 0
    for _ in range(10 * len(before.state.initiative_order)):
        current = loaded.engine
        assert (current.state.round_number, current.state.current_slot_index) < deadline
        if current.state.current_actor_id == RIGHT:
            pin_dice(current, [1])
            repeat_count += 1
        assert act(table, mid, "end")["status"] == "COMMITTED"
        loaded = _reload(tmp_path, mid)
        assert len(_pill_saves(loaded.engine)) == 1 + repeat_count
        assert all(event.payload["success"] is False for event in _pill_saves(loaded.engine))
        clock = (loaded.engine.state.round_number, loaded.engine.state.current_slot_index)
        if clock < deadline:
            assert _condition(loaded.engine, POISONED).model_dump(mode="json") == original
        else:
            assert clock == deadline
            assert _condition(loaded.engine, POISONED) is None
            break
    else:
        raise AssertionError("the duration did not expire at its ten-round deadline")
    assert repeat_count == 10
    removal, = [event for event in loaded.engine.events
                if event.event_type == "CONDITION_REMOVED"
                and event.payload.get("instance_id") == original["instance_id"]]
    assert removal.payload["checkpoint"] == "START_OF_TURN"
    assert not removal.payload.get("repeat_save")
    _assert_replay(loaded)


def test_venom_initial_success_keeps_its_short_condition_without_repeat(tmp_path, pin_dice):
    table, mid, _before, loaded = _cast_pill(tmp_path, pin_dice, initial_success=True)
    condition = _condition(loaded.engine, POISONED)
    assert condition.expires_on == "START_OF_SOURCE_NEXT_TURN"
    assert "repeat_save" not in condition.data
    _assert_replay(loaded)
    original_id = condition.instance_id
    for _ in loaded.engine.state.initiative_order:
        assert act(table, mid, "end")["status"] == "COMMITTED"
        loaded = _reload(tmp_path, mid)
        assert len(_pill_saves(loaded.engine)) == 1
        if loaded.engine.state.current_actor_id == LEFT:
            assert _condition(loaded.engine, POISONED) is None
            break
        assert _condition(loaded.engine, POISONED) is not None
    else:
        raise AssertionError("the source did not receive its next turn")
    removal, = [event for event in loaded.engine.events
                if event.event_type == "CONDITION_REMOVED"
                and event.payload.get("instance_id") == original_id]
    assert removal.actor_id == LEFT
    assert removal.payload["checkpoint"] == "START_OF_TURN"
    assert not removal.payload.get("repeat_save")
    _assert_replay(loaded)


def _shared_save_context(engine, fail_effects, *, ability_duration=None, cl=7):
    """A synthetic delivery around unmodified effect rows exercises shared saves."""
    actor, target = engine.state.actors[ME], engine.state.actors[FOE]
    typed = {"source": "test:p15.shared_save", "numbers": {"pb": 4, "save_dc": 100, "cl": cl},
             "duration": ability_duration or {"kind": "instant"},
             "effects": [{"type": "save", "ability": "con", "on_fail": fail_effects, "on_success": []}]}
    action = ActionDefinition(source_definition_id="action:typed.p15.shared_save", display_name="Duration test",
                              owner_id=ME, economy=EconomyKind.ACTION, resolution_kind="TYPED",
                              target_kind="HOSTILE_ENTITY", range_ft=60, parameters={"typed": typed})
    return typed_executor.Context(engine, actor, action, None, typed, [target], target, {})


def _fail_shared_save(ctx, save=None):
    script(ctx.engine, [1])
    typed_executor.block_save(ctx, save or ctx.typed["effects"][0])
    event = next(event for event in reversed(ctx.engine.events) if event.event_type == "SAVE_ROLLED")
    assert event.payload["success"] is False


def test_heavens_roar_keeps_deafness_minute_separate_from_concentration_turn():
    engine = duel([])
    save = deepcopy(mechanics()[ROAR]["effects"][0])
    original = deepcopy(save)
    ctx = _shared_save_context(engine, save["on_fail"])
    applied_round, applied_slot = engine.state.round_number, engine.state.current_slot_index
    owner_turn = engine.state.actors[ME].turns_started
    _fail_shared_save(ctx, save)
    assert save == original
    deafness = _condition(engine, DEAFENED, FOE)
    concentration = _condition(engine, CONCENTRATION_MODE, FOE)
    assert effect_durations.parse_round(deafness.expires_on) == (applied_round + 10, applied_slot)
    assert deafness.data["repeat_save"] == {"ability": "CON", "when": "end", "dc": 100}
    assert concentration.expires_on == f"END_OF_SOURCE_TURN_AT:{owner_turn + 1}"
    assert concentration.data["rule"]["concentration_mode"] == "DISADVANTAGE"
    # Source's casting turn ends; then target's turn; then source's NEXT turn.
    engine.end_turn()
    assert _condition(engine, CONCENTRATION_MODE, FOE) is not None
    engine.end_turn()
    assert _condition(engine, CONCENTRATION_MODE, FOE) is not None
    engine.end_turn()
    assert _condition(engine, CONCENTRATION_MODE, FOE) is None
    assert _condition(engine, DEAFENED, FOE) is not None


@pytest.mark.parametrize("duration,by_cl,rounds", [
    ("one_minute", None, 10),
    ({"kind": "minutes", "amount": 2}, None, 20),
    ({"kind": "minutes", "amount": 10}, None, 100),
    ({"kind": "hours", "amount": 1}, None, 600),
    ({"kind": "rounds", "amount": 3}, None, 3),
    ("one_minute", [[1, 4, "one_minute"], [5, 10, {"kind": "minutes", "amount": 2}]], 20),
])
def test_supported_counted_effect_duration_precedes_other_effects_turn_prose(duration, by_cl, rounds):
    engine = duel([])
    effect = {"type": "condition", "condition": "poisoned", "duration": duration,
              "evidence": "Poisoned for the stated duration; the separate penalty lasts until the end of your next turn.",
              "repeat_save": {"ability": "CON", "when": "end"},
              "condition_data": {"label": "Duration test"}}
    if by_cl is not None:
        effect["duration_by_cl"] = by_cl
    original = deepcopy(effect)
    ctx = _shared_save_context(engine, [effect])
    _fail_shared_save(ctx)
    condition = _condition(engine, POISONED, FOE)
    assert effect_durations.parse_round(condition.expires_on) == (
        engine.state.round_number + rounds, engine.state.current_slot_index)
    assert condition.data["repeat_save"] == {"ability": "CON", "when": "end", "dc": 100}
    assert condition.data["label"] == "Duration test"
    assert effect == original


@pytest.mark.parametrize("mechanic_id,effect_index", [
    ("TAL_LIGHTNING_COURT_OF_CHARGED_PATHS", 2),
    ("TAL_LIGHTNING_LIGHTNING_SOVEREIGN_INCARNATION", 4),
    ("TAL_VOID_VOID_SOVEREIGN_INCARNATION", 2),
])
def test_actual_states_keep_their_minute_despite_other_creatures_turn_prose(mechanic_id, effect_index):
    engine = duel([])
    mechanic = mechanics()[mechanic_id]
    # Find the actual state by type: removal of the erroneous walking-speed
    # projection changes row offsets, not the printed one-minute lifetime.
    effect = deepcopy(next(row for row in mechanic["effects"] if row.get("type") == "state"))
    original = deepcopy(effect)
    assert effect["type"] == "state" and effect["duration"] == "one_minute"
    ctx = _shared_save_context(engine, [], ability_duration=mechanic["duration"])
    application_clock = (engine.state.round_number, engine.state.current_slot_index)
    # Exercise the state block's real caller of effect_expiry, not just the
    # duration helper. Keep each production effect row byte-for-byte equivalent.
    states.state(ctx, effect)
    condition = states.active(engine, ctx.actor, effect["name"])
    assert condition is not None
    assert effect_durations.parse_round(condition.expires_on) == (
        application_clock[0] + 10, application_clock[1])
    assert condition.data["range_for"] == effect.get("range_for", {})
    assert condition.data["ends_if_incapacitated"] is bool(effect.get("ends_if_incapacitated"))
    assert effect == original
    stored = condition.model_dump(mode="json")
    engine.end_turn()
    engine.end_turn()
    retained = states.active(engine, ctx.actor, effect["name"])
    assert retained is not None
    assert retained.model_dump(mode="json") == stored


def test_explicit_expiry_override_still_precedes_counted_duration():
    engine = duel([])
    ctx = _shared_save_context(engine, [{"type": "condition", "condition": "poisoned",
        "duration": "one_minute", "expires_on": "END_OF_CURRENT_TURN"}])
    _fail_shared_save(ctx)
    assert _condition(engine, POISONED, FOE).expires_on == "END_OF_CURRENT_TURN"
    engine.end_turn()
    assert _condition(engine, POISONED, FOE) is None


def test_explicit_target_next_start_keeps_its_holder_anchor_off_turn():
    engine = duel([])
    engine.end_turn()
    assert engine.state.current_actor_id == FOE
    next_holder_turn = engine.state.actors[FOE].turns_started + 1
    ctx = _shared_save_context(engine, [{"type": "condition", "condition": "poisoned",
        "duration": "one_minute", "expires_on": "START_OF_TARGET_NEXT_TURN"}])
    _fail_shared_save(ctx)
    assert effect_durations.parse(_condition(engine, POISONED, FOE).expires_on) == (
        "start", FOE, next_holder_turn)
    engine.end_turn()
    assert engine.state.current_actor_id == ME
    assert _condition(engine, POISONED, FOE) is not None
    engine.end_turn()
    assert engine.state.current_actor_id == FOE
    assert _condition(engine, POISONED, FOE) is None


@pytest.mark.parametrize("ability_duration,expected", [
    ({"kind": "minutes", "amount": 1, "concentration": True}, "CONCENTRATION_END"),
    ({"kind": "until_end_of_scene"}, "UNTIL_REMOVED"),
])
def test_counted_concentration_and_explicit_scene_keep_existing_semantics(ability_duration, expected):
    engine = duel([])
    effect = {"type": "condition", "condition": "poisoned"}
    if ability_duration.get("concentration"):
        effect.update(duration="one_minute", evidence="The separate penalty lasts until the end of your next turn.")
    ctx = _shared_save_context(engine, [effect], ability_duration=ability_duration)
    _fail_shared_save(ctx)
    assert _condition(engine, POISONED, FOE).expires_on == expected


@pytest.mark.parametrize("duration,after_source_end,after_target_end", [
    ("end_of_turn", False, False),
    ("until_start_of_next_turn", True, False),
    ("until_end_of_next_turn", True, False),
    ("until_end_of_your_next_turn", True, True),
])
def test_failed_save_turn_length_effects_still_expire_on_their_own_turn(duration, after_source_end, after_target_end):
    engine = duel([])
    ctx = _shared_save_context(engine, [{"type": "condition", "condition": "poisoned", "duration": duration}],
                               ability_duration={"kind": "minutes", "amount": 1})
    _fail_shared_save(ctx)
    assert _condition(engine, POISONED, FOE) is not None
    engine.end_turn()
    assert (_condition(engine, POISONED, FOE) is not None) is after_source_end
    engine.end_turn()
    assert (_condition(engine, POISONED, FOE) is not None) is after_target_end
    engine.end_turn()
    assert _condition(engine, POISONED, FOE) is None


def test_counted_reaction_effect_uses_triggering_turn_slot_not_sources_slot():
    engine = duel([])
    source_slot = engine.state.current_slot_index
    engine.end_turn()
    assert engine.state.current_actor_id == FOE
    assert engine.state.current_slot_index != source_slot
    # Resolve the shared save as an off-turn source, at the target's open turn.
    ctx = _shared_save_context(engine, [{"type": "condition", "condition": "poisoned", "duration": "one_minute",
        "evidence": "Poisoned for 1 minute; the separate penalty lasts until the end of your next turn."}])
    _fail_shared_save(ctx)
    assert effect_durations.parse_round(_condition(engine, POISONED, FOE).expires_on) == (
        engine.state.round_number + 10, engine.state.current_slot_index)
