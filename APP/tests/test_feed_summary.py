"""FEEDSUMMARY1 (owner 2026-11-13): the default Combat log is one glanceable entry per action; "All events" is the
full log, unchanged. The words are composed in combat/feed_brief.py from the rows format_history_feed returns, and the
shipped tabletop.js renderer joins them (tests/feed_summary_check.mjs runs it on a DOM stand-in, one call per fetch).

Synthetic events and names: nothing here comes from an owner save or the rules text. The stock fight is an
engine-run AI fight on a shipped arena (tests/test_builtin_arenas.py _fight).
"""
import json
import subprocess
import zipfile
from pathlib import Path

from combat.history_feed import format_history_feed

ROOT = Path(__file__).resolve().parents[1]
BARRAGE, STRIKE, BURST, PARRY = "action:test.barrage+shot", "action:test.strike", "action:test.burst", "reaction:test.parry"
NAMES = {"a": "Aster Vale", "t": "Bram Holt", "c": "Cai Lin", "img": "Afterimage"}
DEFS = {BARRAGE: "Barrage + Distracting Shot", STRIKE: "Test Strike", BURST: "Test Burst", PARRY: "Test Parry",
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
    # Aster's Barrage: the arrow hits Bram's Afterimage instead, the image is gone, and the variant's rider.
    ev("t1", "INTENT_ACCEPTED", "a", ["t"])
    ev("t1", "RESOURCE_SPENT", "a", resource_id="resource:core.qi", amount=2, remaining=5)
    ev("t1", "PASSIVE_TRIGGERED", "a", ["img"], kind="attack_target_intercepted", attack_source_id=BARRAGE,
       original_target_id="t", text="Afterimage: rolled 1 on a d2 — Aster Vale's Barrage + Distracting Shot hit "
                                    "Bram Holt's afterimage instead (the image is gone).")
    ev("t1", "CONDITION_REMOVED", "t", ["t"], condition_id="condition:typed.afterimage",
       gate3_condition_before={"condition_id": "condition:typed.afterimage", "data": {"label": "Afterimage"}})
    ev("t1", "GM_RIDER", "a", ["t"], automated=True,
       rider="Distracting Shot: the primary attack had Advantage; the Barrage follow-up was forgone.")
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
       gate3_condition_after={"condition_id": "condition:typed.whisper", "data": {"label": "Whispered Curse"}})
    # A record the feed has no breakdown for.
    ev("t5", "MYSTERY_RECORD", "t", source=BURST)
    return events, rolls


def _feed(events, rolls):
    return format_history_feed(events, rolls, pre_state=None, post_state={}, actor_names=NAMES, definition_names=DEFS,
                               concealed_condition_instance_ids={"secret"})


def test_default_log_is_one_entry_per_action_with_every_row_behind_it():
    events, rolls = _fight_events()
    rows = _feed(events, rolls)
    entries = render([rows], open=True)
    texts = visible(entries)
    assert texts[0] == "Round 3 · Aster Vale's turn"
    barrage = texts[1]
    assert barrage.startswith("Aster Vale → Bram Holt: Barrage + Distracting Shot. Spent 2 Qi (5 left). Afterimage: rolled 1")
    assert "afterimage instead (the image is gone). Afterimage was removed from Bram Holt." in barrage
    assert "Barrage follow-up was forgone." in barrage and "Distracting Shot: the" not in barrage
    assert texts[2] == "Round 3 · Bram Holt's turn"
    assert texts[3] == "Bram Holt moved 15 ft."
    assert texts[4] == ("Bram Holt → Aster Vale: Test Strike. Hit with Advantage. "
                        "Cai Lin used Test Parry against Aster Vale; Damage reduced by 3. 6 slashing damage (14 HP left).")
    assert texts[5] == "Bram Holt → Aster Vale: Test Strike. Missed."
    assert texts[6].startswith("Bram Holt → Aster Vale: Test Burst. Aster Vale failed the save (DC 13). ")
    assert "Prone" in texts[6]
    assert texts[7] == "Detailed breakdown was not recorded for this event."  # unknown: its own entry, visible
    assert len(texts) == 8
    # The roll keeps its Advantage reasons on hover; damage and rolls keep the feed's colours.
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
        assert "Whispered Curse" not in json.dumps(entry)
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
    # The second fetch names who dealt the damage, since it cannot see the headline; it reads the same.
    assert strike["text"].endswith("Bram Holt dealt 6 slashing damage to Aster Vale (14 HP left).")


def test_stock_fight_reads_one_entry_per_action(tmp_path):
    """An engine-run AI fight's first two rounds: printed BEFORE (today's default log) and AFTER for the owner."""
    from combat.gate5_service import FACTORY_ACTOR_PREFIX
    from combat.tabletop_service import TabletopService
    from tests.retired_arena_support import HistoricalArenaWriter
    from tests.test_builtin_arenas import CLASSIC
    from tests.test_factory_combat_compiler import SHEET

    # tests/test_builtin_arenas.py _fight, with four distinct names so the printed log can be followed.
    fighters = {"west-0": "Aster Vale", "west-1": "Bram Holt", "east-0": "Cai Lin", "east-1": "Dara Moss"}
    for pid, name in fighters.items():
        folder = tmp_path / "portable_characters" / pid
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json",
                             json.dumps({**SHEET, "identity": {**SHEET["identity"], "display_name": name}}))
    service = HistoricalArenaWriter(ROOT, tmp_path)
    mid = service.create_factory_match(project_ids=["west-0", "west-1"],
                                       opponent_actor_ids=[FACTORY_ACTOR_PREFIX + "east-0", FACTORY_ACTOR_PREFIX + "east-1"],
                                       arena_id=CLASSIC[0], maximum_rounds=3, match_seed=f"ARENA1-{CLASSIC[0]}-2")["match_id"]
    for _ in range(120):
        engine = service._load_session(mid).engine
        if engine.state.terminal_result or engine.state.round_number > 2:
            break
        service.local_step(mid, include_match=False)
    rows = TabletopService(service, tmp_path).events(mid, 0)["events"]
    end = next((i for i, row in enumerate(rows) if row["event_type"] == "ROUND_STARTED"
                and row["raw"]["payload"].get("round") == 3), len(rows))
    rows = rows[:end]
    assert any(row["event_type"] == "ATTACK_ROLLED" for row in rows)
    entries = render([rows])
    texts = visible(entries)
    # Every row is behind exactly one entry (map placements fold into their one setup entry, as before), and each
    # action reads as one entry with its headline.
    shown = [seq for entry in entries for seq in entry["sequences"]]
    assert len(shown) == len(set(shown))
    assert {row["event_sequence"] for row in rows if row["event_type"] != "OBJECT_UPDATED"} <= set(shown)
    heads = [row for row in rows if row["brief"]["kind"] == "head"]
    assert heads and len(texts) < len(rows)
    assert not any("additional effect reminder" in text for text in texts)  # a rider says only its rule
    for head in heads:
        assert any(f"{head['brief']['actor']}" in text and head["brief"]["ability"] in text for text in texts)
    # Live: the same rows in two fetches, cut inside every action in turn, end as the same entries.
    for cut in sorted({rows.index(head) + 1 for head in heads}):
        assert visible(render([rows[:cut], rows[cut:]])) == texts
    # BEFORE: the default log until now -- one line per row, map setup grouped, turn ends and match creation left out.
    before = [line["text"] for line in render([rows], detail=True, grouped=True)
              if line.get("type") not in {"TURN_ENDED", "MATCH_CREATED"}]
    print("BEFORE\n" + "\n".join(before) + "\n\nAFTER\n" + "\n".join(texts))
