"""FEEDSUMMARY1 (owner 2026-11-13): the default Combat log is one glanceable entry per action; "All events" is the
full log, unchanged. The words are composed in combat/feed_brief.py from the rows format_history_feed returns, and the
shipped tabletop.js renderer joins them (tests/feed_summary_check.mjs runs it on a DOM stand-in, one call per fetch).

Synthetic events and names: nothing here comes from an owner save, the rules text or a shipped arena. The engine-run
stock fight is in tests/test_feed_summary_stock_fight.py, which stays private.
"""
import json
import subprocess
from pathlib import Path

from combat.history_feed import format_history_feed

ROOT = Path(__file__).resolve().parents[1]
BARRAGE, STRIKE, BURST, PARRY = "action:test.barrage+shot", "action:test.strike", "action:test.burst", "reaction:test.parry"
NAMES = {"a": "Aster Vale", "t": "Bram Holt", "c": "Cai Lin", "img": "Decoy Image"}
DEFS = {BARRAGE: "Test Barrage + Test Shot", STRIKE: "Test Strike", BURST: "Test Burst", PARRY: "Test Parry",
        "resource:core.qi": "Qi", "resource:core.stamina": "Stamina"}


def render(increments, *, detail=False, open=False, grouped=False):
    """The shipped renderer's entries, as the player reads them (``grouped``: map setup folded first, as the
    default log did before FEEDSUMMARY1; used only to print the BEFORE evidence)."""
    result = subprocess.run(["node", str(ROOT / "tests/feed_summary_check.mjs")], text=True, capture_output=True,
                            input=json.dumps({"increments": increments, "detail": detail, "open": open,
                                              "grouped": grouped}))
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


def visible(entries):
    return [entry["text"] for entry in entries if not entry["hidden"]]


def _fight_events():
    events, rolls = [], []

    def ev(txn, event_type, actor, targets=(), source=BARRAGE, **payload):
        events.append({"sequence": len(events) + 1, "event_type": event_type, "actor_id": actor,
                       "target_ids": list(targets), "source_definition_id": source, "trigger_or_intent_id": txn,
                       "transaction_id": txn, "payload": payload})

    def roll(roll_id, actor, total, mode="NORMAL"):
        rolls.append({"roll_id": roll_id, "actor_id": actor, "reason": "ATTACK", "expression": "1d20+5",
                      "dice": [total - 5], "modifier": 5, "total": total, "mode": mode})

    ev("turn-a", "TURN_STARTED", "a", source="system:turn", round=3)
    # Aster's Test Barrage: the arrow hits Bram's Decoy Image instead, the image is gone, and the variant's rider.
    ev("t1", "INTENT_ACCEPTED", "a", ["t"])
    ev("t1", "RESOURCE_SPENT", "a", resource_id="resource:core.qi", amount=2, remaining=5)
    ev("t1", "PASSIVE_TRIGGERED", "a", ["img"], kind="attack_target_intercepted", attack_source_id=BARRAGE,
       original_target_id="t", text="Decoy Image: rolled 1 on a d2 — Aster Vale's Test Barrage + Test Shot hit "
                                    "Bram Holt's decoy image instead (the image is gone).")
    ev("t1", "CONDITION_REMOVED", "t", ["t"], condition_id="condition:typed.afterimage",
       gate3_condition_before={"condition_id": "condition:typed.afterimage", "data": {"label": "Decoy Image"}})
    ev("t1", "GM_RIDER", "a", ["t"], automated=True,
       rider="Test Shot: the primary attack had Advantage; the Test Barrage follow-up was forgone.")
    ev("end-a", "TURN_ENDED", "a", source="system:turn")
    ev("end-a", "TURN_STARTED", "t", source="system:turn", round=3)
    ev("move-t", "MOVEMENT_COMMITTED", "t", source="system:combat.movement", distance_ft=15,
       destination={"x": 4, "y": 5}, path=[{"x": 4, "y": 2}, {"x": 4, "y": 5}])
    # Bram's strike hits with Advantage; Cai's reaction, inside Bram's action, takes 3 off the damage.
    ev("t2", "INTENT_ACCEPTED", "t", ["a"], source=STRIKE)
    roll("r1", "t", 22, "ADVANTAGE")
    ev("t2", "ATTACK_ROLLED", "t", ["a"], source=STRIKE, roll_id="r1", target_ac=14, provisional_hit=True,
       mode="ADVANTAGE", mode_sources=[{"kind": "advantage", "effect": "Prone", "owner": "Aster Vale", "why": "within 5 feet"}])
    ev("t2", "REACTION_RESOLVED", "c", ["a"], source=PARRY, checkpoint="DAMAGE_APPLICATION", reduction=3)
    ev("t2", "DAMAGE_COMMITTED", "t", ["a"], source=STRIKE, hp_damage=6, damage_type="SLASHING", remaining_hp=14,
       rolled_or_pending_damage=9, reduced_to=6)
    # A second strike misses.
    ev("t3", "INTENT_ACCEPTED", "t", ["a"], source=STRIKE)
    roll("r2", "t", 8)
    ev("t3", "ATTACK_ROLLED", "t", ["a"], source=STRIKE, roll_id="r2", target_ac=14, provisional_hit=False)
    # Bram's burst: Aster fails the save and falls Prone; a concealed condition is never shown.
    ev("t4", "INTENT_ACCEPTED", "t", ["a"], source=BURST)
    rolls.append({"roll_id": "r3", "actor_id": "a", "reason": "SAVE", "expression": "1d20+1", "dice": [8],
                  "modifier": 1, "total": 9, "mode": "NORMAL"})
    ev("t4", "SAVE_ROLLED", "a", source=BURST, roll_id="r3", dc=13, success=False)
    ev("t4", "CONDITION_APPLIED", "t", ["a"], source=BURST, condition_id="condition:typed.prone", instance_id="p1",
       expires_on="UNTIL_REMOVED")
    ev("t4", "CONDITION_APPLIED", "t", ["a"], source=BURST, condition_id="condition:typed.whisper", instance_id="secret",
       gate3_condition_after={"condition_id": "condition:typed.whisper", "data": {"label": "Test Hidden Curse"}})
    # A record the feed has no breakdown for.
    ev("t5", "MYSTERY_RECORD", "t", source=BURST)
    return events, rolls


