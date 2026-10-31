"""Incarnation of the Living Forge: the optional ten-minute Temporary Temper.

The printed clause is "your Blacksmith Temporary Tempers may last for 10 minutes
instead of 1 minute". The "may" is the owner's: a Tempering Sequence performed
while Incarnation of the Living Forge stands puts the lifetime question through
the shared choice transport (combat/ext/needle.py ``ask``), the one-minute
option stays in the menu, and the chosen ten-minute temper survives a cold
reload and outlives the Incarnation's own one-minute condition, which keeps its
own printed clock. A smith who does not own the Incarnation is never asked and
keeps the chassis minute.

The Forge Marks that pay for the sequence are placed with the printed
Hammer the Mark bonus action, one per round.
"""
import pytest
from combat.gate2_runtime_models import ActionIntent
from combat.ext.blacksmith_forge import HARDENED, SOFTENED, held_condition, mark_count
from combat.ext.blacksmith_second_pass import LIVING
from combat.ext.effect_durations import parse_round, sweep
from tests.worker2_support import fixture, candidate, turn, reload, OWNER, ALLY, FOE
from tests.test_a2_blacksmith import press, setup

INCARNATION = "tianxia.talent.blacksmith.incarnation_of_the_living_forge"
TEMPERING = "tianxia.talent.blacksmith.tempering_sequence"
CHOICE = "choice:needle.blacksmith_temper_duration"
HARDENING = "Tempering Sequence: Hardening Sequence"
SOFTENING = "Tempering Sequence: Softening Sequence"


def three_marks(combat, table, mid):
    """"When a workpiece has at least 3 Forge Marks from you": the printed
    Hammer the Mark bonus action, one mark per round."""
    for _ in range(3):
        press(combat, table, mid, "Hammer the Mark")
        turn(table, mid, ALLY)
        turn(table, mid, OWNER)


def awaken(combat, table, mid):
    press(combat, table, mid, "Incarnation of the Living Forge")


def temper_prompt(prompts):
    return next(p for p in prompts if p["context"]["reaction_source_id"] == CHOICE)


def advance_rounds(table, mid, rounds):
    """A full initiative round per iteration: the ally's turn, then the owner's."""
    for _ in range(rounds):
        turn(table, mid, ALLY)
        turn(table, mid, OWNER)


def execute(combat, mid, name, target=None):
    session = combat._load_session(mid)
    row = candidate(combat, mid, name, target=target)
    session.mechanical.execute_intent(ActionIntent(
        intent_id="temper:" + name, actor_id=row.actor_id, decision_id=row.decision_id,
        candidate_id=row.candidate_id, state_version=row.state_version,
        target_ids=row.target_ids, destination=row.destination))


@pytest.mark.parametrize("sequence,condition", [
    (HARDENING, HARDENED),
    (SOFTENING, SOFTENED),
])
def test_the_owner_picks_the_ten_minute_temper_and_it_outlives_the_incarnation(tmp_path, sequence, condition):
    combat, table, mid = fixture(tmp_path, [INCARNATION, TEMPERING], bundle_transform=setup)
    three_marks(combat, table, mid)
    awaken(combat, table, mid)
    prompts = press(combat, table, mid, sequence, picks={CHOICE: ["ten_minutes"]})
    # The printed "may" was put to the owner, with both lifetimes in the menu.
    prompt = temper_prompt(prompts)
    offered = {option["id"] for option in prompt["choice"]["options"]}
    assert offered == {"one_minute", "ten_minutes"}
    assert prompt["choice"]["allow_decline"]
    assert "Incarnation of the Living Forge" in prompt["moment"]
    assert prompt["reactor"] == combat._load_session(mid).engine.state.actors[OWNER].display_name

    engine = reload(tmp_path, mid)
    smith = engine.state.actors[OWNER]
    temper = held_condition(smith, condition)
    assert temper is not None, "the sequence's Temporary Temper stands after a cold reload"
    assert (temper.data or {}).get("lifetime") == "ten_minutes"
    due_round, due_slot = parse_round(temper.expires_on)
    assert (due_round, due_slot) == (engine.state.round_number + 100, engine.state.current_slot_index)

    # The Incarnation keeps its own printed one minute: the temper is not
    # truncated by it, and it does not extend the Incarnation.
    living = held_condition(smith, LIVING)
    assert living is not None
    assert parse_round(living.expires_on) == (engine.state.round_number + 10, engine.state.current_slot_index)

    # Past the Incarnation's own minute (10 rounds), the chosen temper still stands.
    advance_rounds(table, mid, 11)
    engine = reload(tmp_path, mid)
    smith = engine.state.actors[OWNER]
    assert held_condition(smith, LIVING) is None, "the Incarnation's own minute ended"
    temper = held_condition(smith, condition)
    assert temper is not None, "the ten-minute temper is not truncated by the Incarnation's expiry"

    # The recognized round clock removes it at exactly its own hundredth round.
    assert parse_round(temper.expires_on) == (due_round, due_slot)
    engine.state.round_number = due_round - 1
    sweep(engine, smith, "START_OF_TURN")
    assert held_condition(smith, condition) is not None
    engine.state.round_number = due_round
    sweep(engine, smith, "START_OF_TURN")
    assert held_condition(smith, condition) is None, "the ten-minute clock ends the temper"


