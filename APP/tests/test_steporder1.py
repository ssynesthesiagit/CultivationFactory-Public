"""Ordered movement uses compiled data and journaled table choices, not ability ids.

Synthetic sheets/stores only. The hostile-patient fixture widens only its sealed
recipient domain to make the normally ally-only treatment exemption observable.
"""
import pytest
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatServiceError
from combat.gate2_engine import SYSTEM_OPPORTUNITY
from combat.typed_executor import mark_condition_id
from tests import auto_worker1_support as S

REELING = "TAL_DRUNKEN_STYLE_REELING_STEP"
PHYSICIAN = "insight.battlefield-physician"
PULSE = "LIFE_BASE_READ_THE_PULSE"
WITNESS = "actor:factory.auto111-witness"
PREFIX = "choice:needle."
LOOSE = "TAL_DRUNKEN_STYLE_LOOSE_CUP_FOOTWORK"
CHAOS = "TAL_DRUNKEN_STYLE_CHAOS_STEP_AWAKENING"
EMPTY = "TAL_DRUNKEN_STYLE_EMPTY_CUP_STANCE"


def _sheet(physician=False, speed=30):
    def edit(doc, aid):
        if aid == S.LEFT:
            doc["ability_scores_and_statistics"]["speed"]["walking_ft"] = speed
            if physician:
                doc.setdefault("spheres_and_talents", {})["cultivation_insight_record_ids"] = [PHYSICIAN]
    return edit


def _drive(send, picks=None, observe=None):
    answers, prompts = [], []
    for _ in range(30):
        result = send(answers)
        if result["status"] != "REACTION_REQUIRED":
            assert result["status"] == "COMMITTED", result
            return prompts
        prompt = result["reaction"]
        prompts.append(prompt)
        if observe:
            observe(prompt, answers)
        choice = prompt.get("choice")
        key = prompt["context"]["reaction_source_id"]
        options = [o["id"] for o in (choice or {}).get("options", [])]
        chosen = (picks or {}).get(key)
        if chosen is None:
            chosen = [] if choice and choice.get("allow_decline") else options[:1]
        answers.append({**prompt["context"], "selection": "DECLINE" if choice and not chosen else "USE",
                        "option_ids": chosen})
    raise AssertionError("too many choices")


def _cast(c, t, m, label, picks=None, target=None, observe=None):
    prompts = _drive(lambda answers: S.act(t, m, label, answers, target_id=target), picks, observe)
    e = S.reload(c, m)
    assert c._load_session(m).verify()["status"] == "PASS"
    return e, prompts


def _picks(key, order, cell, target, exempt=None):
    out = {PREFIX + key + "_order": [order], PREFIX + key + "_move": [cell],
           PREFIX + key + "_test": [target]}
    if exempt:
        out[PREFIX + key + "_oa"] = [exempt]
    return out


def _options(prompts, key):
    return {o["id"] for p in prompts if p["context"]["reaction_source_id"] == PREFIX + key
            for o in p["choice"]["options"]}


def _oa(e):
    return [v for v in e.events if v.event_type == "REACTION_RESOLVED"
            and v.source_definition_id == SYSTEM_OPPORTUNITY]


