"""Named on-hit effects retain their source across table commit and disk reload."""
from combat.history_feed import format_history_feed
from combat.gate4_engine import Gate4ControllerEngine
from tests.test_p4_void_needle import cast, HIDDEN


def test_hit_riders_have_named_sources_after_table_reload(tmp_path, monkeypatch):
    # Reproduce the playtest's Advantage qualification; resolve the actual Exploit/save normally.
    monkeypatch.setattr(Gate4ControllerEngine, "_attack_mode", lambda *args, **kwargs: "ADVANTAGE")
    boundary, _ = cast(tmp_path, monkeypatch, "Empty Vitality", "Hollowed", hidden=True,
                       ruin=True, extra=("TAL_FENCING_CHEST_STRIKE",))
    events = boundary["events"]
    rolls = [e for e in events if e["event_type"] == "DAMAGE_ROLLED"]
    assert rolls[1]["payload"]["display_source_id"] == f"passive:{HIDDEN}"
    assert "TAL_UNMAKING_SECOND_RUIN_FORM" in rolls[2]["payload"]["display_source_id"]
    assert rolls[3]["payload"]["display_source_id"] == "passive:TAL_VOID_NULLIFYING_STRIKE"
    saves = [e for e in events if e["event_type"] == "SAVE_ROLLED"]
    assert [e["source_definition_id"] for e in saves] == [
        "passive:TAL_FENCING_CHEST_STRIKE", "passive:TAL_VOID_NULLIFYING_STRIKE"]
    poison = next(e for e in events if e["event_type"] == "CONDITION_APPLIED"
                  and e["payload"]["condition_id"] == "condition:typed.poisoned")
    assert poison["source_definition_id"] == "passive:TAL_FENCING_CHEST_STRIKE"
    feed = boundary["feed"]
    assert any("save against Chest Strike" in e["summary"] for e in feed)
    assert any("Second Ruin Form" in e["summary"] and "damage against" in e["summary"] for e in feed)
    assert not any("Not automated" in e["summary"] and "Second Ruin Form" in e["summary"] for e in feed)
    assert not any("Not automated" in e["summary"] and "Open the Gate" in e["summary"] for e in feed)
    assert any("Centerline Impact dealt 4 bludgeoning" in e["summary"] for e in feed)
    centerline = next(e for e in events if e["event_type"] == "DAMAGE_COMMITTED"
                      and e["source_definition_id"].endswith(".open_the_gate"))
    assert centerline["payload"]["display_name"] == "Open the Gate: Centerline Impact"
    gate_rider = next(e for e in events if e["event_type"] == "GM_RIDER"
                     and e["payload"].get("rider", "").startswith("Open the Gate:"))
    assert gate_rider["payload"]["completed_outcome_sequence"] == centerline["sequence"]
    assert any("Breaking Knuckle dealt 4 bludgeoning" in e["summary"] for e in feed)
    assert not any("triggered Factory" in e["summary"] and "applies Exploit" in e["summary"] for e in feed)


def test_legacy_complete_prose_marks_and_zone_names():
    events = [
        {"event_type": "PASSIVE_TRIGGERED", "payload": {"trigger": "Tabik applies Exploit: Chest Strike to Spirit."}},
        {"event_type": "CONDITION_APPLIED", "payload": {"condition_id": "condition:typed.mark.opened.actor:factory.tabik",
                                                        "expires_on": "END_OF_MARKER_NEXT_TURN"}},
        {"event_type": "ZONE_CREATED", "payload": {"zone": {"trigger_profile": {"name": "Elbow in the Door: difficult terrain for Spirit"}}}},
    ]
    for seq, event in enumerate(events, 1):
        event.update(sequence=seq, actor_id="tabik", target_ids=["spirit"], source_definition_id="attack")
    feed = format_history_feed(events, [], pre_state=None, post_state={"actors": {}},
                               actor_names={"tabik": "Tabik", "spirit": "Spirit"}, definition_names={})
    assert feed[0]["summary"] == "Tabik applies Exploit: Chest Strike to Spirit."
    assert "placed the Opened mark on Spirit" in feed[1]["summary"]
    assert "Actor:Factory" not in feed[1]["summary"]
    assert "Elbow in the Door: difficult terrain for Spirit" in feed[2]["summary"]


def test_open_the_gate_suffix_does_not_misname_movement_as_centerline_damage():
    event = {"sequence": 1, "event_type": "MOVEMENT_GRANTED", "actor_id": "tabik",
             "source_definition_id": "attack.open_the_gate", "payload": {"distance_ft": 5}}
    feed = format_history_feed([event], [], pre_state=None, post_state={"actors": {}},
                               actor_names={}, definition_names={})
    assert "Open the Gate: Hooking Step" in feed[0]["summary"]
    assert "Centerline" not in feed[0]["summary"]
    assert event["payload"] == {"distance_ft": 5}  # legacy adaptation is read-only


def test_generic_outcome_metadata_names_and_suppresses_only_matched_rider():
    """fix/ds-text b37727f9 (QUEUE: DSFIX1r + marker fix approval) names GM reminders."""
    outcome = {"sequence": 1, "event_type": "DAMAGE_COMMITTED", "actor_id": "actor",
               "target_ids": ["target"], "source_definition_id": "generic",
               "trigger_or_intent_id": "hit", "payload": {"hp_damage": 3, "display_name": "A named benefit"}}
    rider = {"sequence": 2, "event_type": "GM_RIDER", "actor_id": "actor", "target_ids": ["target"],
             "source_definition_id": "generic", "trigger_or_intent_id": "hit",
             "payload": {"rider": "A named benefit", "completed_outcome_sequence": 1}}
    def feed(events):
        return format_history_feed(events, [], pre_state=None, post_state={"actors": {}},
                                   actor_names={}, definition_names={})
    assert len(feed([outcome, rider])) == 1
    assert "A named benefit dealt 3" in feed([outcome, rider])[0]["summary"]
    assert "Resolve only effects that the recorded outcomes have not already applied." in feed([rider])[0]["summary"]
    assert "Rule reminder: A named benefit." in feed([rider])[0]["summary"]
    mismatched = {**outcome, "trigger_or_intent_id": "other-hit"}
    assert len(feed([mismatched, rider])) == 2


def test_unautomated_rider_is_preserved_without_a_matching_recorded_outcome():
    """fix/ds-text b37727f9 (QUEUE: DSFIX1r + marker fix approval) names GM reminders."""
    events = [{"sequence": 2, "event_type": "GM_RIDER", "actor_id": "tabik", "target_ids": ["spirit"],
               "source_definition_id": "attack", "trigger_or_intent_id": "this-hit",
               "payload": {"rider": "Open the Gate: Centerline Impact"}},
              {"sequence": 1, "event_type": "DAMAGE_COMMITTED", "actor_id": "tabik", "target_ids": ["spirit"],
               "source_definition_id": "attack.open_the_gate", "trigger_or_intent_id": "other-hit", "payload": {"hp_damage": 4}}]
    feed = format_history_feed(events, [], pre_state=None, post_state={"actors": {}},
                               actor_names={}, definition_names={})
    assert "Resolve only effects that the recorded outcomes have not already applied." in feed[0]["summary"]
    assert "Rule reminder: Open the Gate: Centerline Impact." in feed[0]["summary"]
