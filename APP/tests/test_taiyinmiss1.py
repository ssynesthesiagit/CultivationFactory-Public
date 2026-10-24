"""HUNTCJ1: a Taiyin GM reminder on a missed attack must not apply its effects."""

import pytest

from combat.canonical import canonical_sha256
from combat.factory_compiler import compile_character
from tests.h1_support import sheet
from tests.worker2_support import OWNER, FOE, fixture, settle, reload


FOUNDATION = "taiyin_lunar_body_v0_2B"
TOUCH = f"foundation.{FOUNDATION}.taiyin_stilling_touch"
HAND = "TAL_DEATH_WITHERING_HAND"
POOL = "resource:foundation.lunar_yin_dew"
KIT = {"starting_kit": {"items": [
    {"item_id": "tianxia.mortal.weapon.jian", "name": "Jian", "quantity": 1},
]}}


@pytest.mark.parametrize("held", [0, 1])
def test_missed_withering_hand_with_taiyin_reminder_has_no_stilling_effect(tmp_path, held):
    doc = sheet([HAND, TOUCH, "tianxia.path.body_refining.feature.extra_attack"],
                cl=10, kit=KIT)
    doc["foundation"] = {
        "foundation_id": FOUNDATION, "stage": "Awakened",
        "resource": {"name": "Lunar Yin Dew", "maximum": 1, "current": held,
                     "resource_id": f"tianxia.resource.foundation.{FOUNDATION}"},
    }
    owner = compile_character(doc, actor_id=OWNER, reaction_plan={"ask": True})
    for action in owner["action_catalog"]:
        typed = action.get("parameters", {}).get("typed", {})
        if typed.get("source") == HAND:
            typed["numbers"]["attack_bonus"] = -100
    owner.pop("bundle_sha256", None)
    owner["bundle_sha256"] = canonical_sha256(owner)
    combat, table, mid = fixture(
        tmp_path, [], owner_bundle=owner, seed="TAIYINMISS1", ask=True,
        positions={OWNER: {"x": 3, "y": 5},
                   "actor:factory.worker2-ally": {"x": 3, "y": 7},
                   FOE: {"x": 8, "y": 5}},
    )
    before = reload(tmp_path, mid)
    chosen = next(c for c in before.legal_candidates()
                  if c.target_ids == (FOE,)
                  and before.action_catalog[c.source_definition_id].display_name
                  == "Withering Hand + Taiyin Stilling Touch (ranged)")
    actor, target = before.state.actors[OWNER], before.state.actors[FOE]
    assert actor.resources[POOL] == held
    hp, conditions, modifiers = target.current_hp, dict(target.conditions), dict(target.modifiers)
    resources = dict(actor.resources)
    sequence = before.state.event_sequence

    assert settle(table, mid, chosen.candidate_id) == [], "A miss must not ask to spend Dew"
    after = reload(tmp_path, mid)
    events = [e for e in after.events if e.sequence > sequence]
    rolls = [e for e in events if e.event_type == "ATTACK_ROLLED"]
    assert len(rolls) == 1 and rolls[0].payload["provisional_hit"] is False
    assert after.state.pending_resolution is None
    assert not any(e.event_type in {"DAMAGE_COMMITTED", "RESOURCE_SPENT", "CONDITION_APPLIED"}
                   for e in events)
    actor, target = after.state.actors[OWNER], after.state.actors[FOE]
    assert actor.resources == resources
    assert (target.current_hp, target.conditions, target.modifiers) == (hp, conditions, modifiers)

    # Reproduce the misleading reminder without prescribing the unrelated
    # Special Attack remainder handler's behavior for the ranged mode.
    reminders = [e for e in events if e.event_type == "GM_RIDER"]
    assert any(e.payload.get("rider") == "Taiyin Stilling Touch: while you have Lunar Yin Dew"
               for e in reminders), [e.payload for e in reminders]
