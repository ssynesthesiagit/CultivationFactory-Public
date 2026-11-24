"""SHEETHANDS1: the sheet's ACTIONS tab groups physical weapon copies and follows the fight's grip state.

Owner 2026-10-22: stowed weapons were offered and each javelin copy was its own row
("Biao Qiang (Javelin) (copy 2)").  These tests drive the real TabletopService/sheet path:
the table's own menu and unavailable reasons decide legality, and the sheet draws one row
per weapon kind with the physical copy ids underneath.
"""
import shutil

from combat.ext.hand_occupancy import free_hands, weapon_grips
from tests.auto_worker1_support import LEFT, RIGHT, fight
from tests.equipment_readiness import ready_table_weapon
from tests.hunt15_support import act

W = "tianxia.mortal.weapon."
KIT = {"items": [
    {"item_id": W + "jian", "name": "Jian (Straight Sword)", "quantity": 1},
    {"item_id": W + "bi_shou", "name": "Bi Shou (Dagger)", "quantity": 1},
    {"item_id": W + "biao_qiang", "name": "Biao Qiang (Javelin)", "quantity": 2},
], "wielded": [W + "jian"]}


def weapon_action(engine, suffix):
    return next(action.source_definition_id for action in engine.action_catalog.values()
                if action.owner_id == LEFT and action.source_definition_id.endswith(suffix))


def state_copies(table, mid, actor_id=LEFT):
    state = table.state(mid)
    row = next(row for row in state["presentation"]["actors"] if row["entity_id"] == actor_id)
    return row.get("weapon_copies") or []


def fresh_sheet(table, tmp_path, source="h15-left", project="deadbeef"):
    shutil.copytree(tmp_path / "portable_characters" / source, tmp_path / "portable_characters" / project)
    return table.sheet(project)


def test_sheet_draws_one_row_per_weapon_kind_with_physical_copies_underneath(tmp_path):
    combat, table, mid = fight(tmp_path, [], left_kit=KIT,
                               spheres=["tianxia.sphere.berserker"])
    sheet = fresh_sheet(table, tmp_path)
    rows = sheet["buttons"]
    visible = [row for row in rows if row.get("weapon_copy") and not row.get("copy_of")]
    labels = {row["label"]: row for row in visible}

    attack = labels["Biao Qiang (Javelin) attack ×2"]
    thrown = labels["Biao Qiang (Javelin) thrown ×2"]
    for row in (attack, thrown):
        assert len(row["copies"]) == 2
        assert row["copies"][0].endswith(".weapon.biao_qiang") or row["copies"][0].endswith(".weapon.biao_qiang#thrown")
        # The carried action behind each drawn id: thrown rows are variants of the same copies,
        # so the table's weapon_copies list can still count them.
        assert [copy.removeprefix("act:").split("#", 1)[0] for copy in row["copies"]] == row["copy_keys"]
        assert sum(1 for other in rows if other.get("copies") == row["copies"]
                   and not other.get("copy_of")) == 1
    # The owner's Batter/Disarm-style per-weapon variants group the same way.
    assert len(labels["Batter: Biao Qiang (Javelin) ×2"]["copies"]) == 2
    assert len(labels["Batter: Biao Qiang (Javelin) thrown ×2"]["copies"]) == 2
    # A single dagger keeps its original row and label.
    assert labels["Bi Shou (Dagger) attack"].get("copies") is None
    # No visible weapon row still carries the compiler's per-copy suffix.
    assert not any("(copy 2)" in row["label"] for row in visible)


def test_stowed_rows_are_refused_until_drawn_and_throwing_frees_the_hand(tmp_path):
    combat, table, mid = fight(tmp_path, [], left_kit=KIT)
    engine = combat._load_session(mid).engine
    attack = weapon_action(engine, ".weapon.biao_qiang")
    thrown = weapon_action(engine, ".weapon.biao_qiang#thrown")
    dagger = weapon_action(engine, ".weapon.bi_shou")
    copy2 = weapon_action(engine, ".weapon.biao_qiang.copy2")
    copy2_thrown = weapon_action(engine, ".weapon.biao_qiang.copy2#thrown")

    state = table.state(mid)
    reasons = state.get("unavailable_reasons") or {}
    for source in (dagger, attack, thrown, copy2, copy2_thrown):
        assert "Draw" in reasons[f"act:{source}"]
    assert not any(group["source_definition_id"] in (dagger, attack, thrown, copy2, copy2_thrown)
                   for group in state["menu"]["actions"])
    assert attack in state_copies(table, mid) and copy2 in state_copies(table, mid)

    # Drawing one javelin makes exactly that copy's rows usable.
    ready_table_weapon(table, mid, attack)
    state = table.state(mid)
    reasons = state.get("unavailable_reasons") or {}
    assert "" == reasons.get(f"act:{attack}", "") == reasons.get(f"act:{thrown}", "")
    assert "Draw" in reasons[f"act:{dagger}"]  # the dagger is still stowed
    group = next(group for group in state["menu"]["actions"] if group["source_definition_id"] == thrown)
    option = next(option for option in group["options"] if RIGHT in (option.get("target_ids") or []))
    assert table.act(mid, option["candidate_id"], state["menu"]["decision_id"],
                     state["menu"]["state_version"], state["last_sequence"])["status"] == "COMMITTED"

    # The thrown copy leaves the hand and the table's possession count (and so the sheet's
    # ×N) drops to the spare.
    engine = combat._load_session(mid).engine
    holder = engine.state.actors[LEFT]
    assert attack not in weapon_grips(engine, holder)
    assert free_hands(engine, holder)
    assert attack not in state_copies(table, mid)
    assert copy2 in state_copies(table, mid)

    # Next turn the spare is still stowed; drawing it makes its rows usable again.
    assert act(table, mid, "end")["status"] == "COMMITTED"
    assert act(table, mid, "end")["status"] == "COMMITTED"
    assert table.state(mid)["menu"]["actor_id"] == LEFT
    ready_table_weapon(table, mid, copy2)
    engine = combat._load_session(mid).engine
    assert copy2 in weapon_grips(engine, engine.state.actors[LEFT])
    state = table.state(mid)
    group = next(group for group in state["menu"]["actions"]
                 if group["source_definition_id"] == copy2_thrown)
    assert any(RIGHT in (option.get("target_ids") or []) for option in group["options"])