def _feed(events, rolls, names=NAMES, definitions=DEFS):
    return format_history_feed(events, rolls, pre_state=None, post_state={}, actor_names=names,
                               definition_names=definitions, concealed_condition_instance_ids={"secret"})


VOLLEY, TAX, CORE, KNUCKLE, MERCY = ("action:test.volley", "reaction:test.grave_tax", "passive:test.core",
                                     "talent:test.breaking_knuckle", "talent:test.merciful_hand")
TALENT_NAMES = {"b": "Tessa Marr", "g": "Test Foe", "d": "Hollis Brandt", "x": "Wren Dacey"}
TALENT_DEFS = {VOLLEY: "Test Volley", TAX: "Test Tax", CORE: "Test Core Passive",
               KNUCKLE: "Test Knuckle", MERCY: "Test Mercy", "resource:core.stamina": "Stamina",
               "resource:core.resonance": "Resonance"}
REMINDER = "Test Rider: If the target is wearing metal armor, the additional damage becomes 1d6."


def _talent_events():
    """One volley with what the showcase fights showed (FEEDSUMMARY1F1 evidence, showcase-2): an enemy's reaction inside
    it, a temporary-HP offer that changed nothing, a thrown weapon, a talent's rider damage, a talent that fires on its own,
    a rule reminder, a condition recorded with a name and a pill, another talent's condition, and an Arc."""
    events = []

    def ev(event_type, actor, targets=(), source=VOLLEY, txn="v1", **payload):
        events.append({"sequence": len(events) + 1, "event_type": event_type, "actor_id": actor,
                       "target_ids": list(targets), "source_definition_id": source, "trigger_or_intent_id": txn,
                       "transaction_id": txn, "payload": payload})

    ev("TURN_STARTED", "b", source="system:turn", txn="turn-b", round=1)
    ev("INTENT_ACCEPTED", "b", ["g"])
    ev("RESOURCE_SPENT", "b", resource_id="resource:core.stamina", amount=3, remaining=29)
    ev("RESOURCE_SPENT", "d", source=TAX, resource_id="resource:core.resonance", amount=4, remaining=51)
    ev("PASSIVE_TRIGGERED", "d", ["b"], source=TAX,
       log="Test Tax reduces the Temporary Hit Points Tessa Marr would gain from 4 to 0.")
    ev("REACTION_RESOLVED", "d", ["b"], source=TAX, checkpoint="TEMP_HP_GAINED")
    ev("TEMP_HP_GRANTED", "b", ["b"], source=CORE, offered=0, before=0, after=0)
    ev("ATTACK_ROLLED", "b", ["g"], roll_id="v-hit", target_ac=17, provisional_hit=True)
    ev("CONDITION_APPLIED", "b", ["b"], condition_id="condition:typed.dropped_item", instance_id="drop",
       expires_on="UNTIL_REMOVED", gate3_condition_after={"condition_id": "condition:typed.dropped_item", "data": {
           "item_key": "duan-cha", "item_name": "Test Spear", "dropped_at": {"x": 4, "y": 4}}})
    ev("DAMAGE_ROLLED", "b", ["g"], roll_id="v-arrow", damage_label="Test Arrow")
    ev("DAMAGE_COMMITTED", "b", ["g"], hp_damage=8, damage_type="LIGHTNING", remaining_hp=110,
       rolled_or_pending_damage=8)
    ev("DAMAGE_COMMITTED", "b", ["g"], display_source_id=KNUCKLE, hp_damage=4, damage_type="BLUDGEONING",
       remaining_hp=106, rolled_or_pending_damage=4)
    ev("GM_RIDER", "b", ["g"], rider=REMINDER)
    ev("CONDITION_APPLIED", "b", ["g"], condition_id="condition:typed.next_attack_damage", instance_id="soft",
       expires_on="END_OF_HOLDER_NEXT_TURN", gate3_condition_after={
           "condition_id": "condition:typed.next_attack_damage", "expires_on": "END_OF_HOLDER_NEXT_TURN",
           "data": {"amount": 8, "label": "Its next attack roll deals 8 less damage", "name": "Test Weakness"}})
    ev("CONDITION_APPLIED", "b", ["g"], source=MERCY, condition_id="condition:typed.prone", instance_id="prone",
       expires_on="STAND_UP")
    ev("PASSIVE_TRIGGERED", "b", ["x"], trigger="an Arc from Test Foe")
    rolls = [{"roll_id": "v-hit", "actor_id": "b", "reason": "ATTACK", "expression": "1d20+7", "dice": [16],
              "modifier": 7, "total": 23, "mode": "NORMAL"},
             {"roll_id": "v-arrow", "actor_id": "b", "reason": "DAMAGE", "expression": "1d8+0", "dice": [8],
              "modifier": 0, "total": 8, "mode": "NORMAL"}]
    return events, rolls


