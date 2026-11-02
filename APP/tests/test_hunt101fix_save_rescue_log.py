"""A rescued save names the bonus that made it succeed, not only the pre-rescue total."""
from combat.history_feed import format_history_feed

NAMES = {"reaction:calamity_furnace": "Calamity Furnace", "save:frost_ward": "Frost Ward",
         "action:ling_qi.true_name_witness": "True Name Witness"}


def _summaries(events):
    rows = format_history_feed(events, [], pre_state=None, post_state={"actors": {}}, actor_names={"a": "Ana"},
                               definition_names=NAMES)
    return [row["summary"] for row in rows if "save against" in row.get("summary", "")]


def test_rescued_save_shows_pre_rescue_total_and_bonus():
    events = [
        {"event_type": "REACTION_RESOLVED", "source_definition_id": "reaction:calamity_furnace", "actor_id": "a", "target_ids": [],
         "payload": {"checkpoint": "SAVE_RESULT_BEFORE_DECLARED", "bonus": 6, "source_save": "save:frost_ward"}},
        {"event_type": "SAVE_ROLLED", "source_definition_id": "save:frost_ward", "actor_id": "a", "target_ids": [],
         "payload": {"expression": "1d20+5", "modifier": 11, "total": 17, "dc": 15, "success": True}},
    ]
    assert _summaries(events) == ["Ana — save against Frost Ward (DC 15): total 11, +6 Calamity Furnace = 17 — Success."]


def test_unrescued_save_keeps_plain_roll_text():
    events = [
        {"event_type": "SAVE_ROLLED", "source_definition_id": "save:frost_ward", "actor_id": "a", "target_ids": [],
         "payload": {"expression": "1d20+5", "modifier": 5, "total": 9, "dc": 15, "success": False}},
    ]
    [line] = _summaries(events)
    assert "Calamity" not in line and line.endswith("total 9 — Failure.")


def test_a_save_checkpoint_reaction_without_a_bonus_leaves_the_plain_roll():
    """HUNT101FIXR: the same checkpoint also carries side-effect reactions with no numeric bonus."""
    events = [
        {"event_type": "REACTION_RESOLVED", "source_definition_id": "reaction:calamity_furnace", "actor_id": "a", "target_ids": [],
         "payload": {"checkpoint": "SAVE_RESULT_BEFORE_DECLARED", "source_save": "save:frost_ward"}},
        {"event_type": "SAVE_ROLLED", "source_definition_id": "save:frost_ward", "actor_id": "a", "target_ids": [],
         "payload": {"expression": "1d20+5", "modifier": 5, "total": 9, "dc": 15, "success": False}},
    ]
    [line] = _summaries(events)
    assert "Calamity" not in line and line.endswith("total 9 — Failure.")


def test_two_rescues_on_one_save_are_both_shown_and_subtracted():
    """HUNT101FIXR2: an engine rescue (True Name Witness, +3) and a typed rescue (+6) on the same save."""
    rescue = {"event_type": "REACTION_RESOLVED", "actor_id": "a", "target_ids": []}
    events = [
        {**rescue, "source_definition_id": "action:ling_qi.true_name_witness",
         "payload": {"checkpoint": "SAVE_RESULT_BEFORE_DECLARED", "bonus": 3, "source_save": "save:frost_ward"}},
        {**rescue, "source_definition_id": "reaction:calamity_furnace",
         "payload": {"checkpoint": "SAVE_RESULT_BEFORE_DECLARED", "bonus": 6, "source_save": "save:frost_ward"}},
        {"event_type": "SAVE_ROLLED", "source_definition_id": "save:frost_ward", "actor_id": "a", "target_ids": [],
         "payload": {"expression": "1d20+5", "modifier": 14, "total": 20, "dc": 18, "success": True}},
    ]
    assert _summaries(events) == [
        "Ana — save against Frost Ward (DC 18): total 11, +3 True Name Witness, +6 Calamity Furnace = 20 — Success."]
