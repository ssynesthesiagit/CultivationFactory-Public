"""Exact-tip review: committed workpiece locks and current-bearer receipts.

Native compiled inventory and handover supply identities. Eligibility probes on
cold-loaded clones restore only turn/economy so a lock, rather than a spent Bonus
Action, decides admission; these probes never change the committed table.
"""
import json
from pathlib import Path

import pytest
from combat import carry
from combat.ext.blacksmith_forge import held_condition, item_lock_id, mark_count, QUENCH_BREATH
from combat.item_uses import carried_item
from tests.worker2_support import fixture, reload, turn, settle, OWNER, ALLY, FOE
from tests.test_a2_blacksmith import press
from tests.test_a2_blacksmith_second_pass import QUENCH, die
from tests.test_mgr_t13_blacksmith_carriers import select, hammer, marks
from tests.test_mgr_t13_blacksmith_review import KIT, TRAITOR, native_bundles

TWO = 'tianxia.talent.blacksmith.two_beat_temper'
BREATH = 'tianxia.talent.blacksmith.quench_in_breath'


@pytest.fixture(autouse=True)
def native_registry_input():
    """Require the native ownership rows, including in public test exports.

    The runtime loader discovers these shards dynamically. Explicit paths keep
    the fixture's source dependencies visible to the static export resolver;
    an incomplete export must fail here rather than mimic an ability bug.
    """
    root = Path(__file__).resolve().parents[1]
    forge = json.loads((root / 'combat/rules/feature_blocks.d/blacksmith.json').read_text())
    responses = json.loads((root / 'combat/rules/feature_blocks.d/blacksmith_second_pass.json').read_text())
    assert forge['features'][TWO]['kind'] == 'two_beat_temper'
    assert forge['features'][BREATH]['kind'] == 'quench_in_breath'
    assert responses['features'][QUENCH]['kind'] == 'quench'


def build(talents):
    return lambda bundles: native_bundles(bundles, owner_talents=talents)


def hammer_options(engine, target=OWNER):
    """Probe only admission, without advancing/expiring the smith's next turn."""
    engine.state.current_actor_id = OWNER
    engine.state.actors[OWNER].bonus_action_available = True
    before = engine.state.model_dump(mode='json')
    rows = [c for c in engine.legal_candidates()
            if c.display_name == 'Hammer the Mark' and c.target_ids == (target,)]
    assert engine.state.model_dump(mode='json') == before
    return rows


@pytest.mark.parametrize('automatic', [False, True])
def test_actor_lock_does_not_hide_different_selected_item(tmp_path, automatic):
    talents = [QUENCH, TWO]
    combat, table, mid = fixture(tmp_path, talents, ally_talents=[TRAITOR], owner_kit=KIT, ally_kit=KIT, foe_kit=KIT,
        bundle_transform=build(talents))
    press(combat, table, mid, 'Hammer the Mark', picks={'choice:needle.blacksmith_two_beat': ['two']})
    e = reload(tmp_path, mid)
    assert mark_count(e.state.actors[OWNER], OWNER) == 2
    assert held_condition(e.state.actors[OWNER], item_lock_id(OWNER, ''))
    assert not hammer_options(e)  # actor-workpiece behavior stays locked
    assert hammer_options(e, ALLY)  # a different actor workpiece stays legal
    key = carry.carrying_of(e, OWNER)['items'][0]['key']
    select(combat, table, mid, owner=OWNER, key=key)
    if automatic:
        combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    e = reload(tmp_path, mid)
    assert marks(e, owner=OWNER, key=key) == 0
    assert hammer_options(e)  # the physical item has no lock


@pytest.mark.parametrize('automatic', [False, True])
def test_item_lock_follows_native_handover_and_expires(tmp_path, automatic):
    talents = [QUENCH, TWO]
    combat, table, mid = fixture(tmp_path, talents, ally_talents=[TRAITOR], owner_kit=KIT, ally_kit=KIT, foe_kit=KIT,
        foe_position={'x': 4, 'y': 5}, bundle_transform=build(talents))
    e = reload(tmp_path, mid)
    key = carry.carrying_of(e, FOE)['items'][0]['key']
    select(combat, table, mid, owner=FOE, key=key)
    press(combat, table, mid, 'Hammer the Mark', FOE,
          picks={'choice:needle.blacksmith_two_beat': ['two']})
    e = reload(tmp_path, mid)
    assert marks(e, owner=FOE, key=key) == 2
    assert held_condition(e.state.actors[FOE], item_lock_id(OWNER, key))
    turn(table, mid, FOE)
    press(combat, table, mid, 'Native handover', ALLY)
    if automatic:
        combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    e = reload(tmp_path, mid)
    assert carried_item(e, FOE, key)['carrier'] == ALLY
    assert not hammer_options(e, ALLY)
    turn(table, mid, OWNER)
    e = reload(tmp_path, mid)
    assert held_condition(e.state.actors[FOE], item_lock_id(OWNER, key)) is None
    assert hammer_options(e, ALLY)
    # Admission above uses the automatic seat too. The explicit one-mark
    # continuation goes through the player's table API, which requires MANUAL.
    if automatic:
        combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='MANUAL')
    press(combat, table, mid, 'Hammer the Mark', ALLY,
          picks={'choice:needle.blacksmith_two_beat': ['one']})
    assert marks(reload(tmp_path, mid), owner=FOE, key=key) == 3


@pytest.mark.parametrize('breath', [False, True])
@pytest.mark.parametrize('accept', [False, True])
def test_transferred_mark_spend_notifies_current_bearer(tmp_path, monkeypatch, breath, accept):
    die(monkeypatch)
    talents = [QUENCH] + ([BREATH] if breath else [])
    combat, table, mid = fixture(tmp_path, talents, ally_talents=[TRAITOR], owner_kit=KIT, ally_kit=KIT, foe_kit=KIT,
        foe_position={'x': 4, 'y': 5}, extra_foes=1, bundle_transform=build(talents))
    e = reload(tmp_path, mid)
    key = carry.carrying_of(e, FOE)['items'][0]['key']
    source = carry.item_of(carry.carrying_of(e, FOE), key=key)['weapon_action']
    select(combat, table, mid, owner=FOE, key=key)
    hammer(combat, table, mid)
    turn(table, mid, FOE)
    press(combat, table, mid, 'Native handover', ALLY)
    turn(table, mid, ALLY)
    press(combat, table, mid, 'Defeat original owner', FOE)
    e = reload(tmp_path, mid)
    assert not e.state.actors[FOE].active
    assert carried_item(e, FOE, key)['carrier'] == ALLY
    borrowed = next(a for a in e.action_catalog.values() if a.owner_id == ALLY
        and a.parameters.get('requires_held_weapon') == source and '#' not in a.source_definition_id)
    candidate = next(c for c in e.legal_candidates() if c.source_definition_id == borrowed.source_definition_id
        and c.target_ids == (FOE + '1',))
    settle(table, mid, candidate.candidate_id,
        picks={'choice:needle.blacksmith_quench': ['quench'] if accept else None})
    e = reload(tmp_path, mid)
    assert marks(e, owner=FOE, key=key) == (0 if accept else 1)
    assert e.state.actors[OWNER].reaction_available == (not accept)
    assert bool(held_condition(e.state.actors[ALLY], QUENCH_BREATH)) == (breath and accept)
    assert not held_condition(e.state.actors[FOE], QUENCH_BREATH)
    assert not held_condition(e.state.actors[OWNER], QUENCH_BREATH)