def test_talents_and_reactions_say_what_happened_and_who_caused_it():
    """FEEDSUMMARY1F1 (owner 2026-11-13: "i need to see how much is communicated"; "we need to avoid large blocks of
    text"): every damage and condition clause names what caused it when its headline does not (decided from the
    recorded source ids, FEEDSUMMARY1F3), a talent that fires on its own is named, a reaction inside the action says
    who used it, nothing that did not happen is said, and a rule reminder, the thrown weapon and the condition read as
    the record names them."""
    events, rolls = _talent_events()
    rows = _feed(events, rolls, TALENT_NAMES, TALENT_DEFS)
    entries = render([rows], open=True)
    assert visible(entries) == [
        "Round 1 · Tessa Marr's turn",
        "Tessa Marr → Test Foe: Test Volley. Spent 3 Stamina (29 left). "
        "Hollis Brandt spent 4 Resonance (51 left). "
        "Test Tax reduces the Temporary Hit Points Tessa Marr would gain from 4 to 0. "
        "Hollis Brandt used Test Tax against Tessa Marr. Hit. "
        "Tessa Marr dropped Test Spear; it lies at their feet. "
        "Test Arrow: 8 lightning damage (110 HP left). Test Knuckle: 4 bludgeoning damage (106 HP left). "
        "Applied Test Weakness. Test Mercy: applied Prone. "
        "Tessa Marr triggered an Arc from Test Foe against Wren Dacey.",
    ]
    # What the default entry leaves out is still one of its detailed lines: the reminder, the offer that changed
    # nothing, and what the condition does.
    volley = next(entry for entry in entries if entry["text"].startswith("Tessa Marr → Test Foe: Test Volley."))
    detail = {row["event_sequence"]: row["summary"] for row in rows if row["event_sequence"] in volley["sequences"]}
    assert any(REMINDER in line for line in detail.values())
    assert any(line.startswith("Test Core Passive offered Tessa Marr 0 temporary HP") for line in detail.values())
    assert any("applied the Test Weakness condition to Test Foe" in line
               and line.endswith("Its next attack roll deals 8 less damage.") for line in detail.values())
    # Every row is behind exactly one entry, in order.
    assert [seq for entry in entries for seq in entry["sequences"]] == [row["event_sequence"] for row in rows]