def test_steporder_reviewed_has_order_choice():
    from tests.h1_support import sheet
    docs = [(sheet([REELING]), False), (sheet([PULSE]), True)]
    for doc, insight in docs:
        if insight:
            doc["spheres_and_talents"]["cultivation_insight_record_ids"] = [PHYSICIAN]
        bundle = compile_character(doc, actor_id=S.LEFT)
        actions = [a for a in bundle["action_catalog"]
                   if a["parameters"].get("typed", {}).get("source") in {REELING, PULSE}]
        assert len(actions) == (2 if insight else 1)
        if insight:
            boundary = next(r for r in bundle["diagnostics"]["insights"] if r["id"] == PHYSICIAN)
            assert boundary["gm_decides"] == [
                "Ability Increase (Level Selection): Ispykcfs rltt Wabulu, Crorahmlkewf, or Cdgyhorl rtsvh by 1, to the loyeuhc gegsyoo by cgnd lmwyout Rlkkt.",
                "When you stabilize a creature, that creature gains Temporary HP equal to your Proficiency Bonus."
            ]
            assert "before or after" not in boundary["explanation"]
        else:
            assert actions[0]["parameters"]["typed"]["riders"] == []
        for action in actions:
            row = action["parameters"]["typed"]["effects"][0]
            spec = row.get("granted_movement")
            assert spec and spec["order_choice"] == ["before", "after"]
            assert spec["distance_ft"] == 10
            assert row["type"] == ("ordered_granted_movement" if insight else "drunken_reeling_step")
    # A composed treatment is sealed before the shared wrapper copies it. It
    # grants one movement, not another grant for every additional patient.
    doc = sheet([PULSE, "tianxia.talent.life.shared_infirmary_hand"])
    doc["spheres_and_talents"]["cultivation_insight_record_ids"] = [PHYSICIAN]
    bundle = compile_character(doc, actor_id=S.LEFT)
    composed = []
    for action in bundle["action_catalog"]:
        for row in action["parameters"].get("typed", {}).get("effects", []):
            if row.get("type") != "ordered_granted_movement":
                continue
            for eff in row["main_action"]["parameters"]["typed"]["effects"]:
                if eff.get("type") == "life_more_targets" and eff.get("choose_patients"):
                    composed.append(eff)
                    assert "base_effects" in eff
                    assert not any(e["type"] == "ordered_granted_movement" for e in eff["base_effects"])
    assert composed


@pytest.mark.parametrize("order", ["before", "after"])
@pytest.mark.parametrize("dc", [-40, 100])
def test_steporder_after_move_target_uses_destination_range(tmp_path, order, dc):
    c, t, m = S.fight(tmp_path, [REELING], left_save_dc=dc, ally={}, positions={
        S.LEFT: {"x": 3, "y": 6}, S.RIGHT: {"x": 2, "y": 6}, S.ALLY: {"x": 7, "y": 6}})
    target = S.RIGHT if order == "before" else S.ALLY
    before = S.reload(c, m).state.actors[S.LEFT]
    budget = before.movement_remaining_ft
    e, prompts = _cast(c, t, m, "Reeling Step",
        _picks("drunken_reeling", order, "cell:5,6", target, S.RIGHT))
    assert _options(prompts, "drunken_reeling_order") == {"before", "after"}
    assert _options(prompts, "drunken_reeling_test") == {target}, "self and wrong-position targets must not be offered"
    assert (e.state.actors[S.LEFT].position.x, e.state.actors[S.LEFT].position.y) == (5, 6)
    assert e.state.actors[S.LEFT].movement_remaining_ft == budget
    assert not e.state.actors[S.LEFT].bonus_action_available
    assert e.state.actors[S.LEFT].action_available
    saves = [v for v in e.events if v.event_type == "SAVE_ROLLED"]
    assert saves[-1].actor_id == target
    moved = next(i for i, v in enumerate(e.events) if v.event_type == "MOVEMENT_COMMITTED" and v.actor_id == S.LEFT)
    saved = next(i for i, v in enumerate(e.events) if v.event_type == "SAVE_ROLLED")
    assert (saved < moved) == (order == "before")
    marks = [v for v in e.state.actors[target].conditions.values()
             if v.condition_id == mark_condition_id("Off-Rhythm", S.LEFT)]
    assert bool(marks) == (dc == 100)
    if marks:
        assert marks[0].expires_on == "START_OF_MARKER_NEXT_TURN"
        S.turn(t, m, S.RIGHT)
        S.turn(t, m, S.LEFT)
        assert not any(v.condition_id == marks[0].condition_id
                       for v in S.reload(c, m).state.actors[target].conditions.values())


