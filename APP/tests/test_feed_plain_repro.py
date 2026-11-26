"""Synthetic busy action regression for the player-facing summary (FEEDPLAIN1)."""

from test_feed_summary import DEFS, STRIKE, _feed, _fight_events, render, visible

ASHFALL = "action:test.ashfall"
ARMOR = "action:test.magma_armor"
HIDDEN_STRIKE = "reaction:test.hidden_strike"
GUARD = "reaction:test.stamina_guard"
ASH = "resource:foundation.funeral_ash"
DEFINITIONS = {**DEFS, ASHFALL: "Ashfall", ARMOR: "Magma Armor", HIDDEN_STRIKE: "Hidden Strike",
               GUARD: "Stamina Guard", ASH: "Funeral Ash"}


def _record(events, kind, actor, targets=(), source=STRIKE, **payload):
    events.append(dict(sequence=events[-1]["sequence"] + 1, event_type=kind, actor_id=actor,
                       target_ids=list(targets), source_definition_id=source,
                       trigger_or_intent_id="t2", transaction_id="t2", payload=payload))


def _busy_action():
    events, rolls = _fight_events()
    events = [event for event in events if event["transaction_id"] == "t2"]
    damage = events.pop()
    events.pop()  # replace the fixture's Test Parry with the actual shape of a paid guard
    _record(events, "RESOURCE_SPENT", "a", source=GUARD, resource_id="resource:core.stamina", amount=4, remaining=35)
    _record(events, "REACTION_RESOLVED", "a", ("a",), GUARD, checkpoint="DAMAGE_APPLICATION",
            pending_before=40, pending_after=6, reduction=34, spend=4)
    _record(events, "DAMAGE_COMMITTED", "t", ("a",), **damage["payload"])

    # The failed save ends the current Ashfall; the held Magma Armor resumes. Neither the
    # zone removal nor the modifier cleanup is the concentration-ending receipt.
    rolls.append(dict(roll_id="con-save", actor_id="a", reason="SAVE:CON", expression="1d20+1",
                      dice=[3], modifier=1, total=4, mode="NORMAL"))
    _record(events, "SAVE_ROLLED", "a", source="system:combat.concentration", roll_id="con-save", dc=10, success=False)
    _record(events, "ZONE_REMOVED", "a", source=ASHFALL, zone_id="test-ashfall", reason="CONCENTRATION")
    _record(events, "CONCENTRATION_ENDED", "a", source=ASHFALL, started_sequence=4, reason="FAILED_SAVE")
    for suffix in ("ac", "resistance"):
        _record(events, "MODIFIER_REMOVED", "a", ("a",), ASHFALL, modifier_id="ashfall-" + suffix, reason="FAILED_SAVE")
    _record(events, "CONCENTRATION_STARTED", "a", source=ARMOR, reason="RESUMED")

    _record(events, "CONDITION_APPLIED", "t", ("a",),
            condition_id="condition:typed.no_reactions_against", expires_on="START_OF_SOURCE_NEXT_TURN",
            gate3_condition_after={"data": {"against": "t", "label": "No Reactions against Bram Holt"}})
    _record(events, "PASSIVE_TRIGGERED", "t", ("t",), trigger="Test Spear gains 1 Crack (3 in all).")
    retired = "condition:typed.destroyed_item"
    _record(events, "CONDITION_APPLIED", "t", ("t",), condition_id=retired, expires_on="UNTIL_REMOVED",
            gate3_condition_after={"condition_id": retired, "data": {
                "label": "Test Spear is destroyed (it breaks at 3 Crack); it cannot be equipped or used.",
                "item_key": "spear-4", "object_id": "t|spear-4", "disables_action": "action:test.spear"}})
    _record(events, "PASSIVE_TRIGGERED", "t", ("t",),
            trigger="Test Spear breaks (it breaks at 3 Crack); it can't be used again.")

    _record(events, "RESOURCE_GAINED", "a", resource_id=ASH, requested=1, gained=1, current=1)
    _record(events, "PASSIVE_TRIGGERED", "a",
            log="Aster Vale gains 1 Funeral Ash. It expires at the end of their next turn and can be spent on a later event.")
    _record(events, "PASSIVE_TRIGGERED", "t", ("a",), HIDDEN_STRIKE, trigger="Hidden Strike")
    rolls.append(dict(roll_id="extra-hit", actor_id="t", reason="ATTACK", expression="1d20+5",
                      dice=[14], modifier=5, total=19, mode="NORMAL"))
    _record(events, "ATTACK_ROLLED", "t", ("a",), HIDDEN_STRIKE, roll_id="extra-hit", target_ac=14, provisional_hit=True)
    _record(events, "DAMAGE_COMMITTED", "t", ("a",), HIDDEN_STRIKE, hp_damage=3, damage_type="force", remaining_hp=11)
    return events, rolls


