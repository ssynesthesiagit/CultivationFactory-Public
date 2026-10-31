"""Manacle Method (Chains, row C15): the printed consent gate decides whether a save is rolled.

"You form manacles ... on one willing, incapacitated, Grappled, Restrained, or Prone creature. If the target is
unwilling and not incapacitated, it makes a Strength saving throw." A willing creature says so (the shared consent
question of combat/ext/willing_targets.py) and an incapacitated one cannot refuse, so neither rolls a save; only an
unwilling creature that is Grappled, Restrained or Prone makes it, failing into the same Bound + escape record. An
unwilling standing creature is not a legal target: its refusal is an illegal use with no save and no chains. A target already Restrained by one
of the caster's Chains effects still has Disadvantage on its first escape check, because Bound is the printed
"Disadvantage on checks to escape" state. Every case commits through the table service and cold-reloads.
"""
import pytest

from combat.ext import escape_options
from combat.gate4_adapters import ManualControllerAdapter
from tests import auto_worker1_support as S
from tests.hunt15_support import ALLY, LEFT, RIGHT, act

MANACLE = "tianxia.talent.chains.manacle_method"
PRISON = "tianxia.talent.chains.chain_prison"
BOUND = "condition:typed.bound"
ESCAPE = "condition:typed.escape_option"
FAIL_DC, PASS_DC = 100, -40


def manacle_saves(engine, actor_id):
    return [e for e in engine.events if e.event_type == "SAVE_ROLLED" and e.actor_id == actor_id
            and "manacle_method" in (e.source_definition_id or "")]


def conditions(engine, actor_id):
    return {c.condition_id for c in engine.state.actors[actor_id].conditions.values()}


def play(combat, table, mid, answers, *, target_id=RIGHT):
    """Answer the printed consent question, then commit Manacle Method on ``target_id``."""
    result, prompts = S.resolve(lambda sent: act(table, mid, "Manacle Method", sent, target_id=target_id), answers)
    assert result["status"] == "COMMITTED", result
    return S.reload(combat, mid), prompts


def test_a_willing_creature_is_asked_and_bound_without_a_save(tmp_path):
    combat, table, mid = S.fight(tmp_path, [MANACLE], left_save_dc=FAIL_DC, ally=())
    engine, prompts = play(combat, table, mid, {"choice:willing.consent": ["accept"]})
    assert [p["context"]["reaction_source_id"] for p in prompts] == ["choice:willing.consent"]
    assert manacle_saves(engine, RIGHT) == []
    assert {BOUND, ESCAPE} <= conditions(engine, RIGHT)
    assert not (conditions(engine, ALLY) & {BOUND, ESCAPE})


def test_an_incapacitated_creature_is_bound_without_a_save_and_is_never_asked(tmp_path):
    combat, table, mid = S.fight(tmp_path, [MANACLE], left_save_dc=FAIL_DC,
                                 prepare=[{"type": "condition", "condition": "incapacitated",
                                           "applies_to": "target", "duration": {"kind": "until_removed"}}])
    S.resolve(lambda sent: act(table, mid, "Prepare", sent, target_id=RIGHT))
    assert "condition:typed.incapacitated" in conditions(S.reload(combat, mid), RIGHT)
    engine, prompts = play(combat, table, mid, {})
    assert prompts == []
    assert manacle_saves(engine, RIGHT) == []
    assert {BOUND, ESCAPE} <= conditions(engine, RIGHT)


def test_an_unwilling_standing_creature_is_not_a_legal_target_so_its_refusal_rolls_no_save_and_binds_nothing(tmp_path):
    combat, table, mid = S.fight(tmp_path, [MANACLE], left_save_dc=FAIL_DC)
    engine, prompts = play(combat, table, mid, {"choice:willing.consent": ["refuse"]})
    assert [p["context"]["reaction_source_id"] for p in prompts] == ["choice:willing.consent"]
    assert manacle_saves(engine, RIGHT) == []
    assert not (conditions(engine, RIGHT) & {BOUND, ESCAPE})


def grappled_fight(tmp_path, *, left_save_dc):
    """A fight whose target (RIGHT) is Grappled, so an unwilling refusal is a legal save."""
    combat, table, mid = S.fight(tmp_path, [MANACLE], left_save_dc=left_save_dc,
                                 prepare=[{"type": "condition", "condition": "grappled",
                                           "applies_to": "target", "duration": {"kind": "until_removed"}}])
    S.resolve(lambda sent: act(table, mid, "Prepare", sent, target_id=RIGHT))
    assert "condition:typed.grappled" in conditions(S.reload(combat, mid), RIGHT)
    return combat, table, mid