def test_steporder_out_of_range_target_is_rejected_after_movement(tmp_path):
    c, t, m = S.fight(tmp_path, [REELING], ally={}, positions={
        S.LEFT: {"x": 3, "y": 6}, S.RIGHT: {"x": 2, "y": 6}, S.ALLY: {"x": 7, "y": 6}})
    picks = _picks("drunken_reeling", "after", "cell:5,6", S.ALLY, S.RIGHT)
    checked = []
    def observe(prompt, answers):
        if prompt["context"]["reaction_source_id"] != PREFIX + "drunken_reeling_test":
            return
        assert S.RIGHT not in {o["id"] for o in prompt["choice"]["options"]}
        bad = {**prompt["context"], "selection": "USE", "option_ids": [S.RIGHT]}
        before = S.reload(c, m).state.model_dump(mode="json")
        with pytest.raises(CombatServiceError) as error:
            S.act(t, m, "Reeling Step", [*answers, bad])
        assert error.value.status_code == 422
        assert S.reload(c, m).state.model_dump(mode="json") == before
        checked.append(True)
    _cast(c, t, m, "Reeling Step", picks, observe=observe)
    assert checked == [True]


@pytest.mark.parametrize("order", ["before", "after"])
@pytest.mark.parametrize("dc", [-40, 100])
def test_steporder_visible_exemption_and_after_save_never_undo_oa(tmp_path, order, dc):
    c, t, m = S.fight(tmp_path, [REELING], left_save_dc=dc,
        positions={S.LEFT: {"x": 3, "y": 6}, S.RIGHT: {"x": 4, "y": 6}},
        extra_witness=True, witness_position={"x": 4, "y": 5})
    e, prompts = _cast(c, t, m, "Reeling Step",
        _picks("drunken_reeling", order, "cell:2,6", S.RIGHT, WITNESS))
    expected = [] if order == "before" and dc < 0 else [S.RIGHT]
    assert [v.actor_id for v in _oa(e)] == expected
    assert e.state.actors[WITNESS].reaction_available
    if order == "after":
        save = next(i for i, v in enumerate(e.events) if v.event_type == "SAVE_ROLLED")
        assert any(i < save and v.event_type == "REACTION_RESOLVED" for i, v in enumerate(e.events))
    # The chosen visible creature still reacts to the next ordinary departure.
    _drive(S.cell_send(t, m, "Move", (3, 6)))
    _drive(S.cell_send(t, m, "Move", (2, 6)))
    e = S.reload(c, m)
    assert WITNESS in [v.actor_id for v in _oa(e)]
    assert not getattr(e, "_granted_movement_oa", None)


@pytest.mark.parametrize("speed", [0, 30])
def test_steporder_zero_movement_allowed_but_speed_zero_blocks(tmp_path, speed):
    effects = [{"type": "speed", "flat": -30, "applies_to": "self", "duration": "one_minute"}] if speed == 0 else []
    c, t, m = S.fight(tmp_path, [REELING], prepare=effects, prepare_target="SELF")
    if speed == 0:
        _cast(c, t, m, "Prepare")
    engine = S.reload(c, m)
    assert engine._effective_speed(engine.state.actors[S.LEFT]) == speed
    offered = any(v.display_name == "Reeling Step" for v in engine.legal_candidates())
    assert offered == bool(speed)
    if speed:
        e, _ = _cast(c, t, m, "Reeling Step",
            _picks("drunken_reeling", "after", "cell:3,6", S.RIGHT, S.RIGHT))
        assert any(v.event_type == "SAVE_ROLLED" for v in e.events)
        assert not any(v.event_type == "MOVEMENT_COMMITTED" and v.actor_id == S.LEFT for v in e.events)
        assert e.state.actors[S.LEFT].position.x == 3


