"""Public synthetic regressions for summon instinct journal and player-facing rules."""
import pytest

from combat.gate3_reducer import reducer_coverage_document
from combat.gate5_service import CombatService
from combat.history_feed import format_history_feed
from combat.tabletop_service import TabletopService
from test_h47_summon_table import table_fixture, candidate, guard, verify_reload, OWNER


def test_instinct_turn_commits_reloads_and_replays_from_the_table(tmp_path):
    combat, table, mid, _, commit = table_fixture(tmp_path)
    commit(candidate(table, mid, "Bone Guard Manifestation"))
    creature = guard(combat, mid)
    # All seats are manual. Ending the owner's turn must commit the automatic turn.
    while table.state(mid)["menu"]["actor_id"] != OWNER:
        commit(table.state(mid)["menu"]["end_turn"])
    commit(table.state(mid)["menu"]["end_turn"])
    fresh = CombatService(combat.source_root, tmp_path)
    fresh_table = TabletopService(fresh, tmp_path)
    verify_reload(fresh, fresh_table, mid)
    turns = [event for event in fresh._load_session(mid).engine.events
             if event.event_type == "SUMMON_TURN" and event.actor_id == creature.entity_id]
    assert turns and "acts on instinct:" in turns[-1].payload["text"]
    feed = fresh_table.events(mid, 0)["events"]
    defaults = [row for row in feed if row["event_type"] == "COMPANION_DEFAULT_APPLIED"
                and row["actor_id"] == creature.entity_id]
    assert defaults[-1]["summary"] == f"{creature.display_name} received no order, so it acts on its own instincts this turn."
    outcomes = [row for row in feed if row["event_type"] == "SUMMON_TURN"
                and row["actor_id"] == creature.entity_id]
    assert outcomes[-1]["summary"] == turns[-1].payload["text"]
    assert "default_movement" not in guard(fresh, mid).summon


def test_an_in_progress_save_with_an_uncommanded_summon_continues_on_instinct(tmp_path):
    """A fight put away before the summon moved must resume with the same instinct turn, not a Dodge default.

    The review asked for this: the instinct change reaches saved fights, so a save made while an uncommanded
    summon stands on the map has to reload, keep its recorded turns and take the creature's next turn the same
    automatic way the live table did."""
    combat, table, mid, _, commit = table_fixture(tmp_path)
    commit(candidate(table, mid, "Bone Guard Manifestation"))
    creature = guard(combat, mid)
    while table.state(mid)["menu"]["actor_id"] != OWNER:
        commit(table.state(mid)["menu"]["end_turn"])
    commit(table.state(mid)["menu"]["end_turn"])          # the uncommanded Guard takes its instinct turn

    fresh = CombatService(combat.source_root, tmp_path)
    fresh_table = TabletopService(fresh, tmp_path)
    verify_reload(fresh, fresh_table, mid)
    saved = [event for event in fresh._load_session(mid).engine.events
             if event.event_type == "SUMMON_TURN" and event.actor_id == creature.entity_id]
    assert saved and "acts on instinct:" in saved[-1].payload["text"]
    assert "default_movement" not in guard(fresh, mid).summon

    def act(candidate_id):                       # the same table, opened again from the saved fight
        answers = []
        for _ in range(16):
            menu = fresh_table.state(mid)["menu"]
            result = fresh_table.act(mid, candidate_id, menu["decision_id"], menu["state_version"], 0, answers)
            if result["status"] == "COMMITTED":
                return result
            assert result["status"] == "REACTION_REQUIRED", result
            prompt, choice = result["reaction"], (result["reaction"].get("choice") or {})
            answer = {**prompt["context"], "selection": "DECLINE"}
            if choice and not choice.get("allow_decline"):
                answer.update(selection="USE", option_ids=(choice.get("preferred") or [choice["options"][0]["id"]])[:1])
            answers.append(answer)
        raise AssertionError("too many reaction prompts")

    while fresh_table.state(mid)["menu"]["actor_id"] != OWNER:      # continue the saved fight
        assert act(fresh_table.state(mid)["menu"]["end_turn"])["status"] == "COMMITTED"
    assert act(fresh_table.state(mid)["menu"]["end_turn"])["status"] == "COMMITTED"
    continued = [event for event in fresh._load_session(mid).engine.events
                 if event.event_type == "SUMMON_TURN" and event.actor_id == creature.entity_id]
    assert len(continued) == len(saved) + 1
    assert "acts on instinct:" in continued[-1].payload["text"]
    verify_reload(fresh, fresh_table, mid)


def test_replay_coverage_declares_summon_turn_as_non_mutating():
    doc = reducer_coverage_document()
    assert {"event_type": "SUMMON_TURN", "reducer_disposition": "NO_STATE_MUTATION"} in doc["event_types"]
    assert doc["missing_event_types"] == [] and doc["status"] == "PASS"


@pytest.mark.parametrize(("event_type", "payload", "summary"), [
    ("COMPANION_DEFAULT_APPLIED", {"behavior": "INSTINCT"},
     "Bone Guard received no order, so it acts on its own instincts this turn."),
    ("COMPANION_DEFAULT_APPLIED", {"behavior": "DIRECTIVE"},
     "Bone Guard follows its order for this turn, then returns to its own instincts."),
    ("SUMMON_TURN", {"text": "Bone Guard acts on instinct: attacks Foe with Bone Strike."},
     "Bone Guard acts on instinct: attacks Foe with Bone Strike."),
])
def test_history_reports_instincts_orders_and_the_recorded_outcome(event_type, payload, summary):
    event = dict(sequence=1, actor_id="guard", target_ids=[], source_definition_id="system:combat.summon_default",
                 event_type=event_type, payload=payload)
    rows = format_history_feed([event], [], pre_state=None, post_state={},
                               actor_names={"guard": "Bone Guard"}, definition_names={})
    assert rows[0]["summary"] == summary
    assert rows[0]["detailed_breakdown_recorded"]


def test_command_button_explains_instincts_and_the_next_turn_after_reload(tmp_path):
    combat, table, mid, _, commit = table_fixture(tmp_path)
    commit(candidate(table, mid, "Bone Guard Manifestation"))
    while table.state(mid)["menu"]["actor_id"] != OWNER:
        commit(table.state(mid)["menu"]["end_turn"])
    fresh = TabletopService(CombatService(combat.source_root, tmp_path), tmp_path)
    group = next(group for group in fresh.state(mid)["menu"]["actions"] if group["label"].startswith("Command "))
    text = group["description"]
    assert "Bonus action:" in text and "costs no Qi, Stamina or other resource" in text
    assert "in range of the order" in text and "next turn" in text
    assert "acts on its own instincts" in text
    assert "takes the Dodge action instead" not in text


def test_order_choice_transport_keeps_all_options_and_is_namespace_inert():
    from combat.ext.summon_instinct import DIRECTIVE_KINDS, order_options

    options = ["manual", *DIRECTIVE_KINDS]
    context = {"needle_options": options, "automatic": False, "preferred": ["manual"]}
    spec = order_options(None, None, "order", "owner", "choice:summon_order:guard:order", context)
    assert spec["option_ids"] == options
    assert not spec["automatic_use"] and not spec["allow_decline"]
    assert order_options(None, None, "order", "owner", "choice:unrelated", context) is None
