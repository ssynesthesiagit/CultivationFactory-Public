"""HUNTCJ1: a Taiyin GM reminder on a missed attack must not apply its effects."""

import pytest

from combat.canonical import canonical_sha256
from combat.factory_compiler import compile_character
from combat.ext.attack_modifiers import enabled_variant
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
def test_missed_withering_hand_with_taiyin_reminder_has_no_stilling_effect(tmp_path, held, capsys):
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
    # Identify exactly the same combined ranged mode, without depending on
    # authority display text (which is scrambled in the public test export).
    combined, = [a for a in before.action_catalog.values()
                 if a.owner_id == OWNER
                 and (typed := a.parameters.get("typed", {})).get("source") == HAND
                 and typed.get("modifier", {}).get("id") == TOUCH
                 and [e.get("attack_kind") for e in typed["effects"]
                      if e.get("type") == "attack"] == ["cultivation_ranged"]]
    legal = before.legal_candidates()
    with capsys.disabled():
        print("TAIYINMISS1 initial menu:", sorted({
            (c.source_definition_id, before.action_catalog[c.source_definition_id].display_name,
             c.target_ids) for c in legal if c.source_definition_id in before.action_catalog}))
        print("TAIYINMISS1 combined row:", combined.source_definition_id, combined.display_name,
              "enabled_variant:", enabled_variant(before, before.state.actors[OWNER], None, combined),
              "(False means the human rider control is off)")

    # Since e1a6c478ef, human variants obey the parent's on/off control.
    # Enable the owned rider with a real table commit, not a state injection.
    parent = combined.parameters["typed"]["attack_modifier_variant"]
    toggle, = [a.source_definition_id for a in before.action_catalog.values()
               if a.owner_id == OWNER
               and (setting := a.parameters.get("attack_modifier_setting", {})).get("family") == parent
               and setting.get("modifier") == TOUCH
               and setting.get("field") == "on" and setting.get("value") == "toggle"]
    settle(table, mid, next(c.candidate_id for c in legal if c.source_definition_id == toggle))
    before = reload(tmp_path, mid)
    chosen = next(c for c in before.legal_candidates()
                  if c.target_ids == (FOE,) and c.source_definition_id == combined.source_definition_id)
    # Pin the reminder to this exact modifier's sealed name/precondition,
    # preserving the assertion on both private and scrambled public authority.
    modifier = combined.parameters["typed"]["modifier"]
    reminder = f'{modifier["name"]}: {modifier["precondition"]}'
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
    assert any(e.payload.get("rider") == reminder
               for e in reminders), [e.payload for e in reminders]
