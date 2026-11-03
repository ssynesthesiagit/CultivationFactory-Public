"""Black-Claw Manifestation on the Unarmed Strike row (feedback desk FD-13).

Printed (TAL_DAEMONIC_CULTIVATION_BLACK_CLAW_MANIFESTATION):
  "Your Unarmed Strikes may deal Slashing, Piercing, Necrotic, or Force damage. Once per
   turn when you hit with an Unarmed Strike or natural weapon, choose one: ..."
The manifestation used to be invisible on the natural.iron_fist row, and a human seat's
once-per-turn benefit was not clearly shown as available/used. These tests use the real
table service and a real compiled Iron Fist character.
"""
import pytest

from combat import ext
from combat.gate5_service import CombatService
from combat.typed_executor import CONDITION_PREFIX
from tests.h1_support import ROOT
from tests.r1i_service_support import fixture, OWNER, FOE

TALENTS = [
    "TAL_DAEMONIC_CULTIVATION_DEMON_SEED",
    "TAL_DAEMONIC_CULTIVATION_BLACK_CLAW_MANIFESTATION",
    "tianxia.path.body_refining.feature.iron_fist",
    "tianxia.path.body_refining.feature.extra_attack",  # 4 Unarmed Strikes at CL17: one prompt, not four
]
CLAW_STATE = CONDITION_PREFIX + "state.black_claw_manifestation"


def _option(table, mid, label, exact=True):
    group = next(g for g in table.state(mid)["menu"]["actions"]
                 if (g["label"] == label if exact else label in g["label"]))
    return group, group["options"][0]["candidate_id"]


def _activate(combat, table, mid, send, commit):
    """Demon Seed, then its Black-Claw manifestation on the owner's next turn."""
    commit(_option(table, mid, "Demon Seed")[1])
    commit(table.state(mid)["menu"]["end_turn"])
    while table.state(mid)["menu"]["actor_id"] != OWNER:
        commit(table.state(mid)["menu"]["end_turn"])
    commit(_option(table, mid, "Black-Claw Manifestation")[1])


def _owner_condition(state, condition_id):
    actor = next(row for row in state["presentation"]["actors"] if row["entity_id"] == OWNER)
    return next(row for row in actor["conditions"] if row["condition_id"] == condition_id)


def _attack(table, mid, send, *, benefit="temp_hp", damage_type="necrotic"):
    """Commit the Iron Fist Attack action, answering every prompt through the table."""
    group, cid = _option(table, mid, "Iron Fist attack", exact=False)
    answers, prompts = [], []
    for _ in range(24):
        result = send(cid, answers)
        if result["status"] == "COMMITTED":
            return group, prompts
        assert result["status"] == "REACTION_REQUIRED", result
        prompt = result["reaction"]
        source = prompt["context"]["reaction_source_id"]
        prompts.append(prompt)
        answer = {**prompt["context"], "selection": "USE"}
        options = [option["id"] for option in prompt["choice"]["options"]]
        if source == "choice:needle.black_claw":
            answer["option_ids"] = [benefit]
        elif source == "choice:needle.black_claw_damage":
            answer["option_ids"] = [damage_type]
        else:  # Iron Fist's own per-strike choice, when the claw menu was declined
            answer["option_ids"] = options[:1]
        answers.append(answer)
    raise AssertionError("too many prompts")


def _claw(tmp_path):
    combat, table, mid, send, commit = fixture(tmp_path, TALENTS, foe_ac=0, seed="BLACKCLAW-ROWS")
    return combat, table, mid, send, commit, tmp_path


@pytest.fixture()
def claw(tmp_path):
    return _claw(tmp_path)