@pytest.mark.parametrize("order", ["before", "after"])
@pytest.mark.parametrize("remote", [False, True])
@pytest.mark.parametrize("repaying", [False, True])
def test_battlefield_physician_both_pulse_variants_use_resolution_position(tmp_path, order, remote, repaying):
    payment = "condition:typed.borrowed_second_payment"
    prepare = ([{"type": "mark", "mark": "Pulse Seal", "applies_to": "target",
                 "duration": {"kind": "until_removed"}}] if remote else [])
    if repaying:
        # Persist the actual repayment condition through a synthetic setup
        # action; treatment itself is compiled from the owned sheet as usual.
        prepare.append({"type": "condition", "condition": "borrowed_second_payment", "applies_to": "self",
                        "duration": {"kind": "until_start_of_your_next_turn"},
                        "condition_data": {"rule": {"speed_zero": 1, "no_reactions": 1, "no_teleport": 1}}})
    c, t, m = S.fight(tmp_path, [PULSE], sheet_edit=_sheet(True), ally={},
        prepare=prepare, prepare_target="ALLY_OR_SELF", positions={
            S.LEFT: {"x": 3, "y": 6}, S.RIGHT: {"x": 12, "y": 6},
            S.ALLY: {"x": 4 if order == "before" or repaying else 6, "y": 6}})
    if prepare:
        _cast(c, t, m, "Prepare", target=S.ALLY)
    before = S.reload(c, m)
    actor = before.state.actors[S.LEFT]
    position, budget = actor.position.model_copy(), actor.movement_remaining_ft
    if repaying:
        assert any(r.condition_id == payment for r in actor.conditions.values())
        assert before._effective_speed(actor) == 0
    label = "Read the Pulse (Pulse Seal)" if remote else "Read the Pulse"
    assert any(v.display_name == label for v in before.legal_candidates())
    e, prompts = _cast(c, t, m, label,
        _picks("battlefield_physician", order, "cell:3,6" if repaying else "cell:5,6", S.ALLY))
    assert _options(prompts, "battlefield_physician_order") == {"before", "after"}
    options = _options(prompts, "battlefield_physician_test")
    assert S.ALLY in options and S.RIGHT not in options, "keep the original treatment eligibility"
    pulse = next(i for i, v in enumerate(e.events) if v.event_type == "PASSIVE_TRIGGERED"
                 and v.target_ids == (S.ALLY,) and str(v.payload.get("log", "")).startswith("Read the Pulse:"))
    assert any(r.condition_id == mark_condition_id("Pulse Seal", S.LEFT)
               for r in e.state.actors[S.ALLY].conditions.values())
    moved = [i for i, v in enumerate(e.events) if v.event_type == "MOVEMENT_COMMITTED" and v.actor_id == S.LEFT]
    actor = e.state.actors[S.LEFT]
    if repaying:
        assert actor.position == position and actor.movement_remaining_ft == budget
        assert not moved and not _options(prompts, "battlefield_physician_move")
        assert any(r.condition_id == payment for r in actor.conditions.values())
    else:
        assert actor.position.x == 5
        assert (pulse < moved[0]) == (order == "before")
    assert not actor.bonus_action_available and actor.action_available


def test_battlefield_physician_moves_without_target_oa(tmp_path):
    def hostile_patient(bundle):
        # Production Read the Pulse is ally-only. A synthetic ANY_CREATURE
        # recipient contract exposes the printed exemption to a real reactor,
        # without changing any movement, effects or exemption data.
        if bundle["actor_id"] == S.LEFT:
            for action in bundle["action_catalog"]:
                for row in action["parameters"].get("typed", {}).get("effects", []):
                    if row.get("type") == "ordered_granted_movement":
                        row["main_action"]["target_kind"] = "ANY_CREATURE"
    c, t, m = S.fight(tmp_path, [PULSE], sheet_edit=_sheet(True), bundle_edit=hostile_patient,
        positions={S.LEFT: {"x": 3, "y": 6}, S.RIGHT: {"x": 4, "y": 6}},
        extra_witness=True, witness_position={"x": 4, "y": 5})
    e, _ = _cast(c, t, m, "Read the Pulse",
        _picks("battlefield_physician", "before", "cell:2,6", S.RIGHT))
    assert e.state.actors[S.LEFT].position.x == 2
    assert [v.actor_id for v in _oa(e)] == [WITNESS]
    assert e.state.actors[S.RIGHT].reaction_available
    _drive(S.cell_send(t, m, "Move", (3, 6)))
    _drive(S.cell_send(t, m, "Move", (2, 6)))
    assert S.RIGHT in [v.actor_id for v in _oa(S.reload(c, m))]