def test_an_unwilling_grappled_creature_makes_the_printed_strength_save_and_fails_into_the_bound_record(tmp_path):
    combat, table, mid = grappled_fight(tmp_path, left_save_dc=FAIL_DC)
    engine, prompts = play(combat, table, mid, {"choice:willing.consent": ["refuse"]})
    assert [p["context"]["reaction_source_id"] for p in prompts] == ["choice:willing.consent"]
    (save,) = manacle_saves(engine, RIGHT)
    assert save.payload["reason"].endswith(":STR") and save.payload["dc"] == FAIL_DC and save.payload["success"] is False
    assert {BOUND, ESCAPE} <= conditions(engine, RIGHT)


def test_an_unwilling_grappled_creature_that_makes_the_save_keeps_no_chains(tmp_path):
    combat, table, mid = grappled_fight(tmp_path, left_save_dc=PASS_DC)
    engine, _ = play(combat, table, mid, {"choice:willing.consent": ["refuse"]})
    (save,) = manacle_saves(engine, RIGHT)
    assert save.payload["success"] is True
    assert not (conditions(engine, RIGHT) & {BOUND, ESCAPE})
    assert escape_options.options(engine.state.actors[RIGHT]) == []


@pytest.mark.parametrize("answer", ["accept", "refuse"])
def test_a_target_already_restrained_by_ones_chains_has_disadvantage_on_its_first_escape_check(tmp_path, answer):
    combat, table, mid = S.fight(tmp_path, [MANACLE, PRISON], left_save_dc=FAIL_DC)
    S.resolve(lambda sent: act(table, mid, "Chain Prison", sent, target_id=RIGHT))
    restrained = S.reload(combat, mid)
    assert "condition:typed.restrained" in conditions(restrained, RIGHT)
    # The prison spent this turn's Action; the next Manacle Method is the caster's next turn.
    assert act(table, mid, "end")["status"] == "COMMITTED"
    S.turn(table, mid, LEFT)
    engine, _ = play(combat, table, mid, {"choice:willing.consent": [answer]})
    ((_key, record),) = escape_options.options(engine.state.actors[RIGHT])
    assert record.data["abilities"] == ["STR", "DEX"]
    assert record.data["skills"] == {"STR": "Athletics", "DEX": "Acrobatics"}
    S.turn(table, mid, RIGHT)
    result, prompts = S.resolve(lambda sent: act(table, mid, "Break free", sent),
                                {"choice:needle.escape_ability": ["STR"]})
    assert result["status"] == "COMMITTED"
    assert [p["context"]["reaction_source_id"] for p in prompts] == ["choice:needle.escape_ability"]
    after = S.reload(combat, mid)
    (check,) = [e for e in after.events if e.event_type == "CHECK_ROLLED"
                and (e.payload.get("skill") or "") in ("Athletics", "Acrobatics")]
    assert check.payload["actor"]["mode"] == "DISADVANTAGE"
    assert check.payload["actor"]["discarded"], "disadvantage keeps the lower of two dice"
    assert check.payload["skill"] == "Athletics" and check.payload["dc"] == FAIL_DC


@pytest.mark.parametrize("answer", ["accept", "refuse"])
def test_ai_caster_pauses_for_manual_recipient_consent_and_commits_answer(tmp_path, answer):
    combat, table, mid = S.fight(tmp_path, [MANACLE], left_save_dc=FAIL_DC)
    state = table.state(mid)
    cid = next(o["candidate_id"] for group in state["menu"]["actions"]
               if group["label"] == "Manacle Method" for o in group["options"]
               if RIGHT in o.get("target_ids", []))
    real = combat.controller

    class ChooseManacle:
        def choose_primary_action(self, context):
            candidate = next((row for row in context.legal_candidates if row.candidate_id == cid), None)
            adapter = ManualControllerAdapter(
                lambda _: (cid, tuple(candidate.option_ids) if candidate else ()))
            return adapter.choose_primary_action(context)

        def __getattr__(self, name):
            return getattr(real, name)

    combat.controller = ChooseManacle()
    combat.set_controller_mode(mid, actor_id=LEFT, controller_mode="LOCAL_AUTO")
    before = S.reload(combat, mid)
    assert RIGHT in before.typed_ask_reactors
    result = table.auto_step(mid, table.state(mid)["last_sequence"], [])
    assert result["status"] == "REACTION_REQUIRED", result
    prompt = result["reaction"]
    assert prompt["context"]["reactor_id"] == RIGHT
    assert "Manacle Method" in str(prompt) and "Keeper" in str(prompt) and "Visitor" in str(prompt)
    assert "refuse" in str(prompt).lower() or "accept" in str(prompt).lower()
    answer_row = {**prompt["context"], "selection": "USE",
                  "option_ids": ["accept" if answer == "accept" else "refuse"]}
    result = table.auto_step(mid, table.state(mid)["last_sequence"], [answer_row])
    assert result["status"] == "COMMITTED", result
    engine = S.reload(combat, mid)
    assert bool({BOUND, ESCAPE} & conditions(engine, RIGHT)) is (answer == "accept")
    assert manacle_saves(engine, RIGHT) == []
