"""Native Starpath range delivery; the parent remains open for carry/anchors.

No owner rows or live-engine metadata are injected. The ordinary portable
Insight field compiles ownership and the table commits the printed paid action.
"""
import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from tests.test_a2_stars_insights import fight, PATH
from tests.auto_worker1_support import LEFT, act, reload, resolve, turn, RIGHT

OWNER = "insight.star-walking-immortal"
SOURCE_HASH = "086759d9a973bf90f989ebf2681920e708c617fb31c1284d9f00f62fa4310749"


def test_controlling_source_is_exact():
    rules = json.loads((Path(__file__).parents[1] / "authority/typed_mechanics/rules_text.json").read_text())
    assert hashlib.sha256(rules[OWNER].encode()).hexdigest() == SOURCE_HASH


@pytest.mark.parametrize("owned,feet", [(False, 20), (True, 40)])
def test_native_paid_step_range_survives_table_commit_reload_and_replay(tmp_path, owned, feet):
    combat, table, mid = fight(tmp_path, [PATH] + ([OWNER] if owned else []),
                              spheres=["tianxia.sphere.stars"])
    before = reload(combat, mid).state.actors[LEFT]
    movement = before.movement_remaining_ft
    resources = dict(before.resources)
    # Repeated menu previews must neither spend payment nor grant movement.
    table.state(mid)
    table.state(mid)
    assert reload(combat, mid).state.actors[LEFT].movement_remaining_ft == movement
    resolve(lambda answers: act(table, mid, "Starpath Step", answers))
    engine = reload(combat, mid)  # helper also performs mechanical replay
    actor = engine.state.actors[LEFT]
    grants = [e for e in engine.events if e.event_type == "MOVEMENT_GRANTED" and e.actor_id == LEFT]
    assert grants[-1].payload["distance_ft"] == feet
    assert actor.movement_remaining_ft == movement + feet
    assert actor.turn_flags["oa_free_ft"] == feet
    assert sum(resources.values()) - sum(actor.resources.values()) == 1
    assert not actor.bonus_action_available
    step = next(a for a in engine.action_catalog.values() if a.display_name == "Starpath Step")
    if owned:
        assert step.parameters["star_walking_range_source"] == {
            "feature_id": OWNER, "text_sha256": SOURCE_HASH, "distance_ft": 20}
    else:
        assert "star_walking_range_source" not in step.parameters
    # Actually spend some of the native grant through a table move, not a
    # direct coordinate edit; reload also verifies the movement journal.
    state = table.state(mid)
    move = next(m for m in state["menu"]["moves"]
                if m["destination"] == {"x": 3, "y": 5})
    resolve(lambda answers: table.act(mid, move["candidate_id"], state["menu"]["decision_id"],
                                      state["menu"]["state_version"], state["last_sequence"], answers))
    moved = reload(combat, mid).state.actors[LEFT]
    assert (moved.position.x, moved.position.y) == (3, 5)
    assert moved.movement_remaining_ft == movement + feet - 5
    assert moved.turn_flags["oa_free_ft"] == feet - 5
    turn(table, mid, RIGHT)
    turn(table, mid, LEFT)
    actor = reload(combat, mid).state.actors[LEFT]
    assert not actor.turn_flags.get("oa_free_ft")
    assert not any(c.condition_id == "condition:typed.ignore_difficult" for c in actor.conditions.values())


def test_parent_does_not_extend_seven_star_step(tmp_path):
    combat, table, mid = fight(tmp_path, [OWNER, "tianxia.talent.stars.seven_star_step"],
                              spheres=["tianxia.sphere.stars"])
    resolve(lambda answers: act(table, mid, "Seven-Star Step", answers))
    engine = reload(combat, mid)
    grants = [e for e in engine.events if e.event_type == "MOVEMENT_GRANTED" and e.actor_id == LEFT]
    assert grants[-1].payload["distance_ft"] == 30


def test_range_composes_with_native_sovereign_variant_without_extra_payment(tmp_path):
    combat, table, mid = fight(tmp_path, [OWNER, PATH, "tianxia.talent.stars.star_sovereign_incarnation"],
                              cl=17, spheres=["tianxia.sphere.stars"])
    resolve(lambda answers: act(table, mid, "Star-Sovereign Incarnation", answers))
    # Incarnation itself spends the Bonus Action. Advance real turns before
    # declaring Step rather than resetting economy flags in a live engine.
    turn(table, mid, RIGHT)
    turn(table, mid, LEFT)
    before = dict(reload(combat, mid).state.actors[LEFT].resources)
    name = "Starpath Step (Star-Sovereign: 80 feet, no cost)"
    resolve(lambda answers: act(table, mid, name, answers))
    engine = reload(combat, mid)
    grants = [e for e in engine.events if e.event_type == "MOVEMENT_GRANTED" and e.actor_id == LEFT]
    assert grants[-1].payload["distance_ft"] == 80
    assert engine.state.actors[LEFT].resources == before
    assert name not in {g["label"] for g in table.state(mid)["menu"]["actions"]}


def test_range_transform_preserves_conditional_alignment_row():
    from combat.factory_compiler import compile_character
    from tests.h1_support import sheet

    doc = sheet([PATH], cl=8)
    doc["spheres_and_talents"]["cultivation_insight_record_ids"] = [OWNER]
    bundle = compile_character(doc, actor_id=LEFT)
    action = next(a for a in bundle["action_catalog"] if a["display_name"] == "Starpath Step")
    effects = action["parameters"]["typed"]["effects"]
    assert effects[0]["distance_ft"] == 40
    aligned = next(e for e in effects if e["type"] == "if_state")
    assert aligned["effects"][0]["distance_ft"] == 10
    assert action["range_ft"] == 40
    boundary = next(row for row in bundle["diagnostics"]["insights"] if row["id"] == OWNER)
    assert len(boundary["gm_decides"]) == 2
    assert any("20 feet" in line for line in boundary["table_applies"])
    assert any("Once per scene" in line for line in boundary["gm_decides"])


@pytest.mark.parametrize("source_hash", [None, "unknown-source"])
def test_unavailable_or_different_owner_source_does_not_grant_bonus(source_hash):
    from combat.factory_compiler import compile_character, TYPED_AUTHORITY
    from tests.h1_support import sheet

    doc = sheet([PATH], cl=8)
    doc["spheres_and_talents"]["cultivation_insight_record_ids"] = [OWNER]
    # Negative authority control only: positive delivery always uses the
    # shipped authority, never an injected ownership or source-status row.
    authority = deepcopy(json.loads(TYPED_AUTHORITY.read_text()))
    authority["mechanics"][OWNER]["source"]["text_sha256"] = source_hash
    bundle = compile_character(doc, actor_id=LEFT, typed_authority=authority)
    action = next(a for a in bundle["action_catalog"] if a["display_name"] == "Starpath Step")
    assert action["parameters"]["typed"]["effects"][0]["distance_ft"] == 20
    assert "star_walking_range_source" not in action["parameters"]
