"""Plain decision summaries at a real damage/reload boundary."""
import pytest

from combat.decision_text import plain
from combat.gate5_service import CombatService
from tests.test_tabletop_hunt6 import table_fight, LEFT, RIGHT
from tests.test_lock2_persistence import act
from tests.test_carry import KIT
from tests.r10_fixup_support import cast_sender, fixed_dice


@pytest.mark.parametrize("cl,dice", [(10, 1), (15, 2), (17, 3)])
def test_shadow_ward_plain_amount_at_table(tmp_path, monkeypatch, cl, dice):
    combat, table, mid = table_fight(tmp_path, ["tianxia.talent.shadow.shadow_ward"], cl=cl,
                                     kit={"starting_kit": KIT}, ask=True, ally_talents=[])
    while table.state(mid)["menu"]["actor_id"] != RIGHT:
        assert act(table, mid, "end")["status"] == "COMMITTED"
    fixed_dice(monkeypatch, [20, 20] + [4] * 40)
    send = cast_sender(combat, table, mid, "Bi Shou (Dagger) thrown", target=LEFT)
    answers = []
    prompts = []
    for _ in range(12):
        result = send(answers)
        if result["status"] == "COMMITTED":
            break
        p = result["reaction"]
        prompts.append(p)
        answers.append({**p["context"], "selection": "DECLINE"})
    ward = next(p for p in prompts if p["reaction"] == "Shadow Ward")
    assert f"{dice}d8 + 2" in ward["summary"]
    assert "|" not in ward["summary"]
    assert "triggering damage" in ward["summary"]
    assert "Shadowed Space" in ward["summary"]
    assert "1" in ward["cost"] and "Reaction" in ward["cost"]
    assert CombatService(combat.source_root, tmp_path)._load_session(mid).mechanical.replay()["status"] == "PASS"


def test_generic_printed_tables_become_labelled_rows():
    text = "Choose a result:\n| Level | Benefit |\n| --- | --- |\n| 1-10 | +2 AC |\n| 11-20 | +3 AC |"
    result = plain(text)
    assert "|" not in result and "---" not in result
    assert "Level: 1-10; Benefit: +2 AC" in result
    assert "Level: 11-20; Benefit: +3 AC" in result


def test_all_printed_rule_tables_are_plain_in_decision_text():
    import json
    import re
    from pathlib import Path
    rules = json.loads((Path(__file__).resolve().parents[1] /
                        "authority/typed_mechanics/rules_text.json").read_text())
    checked = 0
    for source, text in rules.items():
        if not any("|" in line and "---" in line for line in text.splitlines()):
            continue
        checked += 1
        result = plain(text)
        assert not any(line.lstrip().startswith("|") for line in result.splitlines()), source
        assert not re.search(r"\|\s*:?-{3,}", result), source
    assert checked > 0
