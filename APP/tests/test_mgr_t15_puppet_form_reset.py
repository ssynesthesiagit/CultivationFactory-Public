"""F15R2 optional: the prepared puppet vessel fixes its form only while it is carried and intact.

vessel_actions() offers the Vessel form picks for an ordinary vessel. A prepared vessel that is broken
or left behind no longer holds the form, so the picks must come back; a carried intact prepared vessel
keeps them withdrawn. Without the reset, the picks vanish after the item is broken or left behind.
"""
from combat.ext import vessel

PID_ITEM = "puppet:0123456789abcdef01234567"


def _info(sheet_vessel, carried):
    items = [{"combat_item_key": PID_ITEM}] if carried else []
    return {"spheres": [vessel.SPHERE], "short": "puppet", "actor_id": "actor:factory.x",
            "numbers": {"cl": 1}, "owned_ids": [], "passives": [], "primary": "qi",
            "owner_sheet": {"puppet_initiation": {"vessel": sheet_vessel} if sheet_vessel else {}},
            "kit": {"items": items}, "actions": []}


def _forms(actions):
    return sorted(a.display_name for a in actions or () if a.display_name.startswith("Vessel form"))


PREPARED = {"item_instance_id": PID_ITEM, "form": "piercing", "hp": 4, "broken": 0}


def test_an_intact_carried_prepared_vessel_keeps_its_form_fixed():
    assert _forms(vessel.vessel_actions(_info(dict(PREPARED), carried=True))) == []


def test_a_broken_prepared_vessel_releases_the_form_picks_for_the_next_vessel():
    assert _forms(vessel.vessel_actions(_info({**PREPARED, "broken": 1}, carried=True))) != []


def test_a_left_behind_prepared_vessel_releases_the_form_picks_for_the_next_vessel():
    assert _forms(vessel.vessel_actions(_info(dict(PREPARED), carried=False))) != []


def test_no_prepared_vessel_offers_the_form_picks():
    assert _forms(vessel.vessel_actions(_info(None, carried=False))) != []

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
