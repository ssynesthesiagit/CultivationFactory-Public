"""Temporary diagnostic probe for MMXAUTO-EARTH1F8 (deleted after the run)."""
from tests.auto_worker1_support import LEFT, RIGHT, act, fight, reload, turn

WITNESS = "actor:factory.auto111-witness"
MARK = {"type": "mark", "mark": "Burden Mark", "applies_to": "target", "duration": {"kind": "until_removed"}}
GROUND_SCORE = "TAL_EARTH_THE_GROUND_KEEPS_SCORE"
DEEP_ROOT = "TAL_EARTH_DEEP_ROOT_STANCE"
STANDARD = "WARLEADER_BASE_SET_THE_STANDARD"
BRUTE_SHOVE = "BRUTE_BASE_BRUTAL_SHOVE"


def brief(aid):
    return str(aid).split(".")[-1].replace("h15-", "")


def lines(table, mid):
    menu = table.state(mid)["menu"]
    out = [brief(menu["actor_id"])]
    for group in menu["actions"]:
        if "Push" in group["label"] or "Shove" in group["label"]:
            for option in group["options"]:
                out.append(group["label"] + "|" + ",".join(brief(t) for t in (option.get("target_ids") or [])))
    out.append("groups=" + str(len(menu["actions"])))
    return " ".join(out)


def test_probe_shove_enemy(tmp_path):
    combat, table, mid = fight(tmp_path, [GROUND_SCORE], extra_witness=True, prepare=[MARK],
                               right_talents=[BRUTE_SHOVE], right_spheres=["tianxia.sphere.brute"],
                               witness_talents=[STANDARD])
    assert act(table, mid, "Prepare", target_id=RIGHT)["status"] == "COMMITTED"
    turn(table, mid, WITNESS)
    assert act(table, mid, "Set the Standard")["status"] == "COMMITTED"
    turn(table, mid, RIGHT)
    assert False, lines(table, mid)


def test_probe_deep_root(tmp_path):
    combat, table, mid = fight(tmp_path, [GROUND_SCORE, DEEP_ROOT], extra_witness=True, prepare=[MARK],
                               right_talents=[BRUTE_SHOVE], right_spheres=["tianxia.sphere.brute"])
    assert act(table, mid, "Prepare", target_id=RIGHT)["status"] == "COMMITTED"
    turn(table, mid, WITNESS)
    left_menu = table.state(mid)["menu"]["actor_id"]
    assert False, (brief(left_menu), "DeepRoot" in str(table.state(mid)["menu"]["actions"])[:4000])
