"""Form picks designate a new physical vessel whatever the prepared item's state.

The printed choice is made "when you designate the vessel's form": carrying an intact prepared
doll, carrying a broken one, leaving it behind, or having no rest product yet must not change
whether the puppeteer can designate Bludgeoning, Piercing or Slashing for the next vessel.
The prepared item's own form stays what it was made as (see test_puppet_scene_form.py's table test).
"""
import pytest

from combat.ext import vessel

PID_ITEM = "puppet:0123456789abcdef01234567"
ALL_FORMS = ["Vessel form: Bludgeoning", "Vessel form: Piercing", "Vessel form: Slashing"]


def _info(vessel_receipt, carried):
    """`vessel_receipt` is None (no receipt), "learned" (receipt without a rest product) or the item."""
    items = [{"combat_item_key": PID_ITEM}] if carried else []
    receipt: dict = {}
    if isinstance(vessel_receipt, dict):
        receipt["vessel"] = vessel_receipt
    elif vessel_receipt:
        receipt["proficiency"] = "calligraphers_tools"
    return {"spheres": [vessel.SPHERE], "short": "puppet", "actor_id": "actor:factory.x",
            "numbers": {"cl": 1}, "owned_ids": [], "passives": [], "primary": "qi",
            "owner_sheet": {"puppet_initiation": receipt},
            "kit": {"items": items}, "actions": []}


def _forms(actions):
    return sorted(a.display_name for a in actions or () if a.display_name.startswith("Vessel form"))


PREPARED = {"item_instance_id": PID_ITEM, "form": "piercing", "hp": 4, "broken": 0}


@pytest.mark.parametrize("receipt, carried", [
    (None, False),                                  # no initiation receipt at all
    ("learned", False),                             # freshly learned, no completed Long Rest product yet
    (dict(PREPARED), True),                         # intact prepared doll carried
    ({**PREPARED, "broken": 1}, True),              # the doll was broken
    (dict(PREPARED), False),                        # the doll was left behind
])
def test_every_prepared_item_state_leaves_all_three_form_picks_reachable(receipt, carried):
    assert _forms(vessel.vessel_actions(_info(receipt, carried))) == ALL_FORMS


def test_a_character_without_the_puppetry_sphere_is_offered_no_form_picks():
    info = _info(dict(PREPARED), True)
    info["spheres"] = []
    assert _forms(vessel.vessel_actions(info)) == []


def test_a_nested_journey_store_over_the_same_root_shares_the_registry_lock(tmp_path):
    """F15R2 hang: journey_start_combat holds locked() and calls save() on a new JourneyStore.

    journeys is rebuilt on every access, so the nested save used a fresh instance whose depth
    counter was zero and blocked on its own process's flock forever. The lock must nest per root.
    """
    import threading
    from combat.journey import JourneyStore
    root = tmp_path / "Journeys"
    outer, inner = JourneyStore(root), JourneyStore(root)
    done = threading.Event()

    def nested():
        with outer.registry_lock():
            with inner.registry_lock():
                done.set()

    worker = threading.Thread(target=nested, daemon=True)
    worker.start()
    worker.join(timeout=5)
    assert done.is_set(), "a nested registry lock on the same root blocked on its own flock"
