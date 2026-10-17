"""GROW1: ability-score entries in the table growth record (combat/table_advance.py). A finished character's scores can
change (GM respec now, level increases later) and every score-derived number is recomputed; the sealed install is never
touched. Synthetic sheet only, so this runs in public CI."""

import hashlib
import json

import pytest

from combat import table_advance as ta

ABILITIES = ["STR", "DEX", "CON", "INT", "WIS", "CHA"]
OLD = {"STR": 8, "DEX": 15, "CON": 14, "INT": 14, "WIS": 12, "CHA": 14}
NEW = {"STR": 8, "DEX": 14, "CON": 18, "INT": 10, "WIS": 16, "CHA": 12}


def sheet(scores=OLD, cl=4):
    mods = {a: ta.ability_modifier(scores[a]) for a in ABILITIES}
    con = {"op": "add", "terms": [{"op": "constant", "value": 10}, {"op": "ability_modifier", "ability": "CON"}, {"op": "pb", "value": 2}]}
    return {
        "identity": {"cultivation_level": cl, "key_ability": "CON", "proficiency_bonus": 2},
        "ability_scores_and_statistics": {
            "abilities": [{"ability": a, "score": scores[a], "modifier": mods[a]} for a in ABILITIES],
            "armor_class": {"base_value": 10 + mods["CON"] + 2, "calculation": "10 + CON modifier + PB",
                            "formula_trace": {"root": {**con, "value": 10 + mods["CON"] + 2}}},
            "hit_points": {"maximum": 9 + 3 * mods["CON"], "build_state_current": 9 + 3 * mods["CON"],
                           "progression": {"levels": [{"cl": i, "gain": 3 + mods["CON"], "maximum": 3 + mods["CON"] * i} for i in range(1, cl + 1)]}},
            "initiative": {"ability": "DEX", "bonus": mods["DEX"]},
            "skills": [{"skill": "Endurance", "ability": "CON", "bonus": mods["CON"] + 2},
                       {"skill": "Lore", "ability": "INT", "bonus": mods["INT"] + 2}],
            "technique_attack_bonus": mods["CON"] + 2,
            "technique_save_dc": 8 + mods["CON"] + 2,
        },
    }


def stats(s):
    b = s["ability_scores_and_statistics"]
    return {
        "abilities": {r["ability"]: (r["score"], r["modifier"]) for r in b["abilities"]},
        "ac": b["armor_class"]["base_value"], "ac_trace": b["armor_class"]["formula_trace"]["root"]["value"],
        "hp": b["hit_points"]["maximum"], "hp_cur": b["hit_points"]["build_state_current"],
        "hp_levels": [(l["gain"], l["maximum"]) for l in b["hit_points"]["progression"]["levels"]],
        "init": b["initiative"]["bonus"], "skills": [r["bonus"] for r in b["skills"]],
        "tab": b["technique_attack_bonus"], "dc": b["technique_save_dc"],
    }


def test_xiahou_case_recomputes_every_number():
    before = sheet()
    after = ta.recompute_from_abilities(before, OLD, NEW)
    b, a = stats(before), stats(after)
    assert a["abilities"]["CON"] == (18, 4)
    assert a["hp"] == b["hp"] + 2 * 4                       # CON mod +2 -> +4, times CL 4
    assert a["hp_cur"] == b["hp_cur"] + 2 * 4               # at maximum, so current moves too
    assert [g for g, _ in a["hp_levels"]] == [g + 2 for g, _ in b["hp_levels"]]
    assert a["ac"] == b["ac"] + 2 and a["ac_trace"] == b["ac_trace"] + 2   # Path AC is 10 + CON + PB
    assert a["tab"] == b["tab"] + 2 and a["dc"] == b["dc"] + 2             # key ability is CON
    assert a["init"] == b["init"]                                           # DEX 15 -> 14 keeps +2
    assert a["skills"] == [b["skills"][0] + 2, b["skills"][1] - 2]          # Endurance (CON) +2, Lore (INT) -2
    assert before == sheet()                                                # input never changed


def test_recompute_then_back_restores_every_number():
    original = sheet()
    there = ta.recompute_from_abilities(original, OLD, NEW)
    back = ta.recompute_from_abilities(there, NEW, OLD)
    drop = lambda s: {k: v for k, v in s.items() if k != "table_advancement"}
    assert drop(back) == drop(original)


def test_apply_with_entry_recomputes_and_removing_restores():
    base = sheet(cl=4)
    doc = ta.normalized({"abilities": [{"type": "ability", "reason": "level_increase", "cl": 4,
                                        "changes": {"CON": 2}, "note": "CON training"}]})
    assert ta.normalized(doc)["abilities"][0]["changes"] == {"CON": 2}
    applied = ta.apply(base, doc)
    assert stats(applied)["abilities"]["CON"] == (16, 3)
    assert stats(applied)["hp"] == stats(base)["hp"] + 1 * 4 and stats(applied)["ac"] == stats(base)["ac"] + 1   # mod +2 -> +3
    assert ta.apply(base, ta.normalized({"abilities": []})) is base   # removing the entry: the untouched sheet