def test_row_names_black_claw_and_offers_its_damage_types_then_reloads(claw):
    combat, table, mid, send, commit, tmp_path = claw
    # Before the manifestation, the row is untouched (inert for a character without it).
    seed_group, _ = _option(table, mid, "Iron Fist attack", exact=False)
    assert "Black Claw" not in seed_group["label"]
    assert "Black-Claw Manifestation is active" not in seed_group["description"]

    _activate(combat, table, mid, send, commit)

    group, _cid = _option(table, mid, "Iron Fist attack", exact=False)
    assert group["label"] == "Iron Fist attack (Black Claw)"
    assert "Necrotic or Force damage" in group["description"]
    assert "once-per-turn on-hit choice is still available" in group["description"]
    assert "still available" in _owner_condition(table.state(mid), CLAW_STATE)["detail"]

    group, prompts = _attack(table, mid, send)
    sources = [prompt["context"]["reaction_source_id"] for prompt in prompts]
    assert sources.count("choice:needle.black_claw_damage") == 1
    assert sources.count("choice:needle.black_claw") == 1

    damage_prompt = next(prompt for prompt in prompts
                         if prompt["context"]["reaction_source_id"] == "choice:needle.black_claw_damage")
    offered = {option["id"]: option["label"] for option in damage_prompt["choice"]["options"]}
    assert {"slashing", "piercing", "necrotic", "force"} <= set(offered)
    assert offered["necrotic"] == "Necrotic damage"
    assert offered["force"] == "Force damage"

    engine = combat._load_session(mid).engine
    assert len([event for event in engine.events if event.event_type == "ATTACK_ROLLED"]) == 4
    committed = [event.payload.get("damage_type") for event in engine.events
                 if event.event_type == "DAMAGE_COMMITTED" and event.actor_id == OWNER]
    assert committed[0].lower() == "necrotic"
    assert any(event.event_type == "TEMP_HP_GRANTED" and event.actor_id == OWNER
               and int(event.payload.get("offered") or 0) == 4 for event in engine.events)

    after = table.state(mid)
    assert "choice is spent this turn" in _owner_condition(after, CLAW_STATE)["detail"]

    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    owner = loaded.engine.state.actors[OWNER]
    assert owner.turn_flags.get(f"black_claw:{loaded.engine.state.round_number}:{loaded.engine.state.current_slot_index}")
    row = next(action for action in loaded.engine.action_catalog.values()
               if ".natural.iron_fist" in action.source_definition_id)
    assert "choice is spent this turn" in ext.run("attack_state_rows", loaded.engine, owner,
                                       row.model_dump(mode="json"))[0][0]["note"]
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_declining_the_first_hit_keeps_that_turns_allowance_open(claw):
    """Declining takes no benefit, so the turn's once-per-turn allowance stays open and the next hit asks again."""
    combat, table, mid, send, commit, tmp_path = claw
    _activate(combat, table, mid, send, commit)
    group, cid = _option(table, mid, "Iron Fist attack", exact=False)
    answers, sources = [], []
    for _ in range(24):
        result = send(cid, answers)
        if result["status"] == "COMMITTED":
            break
        prompt = result["reaction"]
        source = prompt["context"]["reaction_source_id"]
        sources.append(source)
        options = [option["id"] for option in prompt["choice"]["options"]]
        selection = "DECLINE" if source == "choice:needle.black_claw" else "USE"
        answers.append({**prompt["context"], "selection": selection,
                        "option_ids": [] if selection == "DECLINE" else options[:1]})
    # Regression: a declined menu must not set the turn flag, so a later hit in the
    # same turn is offered the choice again (main's rule), not silently skipped.
    assert sources.count("choice:needle.black_claw") >= 2
    engine = combat._load_session(mid).engine
    assert not any(event.event_type == "TEMP_HP_GRANTED" and int(event.payload.get("offered") or 0) == 4
                   for event in engine.events)
    owner = engine.state.actors[OWNER]
    assert not owner.turn_flags.get(f"black_claw:{engine.state.round_number}:{engine.state.current_slot_index}")
    row = next(action for action in engine.action_catalog.values() if ".natural.iron_fist" in action.source_definition_id)
    note = ext.run("attack_state_rows", engine, owner, row.model_dump(mode="json"))[0][0]["note"]
    assert "still available this turn" in note
    assert "spent" not in note


def test_ai_seat_takes_the_benefit_without_a_prompt(claw):
    combat, table, mid, send, commit, tmp_path = claw
    _activate(combat, table, mid, send, commit)
    _group, cid = _option(table, mid, "Iron Fist attack", exact=False)
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode="LOCAL_AUTO")
    result = send(cid, [], auto=True)
    assert result["status"] == "COMMITTED"
    engine = combat._load_session(mid).engine
    owner = engine.state.actors[OWNER]
    assert owner.turn_flags.get(f"black_claw:{engine.state.round_number}:{engine.state.current_slot_index}")
    assert any(event.event_type == "TEMP_HP_GRANTED" and event.actor_id == OWNER
               and int(event.payload.get("offered") or 0) == 4 for event in engine.events)