def test_busy_action_summary_only_reports_outcomes(capsys):
    events, rolls = _busy_action()
    rows = _feed(events, rolls, definitions=DEFINITIONS)
    entries = render([rows], open=True)
    count = sum(row["brief"]["kind"] == "clause" for row in rows)
    message = "\n".join(visible(entries)) + f"\nclauses: {count}"
    with capsys.disabled():
        print(message, flush=True)
    assert len(entries) == 1, message
    entry = entries[0]
    lines = entry["text"].splitlines()
    assert lines == [
        "Bram Holt → Aster Vale: Test Strike.",
        "Hit with Advantage.",
        "Aster Vale spent 4 Stamina (35 left).",
        "Aster Vale resolved Stamina Guard; Damage reduced by 34.",
        "6 slashing damage (14 HP left).",
        "Aster Vale failed the save (DC 10).",
        "Aster Vale stopped concentrating on Ashfall.",
        "Aster Vale cannot take reactions against Bram Holt because of Test Strike.",
        "Test Spear is destroyed (it breaks at 3 Crack); it cannot be equipped or used.",
        "Aster Vale gained 1 Funeral Ash (1 now).",
        "Hit.",
        "Hidden Strike: 3 force damage (11 HP left).",
    ], message
    assert count == len(lines) - 1, message
    assert entry["sequences"] == [event["sequence"] for event in events], message
    all_events = visible(render([rows], detail=True))
    assert entry["lines"] == all_events, message
    assert "Test Spear gains 1 Crack (3 in all)." in all_events, message
    assert "Test Spear breaks (it breaks at 3 Crack); it can't be used again." in all_events, message
    assert any("spent 4 Stamina" in line and "Stamina Guard" in line for line in all_events), message
    assert "The effect of Ashfall ended for Aster Vale." in all_events, message
    assert "Aster Vale keeps concentrating on Magma Armor." in all_events, message
    assert any("gains 1 Funeral Ash" in line for line in all_events), message


def test_outcome_and_action_group_do_not_require_a_detailed_breakdown():
    events, _ = _fight_events()
    events = [event for event in events if event["transaction_id"] == "t2"][:1]
    _record(events, "ATTACK_ROLLED", "t", ("a",), provisional_hit=True, mode="ADVANTAGE")
    _record(events, "PASSIVE_TRIGGERED", "t", ("a",))  # the detailed formatter cannot describe it
    _record(events, "DAMAGE_COMMITTED", "t", ("a",), remaining_hp=14)  # no amount: must not throw or invent one
    _record(events, "DAMAGE_COMMITTED", "t", ("a",), amount=6, damage_type="slashing", remaining_hp=8)
    head, tail = _feed(events[:2], []), _feed(events[2:], [])
    entries = render([head, tail], open=True)
    count = sum(row["brief"]["kind"] == "clause" for row in head + tail)
    message = "\n".join(visible(entries)) + f"\nclauses: {count}"
    assert len(entries) == 1, message
    entry = entries[0]
    assert not head[-1]["detailed_breakdown_recorded"], message
    assert all(not row["detailed_breakdown_recorded"] for row in tail), message
    assert entry["text"].splitlines() == [
        "Bram Holt → Aster Vale: Test Strike.",
        "Hit with Advantage.",
        "Test Strike: Bram Holt dealt 6 slashing damage to Aster Vale (8 HP left).",
    ], message
    assert entry["sequences"] == [event["sequence"] for event in events], message


def test_attack_at_empty_square_and_creatures_going_down_are_outcomes():
    events, _ = _fight_events()
    events = [event for event in events if event["transaction_id"] == "t2"][:1]
    _record(events, "ATTACK_LOCATION_MISSED", "t", destination={"x": 4, "y": 5}, attack_index=1,
            reason="EMPTY_REMEMBERED_SQUARE",
            text="Bram Holt attacks the square where they last saw Aster Vale, but hits nothing.")
    _record(events, "LIFE_STATE_CHANGED", "a", life_state="DYING")
    _record(events, "ENTITY_DEFEATED", "c", source="system:combat.defeat", nonlethal=True, defeating_source=STRIKE)
    # The death plug-in applies this marker before the same engine defeat receipt.
    dead = "condition:typed.death_finalized"
    _record(events, "CONDITION_APPLIED", "a", ("a",), condition_id=dead,
            gate3_condition_after={"condition_id": dead, "data": {"label": "Dead: soul has departed"}})
    _record(events, "ENTITY_DEFEATED", "a", source="system:combat.defeat", nonlethal=True, defeating_source=STRIKE)
    rows = _feed(events, [])
    [entry] = render([rows])
    count = sum(row["brief"]["kind"] == "clause" for row in rows)
    message = entry["text"] + f"\nclauses: {count}"
    assert entry["text"].splitlines() == [
        "Bram Holt → Aster Vale: Test Strike.",
        "Bram Holt attacks the square where they last saw Aster Vale, but hits nothing.",
        "Aster Vale dropped and is dying.",
        "Cai Lin was defeated without being killed.",
        "Aster Vale died.",
    ], message