def test_default_log_is_one_entry_per_action_with_every_row_behind_it():
    events, rolls = _fight_events()
    rows = _feed(events, rolls)
    entries = render([rows], open=True)
    texts = visible(entries)
    assert texts[0] == "Round 3 · Aster Vale's turn"
    barrage = texts[1]
    assert barrage.startswith("Aster Vale → Bram Holt: Test Barrage + Test Shot. Spent 2 Qi (5 left). Decoy Image: rolled 1")
    assert "decoy image instead (the image is gone). Decoy Image was removed." in barrage
    assert "Test Shot: the primary attack had Advantage; the Test Barrage follow-up was forgone." in barrage
    assert texts[2] == "Round 3 · Bram Holt's turn"
    assert texts[3] == "Bram Holt moved 15 ft."
    # Cai's reaction, recorded inside Bram's action, is a clause of Bram's entry, right after the hit it answered.
    assert texts[4] == ("Bram Holt → Aster Vale: Test Strike. Hit with Advantage. "
                        "Cai Lin used Test Parry against Aster Vale; Damage reduced by 3. 6 slashing damage (14 HP left).")
    assert texts[5] == "Bram Holt → Aster Vale: Test Strike. Missed."
    assert texts[6] == "Bram Holt → Aster Vale: Test Burst. Aster Vale failed the save (DC 13). Applied Prone."
    assert texts[7] == "Detailed breakdown was not recorded for this event."  # unknown: its own entry, visible
    assert len(texts) == 8
    # Damage and rolls keep the feed's colours.
    strike = next(entry for entry in entries if entry["text"] == texts[4])
    assert strike["className"].startswith("is-summary is-damage")
    # Every row is on exactly one entry, and an opened entry shows its rows exactly as "All events" does (turn
    # headers are not opened).
    everything = render([rows], detail=True)
    assert len(everything) == len(rows)
    assert [seq for entry in entries for seq in entry["sequences"]] == [row["event_sequence"] for row in rows]
    assert [line for entry in entries for line in entry["lines"]] == [
        line["text"] for line in everything if line.get("type") != "TURN_STARTED"]
    # A concealed condition is in no entry, hover or detail line.
    for entry in entries + everything:
        assert "Test Hidden Curse" not in json.dumps(entry)
    assert all(row["raw"]["payload"].get("instance_id") != "secret" for row in rows)


def test_an_action_split_across_two_fetches_ends_as_one_entry():
    events, rolls = _fight_events()
    whole = visible(render([_feed(events, rolls)]))
    # The table formats each `events?after=N` fetch on its own: split inside Bram's strike, after its attack roll.
    cut = next(index for index, event in enumerate(events) if event["event_type"] == "REACTION_RESOLVED")
    first, second = _feed(events[:cut], rolls), _feed(events[cut:], rolls)
    entries = render([first, second])
    split = visible(entries)
    assert len(split) == len(whole)
    strike = next(entry for entry in entries if entry["text"].startswith("Bram Holt → Aster Vale: Test Strike. Hit"))
    assert len(strike["sequences"]) == 4
    # The second fetch cannot see the headline, so its clauses name who did what with what; it reads the same.
    assert strike["text"] == ("Bram Holt → Aster Vale: Test Strike. Hit with Advantage. "
                              "Cai Lin used Test Parry against Aster Vale; Damage reduced by 3. "
                              "Test Strike: Bram Holt dealt 6 slashing damage to Aster Vale (14 HP left).")
