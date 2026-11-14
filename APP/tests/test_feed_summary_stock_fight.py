"""FEEDSUMMARY1 stock fight: an engine-run AI fight on a shipped arena, one entry per action. This file stays private: it
builds the fight through the retired-arena writer and the shipped factory characters (tests/retired_arena_support.py,
tests/test_builtin_arenas.py _fight), which the public copy does not ship. The synthetic-fixture checks are in
tests/test_feed_summary.py, which the public copy runs.
"""
import json
import zipfile
from pathlib import Path

from tests.test_feed_summary import TALENT_DEFS, TALENT_NAMES, _feed, _fight_events, _talent_events, render, visible

ROOT = Path(__file__).resolve().parents[1]


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
    # A condition that is itself its cause (Dodge's Dodge) is not named twice (FEEDSUMMARY1F3: decided from records).
    assert not any("Dodge: " in text for text in texts)
    for head in heads:
        assert any(f"{head['brief']['actor']}" in text and head["brief"]["ability"] in text for text in texts)
    # Live: the same rows in two fetches, cut inside every action in turn, end as the same entries.
    for cut in sorted({rows.index(head) + 1 for head in heads}):
        assert visible(render([rows[:cut], rows[cut:]])) == texts
    # BEFORE: the default log until now -- one line per row, map setup grouped, turn ends and match creation left out.
    before = [line["text"] for line in render([rows], detail=True, grouped=True)
              if line.get("type") not in {"TURN_ENDED", "MATCH_CREATED"}]
    print("BEFORE\n" + "\n".join(before) + "\n\nAFTER\n" + "\n".join(texts))
    # Entry lengths (FEEDSUMMARY1F1 cause 5), over this fight and the two fixture fights above.
    fights = {"stock fight": texts, "barrage fixture": visible(render([_feed(*_fight_events())])),
              "talent fixture": visible(render([_feed(*_talent_events(), TALENT_NAMES, TALENT_DEFS)]))}
    for name, shown in fights.items():
        lengths = sorted(len(text) for text in shown)
        print(f"LENGTHS {name}: {len(lengths)} entries, longest {lengths[-1]}, median {lengths[len(lengths) // 2]}")