def test_other_recorded_outcomes_stay_visible():
    events, _ = _fight_events()
    events = [event for event in events if event["transaction_id"] == "t2"][:1]
    _record(events, "SAVE_ROLLED", "a", dc=12, success=True)  # detailed roll not present in this fetch
    _record(events, "SAVE_AUTO_FAILED", "a", ability="DEX")
    _record(events, "SAVE_ROLLED", "a", dc=12, success=False)
    _record(events, "HEALING_APPLIED", "t", ("a",), before=10, after=13, offered=5)
    _record(events, "TEMP_HP_GRANTED", "t", ("a",), before=0, after=4, offered=4)
    _record(events, "MOVEMENT_COMMITTED", "a", destination={"x": 4, "y": 5}, distance_ft=10, forced=True)
    _record(events, "UNAVOIDABLE_DAMAGE_COMMITTED", "t", ("t",), hp_damage=2, remaining_hp=8, damage_type="FORCE")
    _record(events, "OBJECT_UPDATED", "t", ("door",), damage={"taken": 5, "kinds": "force"},
            object={"object_id": "door", "object_kind": "DOOR", "destroyed": True, "current_hp": 0})
    rows = _feed(events, [])
    [entry] = render([rows])
    count = sum(row["brief"]["kind"] == "clause" for row in rows)
    message = entry["text"] + f"\nclauses: {count}"
    assert entry["text"].splitlines() == [
        "Bram Holt → Aster Vale: Test Strike.",
        "Aster Vale made the save (DC 12).",
        "Aster Vale failed the save (DC 12).",
        "Aster Vale regained 3 HP (13 HP now).",
        "Aster Vale now has 4 temporary HP.",
        "Aster Vale was moved 10 ft by force.",
        "2 force damage to Bram Holt (8 HP left).",
        "Door took 5 force damage and was destroyed.",
    ], message


def test_reaction_and_summon_command_keep_actor_and_targets():
    events, _ = _fight_events()
    events = [event for event in events if event["transaction_id"] == "t2"][:1]
    _record(events, "REACTION_RESOLVED", "c", ("t",), "reaction:test.pursuit")
    _record(events, "SUMMONS_COMMANDED", "t", ("a", "c"), "action:test.command")
    _record(events, "SUMMON_APPEARED", "t", ("c",), "action:test.command")
    rows = _feed(events, [], definitions={**DEFS, "reaction:test.pursuit": "Pursuit",
                                         "action:test.command": "Command"})
    [entry] = render([rows])
    lines = entry["text"].splitlines()
    message = "\n".join(lines)
    assert "Cai Lin used Pursuit against Bram Holt." in lines, message
    assert "Bram Holt commanded Aster Vale, Cai Lin with Command." in lines, message
    assert "Cai Lin appeared, summoned by Bram Holt with Command." in lines, message


def test_reaction_turns_hit_into_miss():
    events, _ = _fight_events()
    events = [event for event in events if event["transaction_id"] == "t2"][:1]
    _record(events, "ATTACK_ROLLED", "t", ("a",), provisional_hit=True)
    _record(events, "REACTION_RESOLVED", "a", ("a",), "reaction:test.guard",
            checkpoint="ATTACK_HIT_BEFORE_DAMAGE", hit_after_recheck=False)
    [entry] = render([_feed(events, [], definitions={**DEFS, "reaction:test.guard": "Guard Reflex"})])
    lines = entry["text"].splitlines()
    message = "\n".join(lines)
    assert "Hit." in lines, message
    assert any("Guard Reflex" in line and line.endswith("; the attack missed.") for line in lines), message


def test_successful_defense_recheck_is_not_a_reaction():
    events, _ = _fight_events()
    events = [event for event in events if event["transaction_id"] == "t2"][:1]
    _record(events, "ATTACK_ROLLED", "t", ("a",), provisional_hit=True)
    _record(events, "REACTION_RESOLVED", "a", ("a",), checkpoint="AFTER_ATTACK_ROLL_DEFENSES", hit_after_recheck=True)
    [entry] = render([_feed(events, [])])
    lines = entry["text"].splitlines()
    message = "\n".join(lines)
    assert "Hit." in lines, message
    assert not any("Aster Vale resolved Test Strike" in line for line in lines), message