def test_gm_respec_must_be_point_buy_legal():
    s = sheet()
    legal = {"type": "ability", "reason": "gm_respec", "changes": {"STR": 8, "DEX": 14, "CON": 15, "INT": 13, "WIS": 12, "CHA": 10}, "cl": 4}
    assert ta.ability_status(legal, s)["legal"] is True                     # 0+7+9+5+4+2 = 27 points
    over = {**legal, "changes": {**legal["changes"], "INT": 15}}
    assert ta.ability_status(over, s)["legal"] is False                     # 0+7+9+9+4+2 = 31 points, not 27
    spread = {"type": "ability", "reason": "gm_respec", "changes": ta.default_spread("CON"), "cl": 4}
    assert ta.default_spread("CON") == {"CON": 15, "DEX": 14, "WIS": 13, "INT": 12, "CHA": 10, "STR": 8}
    assert ta.ability_status(spread, s)["legal"] is True                    # 9+7+5+4+2+0 = 27
    high = {"type": "ability", "reason": "gm_respec", "changes": {**ta.default_spread("CON"), "CON": 16}, "cl": 4}
    assert ta.ability_status(high, s)["legal"] is False


def test_level_increase_follows_the_stage2_rule():
    s = sheet(cl=4)
    ok = {"type": "ability", "reason": "level_increase", "changes": {"CON": 1, "WIS": 1}, "cl": 4}
    assert ta.ability_status(ok, s)["legal"] is True
    assert ta.ability_status({**ok, "cl": 3}, s)["legal"] is False         # CL 4 only
    assert ta.ability_status(ok, sheet(OLD, cl=7))["legal"] is False       # cannot record a missed CL 4 opportunity later
    assert ta.ability_status({**ok, "changes": {"CON": 2, "WIS": 1}}, s)["legal"] is False   # budget 2
    assert ta.ability_status({**ok, "changes": {"CON": 3, "WIS": -1}}, s)["legal"] is False  # deltas +1/+2
    assert ta.ability_status({**ok, "changes": {"CON": 2}}, sheet(OLD, cl=2))["legal"] is False  # below CL 4
    capped = sheet({**OLD, "CON": 20})
    assert ta.ability_status({"type": "ability", "reason": "level_increase", "changes": {"CON": 2}, "cl": 4}, capped)["legal"] is False


def test_service_rejects_second_level_increase_at_same_cl():
    from combat.tabletop_service import TabletopService, TabletopError

    class Buttons:
        def get(self, _project):
            return {"advancement": {"abilities": [
                {"reason": "level_increase", "cl": 4, "changes": {"CON": 2}, "gm": False}
            ]}}

    class Combat:
        def _factory_owner_sheet(self, _project):
            return sheet(cl=7)

    service = TabletopService.__new__(TabletopService)
    service.combat, service.buttons = Combat(), Buttons()
    with pytest.raises(TabletopError) as error:
        service.add_ability("synthetic-project", {
            "reason": "level_increase", "cl": 4, "changes": {"WIS": 2}
        })
    assert error.value.status_code == 409
    assert "already recorded at CL 4" in str(error.value)


def test_gm_override_marks_an_illegal_entry():
    entry = {"type": "ability", "reason": "gm_respec", "changes": {"CON": 20}, "cl": 4}
    status = ta.ability_status(entry, sheet())
    assert status["legal"] is False and status["reasons"]


def test_normalized_keeps_ability_entry_through_table_commit_reload():
    record = {"abilities": [{"type": "ability", "reason": "level_increase", "cl": 4, "changes": {"CON": 2}, "note": "Training"}]}
    committed = json.dumps(ta.normalized(record))
    reloaded = ta.normalized(json.loads(committed))
    assert ta.empty()["abilities"] == [] and set(reloaded) == set(ta.empty())
    assert reloaded["abilities"] == ta.normalized(record)["abilities"]
    applied = ta.apply(sheet(cl=4), reloaded)
    assert stats(applied)["abilities"]["CON"] == (16, 3)


def test_entry_fields_are_clipped_and_typed():
    row = ta.normalized({"abilities": [{"reason": "gm_respec", "changes": {"CON": "x", "STR": 9, "BOGUS": 1}, "cl": "4", "note": "n" * 300}]})["abilities"][0]
    assert row["changes"] == {"STR": 9, "CON": None} and row["cl"] == 4 and len(row["note"]) == 240
