"""Manual spending stays transactional; AI healing remains automatic."""
import pytest
from tests.hunt31_support import OWNER, ALLY, fixture, prepare, pick, reload, send, act

BLOOD = 'tianxia.talent.blood.vital_transfusion'
REGEN = 'TAL_DAEMONIC_CULTIVATION_DEMON_BONE_REGENERATION'
ESSENCE = 'resource:named.devoured_essence'
INJURY = {'type': 'damage', 'applies_to': 'target', 'damage_types': ['FORCE'], 'flat': 20}


@pytest.mark.parametrize('auto', [False, True])
@pytest.mark.parametrize('amount', [0, 1, 3])
def test_transfusion_owner_selects_damage(monkeypatch, tmp_path, auto, amount):
    combat, table, mid = fixture(monkeypatch, tmp_path, [BLOOD], setup=[INJURY])
    prepare(table, mid, ALLY)
    cid = pick(table, mid, 'Vital Transfusion', ALLY)
    before = reload(combat, mid).state.actors[OWNER].current_hp
    before_state = reload(combat, mid).state.model_dump(mode='json')
    result = send(combat, table, mid, cid, auto)
    if not auto:
        assert result['status'] == 'REACTION_REQUIRED'
        prompt = result['reaction']
        assert 'Vital Transfusion' in str(prompt) and prompt['affected'] == 'Factory character'
        assert prompt['title'] == 'Vital Transfusion'
        assert reload(combat, mid).state.actors[OWNER].current_hp == before
        assert reload(combat, mid).state.model_dump(mode='json') == before_state
        if amount == 1:
            invalid = str(int(prompt['choice']['options'][-1]['id']) + 1)
            with pytest.raises(Exception):
                send(combat, table, mid, cid, auto, [{**prompt['context'], 'selection': 'USE', 'option_ids': [invalid]}])
            assert reload(combat, mid).state.actors[OWNER].current_hp == before
        answer = {**prompt['context'], 'selection': 'USE' if amount else 'DECLINE',
                  'option_ids': [str(amount)] if amount else []}
        result = send(combat, table, mid, cid, auto, [answer])
    assert result['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    actor, target = engine.state.actors[OWNER], engine.state.actors[ALLY]
    if auto:
        assert actor.current_hp < before
    else:
        assert actor.current_hp == before - amount
    assert target.current_hp == target.maximum_hp - 20 + (before - actor.current_hp)


@pytest.mark.parametrize('auto_trigger', [False, True])
@pytest.mark.parametrize('use', [False, True])
def test_regeneration_manual_owner_chooses_on_any_turn(monkeypatch, tmp_path, auto_trigger, use):
    setup = [{**INJURY, 'applies_to': 'self'},
             {'type': 'condition', 'condition': 'stance.demon_seed', 'applies_to': 'self', 'duration': 'until_removed'}]
    combat, table, mid = fixture(monkeypatch, tmp_path, [REGEN], setup=setup, resources={ESSENCE: 3})
    prepare(table, mid, OWNER)
    seeded = reload(combat, mid).state.actors[OWNER]
    assert seeded.current_hp == seeded.maximum_hp - 20
    assert any(c.condition_id == 'condition:typed.stance.demon_seed' for c in seeded.conditions.values())
    # Advance to the last other actor; its end-turn intent starts the owner's turn.
    assert act(table, mid, table.state(mid)['menu']['end_turn'])['status'] == 'COMMITTED'
    for _ in range(3):
        engine = reload(combat, mid)
        order = engine.state.initiative_order
        if order[(order.index(engine.state.current_actor_id) + 1) % len(order)] == OWNER:
            break
        assert act(table, mid, table.state(mid)['menu']['end_turn'])['status'] == 'COMMITTED'
    cid = table.state(mid)['menu']['end_turn']
    actor = table.state(mid)['menu']['actor_id']
    before = reload(combat, mid).state.actors[OWNER].current_hp
    before_state = reload(combat, mid).state.model_dump(mode='json')
    result = send(combat, table, mid, cid, auto_trigger, actor=actor)
    assert result['status'] == 'REACTION_REQUIRED'
    prompt = result['reaction']
    assert 'Demon Bone Regeneration' in str(prompt)
    assert prompt['title'] == 'Demon Bone Regeneration'
    assert reload(combat, mid).state.actors[OWNER].resources[ESSENCE] == 3
    assert reload(combat, mid).state.model_dump(mode='json') == before_state
    answer = {**prompt['context'], 'selection': 'USE' if use else 'DECLINE', 'option_ids': ['1'] if use else []}
    assert send(combat, table, mid, cid, auto_trigger, [answer], actor=actor)['status'] == 'COMMITTED'
    target = reload(combat, mid).state.actors[OWNER]
    assert target.resources[ESSENCE] == 3 - int(use)
    assert (target.current_hp > before) == use


def test_transfusion_payment_can_exceed_missing_hp(monkeypatch, tmp_path):
    combat, table, mid = fixture(monkeypatch, tmp_path, [BLOOD], setup=[{**INJURY, 'flat': 1}])
    prepare(table, mid, ALLY)
    cid = pick(table, mid, 'Vital Transfusion', ALLY)
    result = send(combat, table, mid, cid, False)
    prompt = result['reaction']
    amount = int(prompt['choice']['options'][-1]['id'])
    assert amount > 1
    answer = {**prompt['context'], 'selection': 'USE', 'option_ids': [str(amount)]}
    assert send(combat, table, mid, cid, False, [answer])['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    assert engine.state.actors[OWNER].current_hp == engine.state.actors[OWNER].maximum_hp - amount
    assert engine.state.actors[ALLY].current_hp == engine.state.actors[ALLY].maximum_hp


def test_regeneration_ai_owner_spends_automatically(monkeypatch, tmp_path):
    setup = [{**INJURY, 'applies_to': 'self'},
             {'type': 'condition', 'condition': 'stance.demon_seed', 'applies_to': 'self', 'duration': 'until_removed'}]
    combat, table, mid = fixture(monkeypatch, tmp_path, [REGEN], setup=setup, resources={ESSENCE: 3})
    prepare(table, mid, OWNER)
    assert act(table, mid, table.state(mid)['menu']['end_turn'])['status'] == 'COMMITTED'
    for _ in range(3):
        engine = reload(combat, mid)
        order = engine.state.initiative_order
        if order[(order.index(engine.state.current_actor_id) + 1) % len(order)] == OWNER:
            break
        assert act(table, mid, table.state(mid)['menu']['end_turn'])['status'] == 'COMMITTED'
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    assert act(table, mid, table.state(mid)['menu']['end_turn'])['status'] == 'COMMITTED'
    actor = reload(combat, mid).state.actors[OWNER]
    assert actor.resources[ESSENCE] == 2 and actor.current_hp > actor.maximum_hp - 20
