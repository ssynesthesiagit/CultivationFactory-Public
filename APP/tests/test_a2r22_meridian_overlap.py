"""Overlapping next-check promises expire on the same actual table roll."""
import pytest

from combat.ext import athletics
from tests.auto8f1_table_support import fixture, zero_martial_focus, OWNER, FOE
from tests.cw2_service_support import seal
from tests.test_a2r22_review import (
    COORDINATED, MERIDIAN, add_action, use, held, finish, fake_menu_embeddings,
)


@pytest.mark.parametrize("ability,skill", [("STR", "Athletics"), ("DEX", "Acrobatics")])
def test_overlapping_grants_apply_to_the_same_next_check_after_reload(tmp_path, ability, skill):
    def prepare(bundles):
        zero_martial_focus(bundles)
        for bundle in bundles:
            if bundle["actor_id"] == OWNER:
                # Test-only legal actions use ordinary typed effects and economy.
                add_action(bundle, "Spend focus", [{"type": "spend_resource",
                    "resource_id": athletics.FOCUS, "flat": 1, "applies_to": "self"}])
                bundle["action_catalog"][-1]["economy"] = "NONE"
                bundle["action_catalog"][-1]["parameters"]["free_primary"] = True
                add_action(bundle, "Two qualifying checks", [{"type": "contest_against",
                    "actor_check": {"kind": "check", "ability": ability, "skill": skill},
                    "target_check": {"kind": "check", "ability": "STR"},
                }] * 2, hostile=True)
                bundle["action_catalog"][-1]["economy"] = "BONUS_ACTION"
            seal(bundle)

    g = fixture(tmp_path, [COORDINATED, MERIDIAN], seed="A2R22FF4-" + skill,
                bundle_transform=prepare)
    use(g, "Dash")
    first = held(g["reload_owner"]())[0].instance_id
    g["commit"](g["menu"]()["end_turn"])
    g["to_owner"]()
    assert held(g["reload_owner"]())[0].instance_id == first
    use(g, "Spend focus")
    assert g["reload_owner"]().resources[athletics.FOCUS] == 0
    use(g, "Dash")
    actor = g["reload_owner"]()
    assert len(held(actor)) == 2, "two real Focus restorations overlap before expiry"
    assert first in {c.instance_id for c in held(actor)}
    finish(g)
    g["menu"]()
    assert len(held(g["reload_owner"]())) == 2, "previews do not spend grants"
    previous = len(g["stored_engine"]().events)
    use(g, "Two qualifying checks", target=FOE)
    engine = g["stored_engine"]()
    checks = [event for event in engine.events[previous:]
              if event.event_type == "CHECK_ROLLED"]
    assert len(checks) == 2
    assert [len(event.payload["actor"]["dice"]) for event in checks] == [2, 1]
    assert not held(engine.state.actors[OWNER])
    finish(g)