def test_read_pulse_without_insight_has_no_movement_or_order_choice(tmp_path):
    c, t, m = S.fight(tmp_path, [PULSE], ally={})
    e, prompts = _cast(c, t, m, "Read the Pulse", target=S.ALLY)
    assert e.state.actors[S.LEFT].position.x == 3
    assert not _options(prompts, "battlefield_physician_order")
    assert not any(v.event_type == "MOVEMENT_COMMITTED" and v.actor_id == S.LEFT for v in e.events)


@pytest.mark.parametrize("talents,flight,feet", [([], False, 10), ([LOOSE], False, 15),
    ([CHAOS], False, 20), ([LOOSE, CHAOS], False, 25), ([LOOSE, CHAOS], True, 35)])
def test_steporder_keeps_printed_movement_bounds_and_loose_cup_aim(tmp_path, talents, flight, feet):
    sovereign = ["TAL_DRUNKEN_STYLE_SOVEREIGN_CHAOS_STEP_INCARNATION"] if flight else []
    c, t, m = S.fight(tmp_path, [REELING, *talents, *sovereign],
        positions={S.LEFT: {"x": 3, "y": 6}, S.RIGHT: {"x": 5, "y": 6}})
    if flight:
        _cast(c, t, m, "Sovereign Chaos-Step Incarnation")
        S.turn(t, m, S.RIGHT)
        S.turn(t, m, S.LEFT)
    e, prompts = _cast(c, t, m, "Reeling Step",
        _picks("drunken_reeling", "after", "cell:4,6", S.RIGHT, S.RIGHT))
    movement = next(p for p in prompts if p["context"]["reaction_source_id"] == PREFIX + "drunken_reeling_move")
    costs = [int(o["label"].rsplit("(", 1)[1].split()[0]) for o in movement["choice"]["options"] if o["label"].startswith("Move to")]
    assert max(costs) == feet
    assert all(v <= feet for v in costs)
    aim = [r for r in e.state.actors[S.LEFT].conditions.values() if r.condition_id == "condition:typed.drunken_loose_cup_aim"]
    assert bool(aim) == (LOOSE in talents)
    assert not any(r.condition_id == "condition:typed.drunken_reeling_terrain" for r in e.state.actors[S.LEFT].conditions.values())
    if aim:
        assert aim[0].data["target_id"] == S.RIGHT
        terrain = [(i, v.event_type) for i, v in enumerate(e.events)
                   if v.payload.get("condition_id") == "condition:typed.drunken_reeling_terrain"]
        placed = next(i for i, kind in terrain if kind == "CONDITION_APPLIED")
        removed = next(i for i, kind in terrain if kind == "CONDITION_REMOVED")
        moved = next(i for i, v in enumerate(e.events) if v.event_type == "MOVEMENT_COMMITTED" and v.actor_id == S.LEFT)
        saved = next(i for i, v in enumerate(e.events) if v.event_type == "SAVE_ROLLED")
        assert placed < moved < removed < saved, "terrain permission is scoped to the granted path, not the main save"


def test_empty_cup_dodge_uses_the_same_data_order_choice(tmp_path):
    c, t, m = S.fight(tmp_path, [REELING, EMPTY],
        positions={S.LEFT: {"x": 3, "y": 6}, S.RIGHT: {"x": 7, "y": 6}})
    picks = _picks("drunken_reeling", "after", "cell:5,6", S.RIGHT, S.RIGHT)
    picks[PREFIX + "empty_cup_dodge_reeling"] = ["step"]
    e, prompts = _cast(c, t, m, "Dodge", picks)
    assert _options(prompts, "drunken_reeling_order") == {"before", "after"}
    assert e.state.actors[S.LEFT].bonus_action_available
    assert e.state.actors[S.LEFT].position.x == 5
    assert any(v.event_type == "SAVE_ROLLED" and v.actor_id == S.RIGHT for v in e.events)


def test_steporder_rejects_invalid_typed_order_and_distance():
    from combat.ext.granted_movement import validate_step
    row = {"order_choice": ["before", "after"], "distance_ft": 10,
           "name": "Test step", "choice_key": "test"}
    for change in ({"order_choice": ["before"]}, {"order_choice": ["during"]},
                   {"distance_ft": -5}, {"distance_ft": 10.5}):
        with pytest.raises(ValueError):
            validate_step({**row, **change})