def test_the_one_minute_option_stays_in_the_menu_and_is_honored(tmp_path):
    combat, table, mid = fixture(tmp_path, [INCARNATION, TEMPERING], bundle_transform=setup)
    three_marks(combat, table, mid)
    awaken(combat, table, mid)
    prompts = press(combat, table, mid, HARDENING, picks={CHOICE: ["one_minute"]})
    assert temper_prompt(prompts)["choice"]["options"][0]["id"] == "one_minute"
    engine = reload(tmp_path, mid)
    temper = held_condition(engine.state.actors[OWNER], HARDENED)
    assert temper is not None
    assert "lifetime" not in (temper.data or {})
    assert parse_round(temper.expires_on) == (engine.state.round_number + 10, engine.state.current_slot_index)
    advance_rounds(table, mid, 11)
    assert held_condition(reload(tmp_path, mid).state.actors[OWNER], HARDENED) is None


def test_the_printed_may_can_be_declined_for_the_chassis_minute(tmp_path):
    combat, table, mid = fixture(tmp_path, [INCARNATION, TEMPERING], bundle_transform=setup)
    three_marks(combat, table, mid)
    awaken(combat, table, mid)
    press(combat, table, mid, HARDENING, picks={CHOICE: None})
    engine = reload(tmp_path, mid)
    temper = held_condition(engine.state.actors[OWNER], HARDENED)
    assert temper is not None
    assert "lifetime" not in (temper.data or {})
    assert parse_round(temper.expires_on) == (engine.state.round_number + 10, engine.state.current_slot_index)


def test_without_the_incarnation_no_question_is_asked_and_the_minute_stands(tmp_path):
    """A smith who does not own the Incarnation keeps the chassis minute: no
    question, no ten-minute clock, and no creature but the owner carries anything
    the sequence placed."""
    combat, table, mid = fixture(tmp_path, [TEMPERING], bundle_transform=setup)
    three_marks(combat, table, mid)
    prompts = press(combat, table, mid, HARDENING)
    assert not any(p["context"]["reaction_source_id"] == CHOICE for p in prompts)
    engine = reload(tmp_path, mid)
    temper = held_condition(engine.state.actors[OWNER], HARDENED)
    assert temper is not None
    assert "lifetime" not in (temper.data or {})
    assert parse_round(temper.expires_on) == (engine.state.round_number + 10, engine.state.current_slot_index)
    assert held_condition(engine.state.actors[ALLY], HARDENED) is None
    assert held_condition(engine.state.actors[FOE], HARDENED) is None


def test_the_built_in_ai_takes_the_printed_ten_minute_lifetime(tmp_path):
    """An AI-controlled smith selects from the legal lifetimes on its own; the
    menu it sees is the same two options, the printed longer one first."""
    combat, table, mid = fixture(tmp_path, [INCARNATION, TEMPERING], bundle_transform=setup)
    three_marks(combat, table, mid)
    awaken(combat, table, mid)
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode="LOCAL_AUTO")
    execute(combat, mid, HARDENING)
    engine = reload(tmp_path, mid)
    temper = held_condition(engine.state.actors[OWNER], HARDENED)
    assert temper is not None, "the AI performed the Hardening Sequence"
    assert (temper.data or {}).get("lifetime") == "ten_minutes"
    assert parse_round(temper.expires_on) == (engine.state.round_number + 100, engine.state.current_slot_index)
