"""PLAYTEST1014: attack paths and cone sources across table commit/cold reload."""
from types import SimpleNamespace

import pytest

from combat import typed_executor as te, zones
from combat.gate2_runtime_models import Position, ZoneState
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, script
from tests import test_tabletop_hunt6 as H
from tests.test_lock2_persistence import act
from tests.r10_fixup_support import cast_sender, commit

CANOPY = 'TAL_VERDANT_GROWTH_CANOPY_OF_TEN_THOUSAND_LEAVES'
BREATH = 'TAL_DAEMONIC_CULTIVATION_HUNGER_REFINING_BREATH'
AUGMENT = 'TAL_DAEMONIC_CULTIVATION_DAEMONIC_AUGMENT'
GUARD = 'tianxia.path.body_refining.feature.stamina_guard'


def cold(data, mid):
    combat = CombatService(ROOT, data)
    table = TabletopService(combat, data)
    loaded = combat._load_session(mid)
    assert loaded.mechanical.replay()['status'] == 'PASS'
    return combat, table, loaded.engine


@pytest.mark.parametrize('resolver,delivery,attacker_at,target_at,expected', [
    ('native', 'ranged', (10, 4), (3, 4), 'DISADVANTAGE'),
    ('typed', 'ranged', (10, 4), (3, 4), 'DISADVANTAGE'),
    ('portable', 'ranged', (10, 4), (3, 4), 'DISADVANTAGE'),
    ('native', 'ranged', (2, 4), (3, 4), 'NORMAL'),  # both inside
    ('native', 'ranged', (10, 4, 1), (3, 4, 1), 'DISADVANTAGE'),
    ('native', 'ranged', (2, 4, 1), (3, 4, 1), 'NORMAL'),  # both inside above aim plane
    ('native', 'ranged', (10, 4), (7, 4), 'NORMAL'),  # less than ten feet
    ('native', 'melee', (10, 4), (3, 4), 'NORMAL'),
])
def test_canopy_ranged_crossing_table_cold_reload(monkeypatch, tmp_path, resolver, delivery, attacker_at, target_at, expected):
    combat, table, mid = H.table_fight(tmp_path, [CANOPY],
        ally_talents=['POISON_BASE_DELIVER_THE_DOSE', 'tianxia.talent.poison.corrosive_dose'])
    # Create the actual compiled canopy through the player's placement picker.
    commit(cast_sender(combat, table, mid, 'Canopy of Ten Thousand Leaves'),
           lambda p: ('cell:3,4,0', True) if p.get('choice') else (None, False))
    combat, table, engine = cold(tmp_path, mid)
    canopy = next(z for z in zones.typed_zones(engine) if z.trigger_profile['name'] == 'Canopy of Ten Thousand Leaves')
    assert canopy.trigger_profile['obscured'] == 'light'
    # Inject an ordinary native attack in an accepted action so the shared
    # resolver is exercised independently of a particular talent's executor.
    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    while table.state(mid)['menu']['actor_id'] != H.LEFT:
        assert act(table, mid, 'end')['status'] == 'COMMITTED'
    def attack(e):
        attacker, target = e.state.actors[H.ALLY if resolver == 'typed' else H.RIGHT], e.state.actors[H.LEFT]
        attacker.position = Position(x=attacker_at[0], y=attacker_at[1], z=attacker_at[2] if len(attacker_at) > 2 else 0)
        target.position = Position(x=target_at[0], y=target_at[1], z=target_at[2] if len(target_at) > 2 else 0)
        if resolver == 'typed':
            action = next(a for a in e.action_catalog.values() if a.owner_id == H.ALLY
                          and 'Deliver the Dose' in a.display_name and 'Corrosive Dose' in a.display_name)
            typed = dict(action.parameters['typed'])
            typed['numbers'] = {**typed['numbers'], 'attack_bonus': -100}
            ctx = te.Context(e, attacker, action, e._active_intent, typed, [target], target, {})
            te.run_effects(ctx, typed['effects'])
        elif resolver == 'portable':
            from combat.character_runtime_adapter import CharacterCombatRuntimeEngine
            CharacterCombatRuntimeEngine._resolve_character_attack(e, attacker, target, source_id='test:canopy-path', attack_bonus=-100,
                damage=None, damage_type='UNTYPED', intent=e._active_intent, ranged=True)
        else:
            e._resolve_attack_spec(attacker, target, {'attack_profile': 'cultivation_' + delivery,
                'range_ft': 100, 'attack_bonus': -100}, e._active_intent, source_definition_id='test:canopy-path')
    H.on_hold(monkeypatch, attack)
    assert act(table, mid, H.HOLD)['status'] == 'COMMITTED'
    _, _, engine = cold(tmp_path, mid)
    roll = next(e for e in reversed(engine.events) if e.event_type == 'ATTACK_ROLLED')
    assert roll.payload['mode'] == expected
    assert len(roll.payload['dice']) == (2 if expected == 'DISADVANTAGE' else 1)


@pytest.mark.parametrize('mutual,expected', [(False, 'DISADVANTAGE'), (True, 'NORMAL')])
def test_heavy_obscurement_native_attack_table_cold_reload(monkeypatch, tmp_path, mutual, expected):
    combat, table, mid = H.table_fight(tmp_path, [], ally_talents=[], starts={'team1': [[3, 4], [3, 5]], 'team2': [[8, 4]]})
    def attack(e):
        target, attacker = e.state.actors[H.LEFT], e.state.actors[H.RIGHT]
        cells = tuple(Position(x=x, y=4) for x in (range(3, 9) if mutual else [3]))
        z = ZoneState(zone_id='zone:test.heavy', source_definition_id=H.HOLD, owner_id=H.LEFT,
            center=target.position, radius_cells=4, affected_cells=cells,
            concentration_link=False, created_round=e.state.round_number,
            trigger_profile={'kind': 'TYPED', 'obscured': 'heavy', 'triggers': [], 'inside': []})
        e.state.zones[z.zone_id] = z
        e._append_event('ZONE_CREATED', H.HOLD, actor_id=H.LEFT, payload={'zone': z.model_dump(mode='json')})
        e._resolve_attack_spec(attacker, target, {'range_ft': 100, 'attack_bonus': -100},
                               e._active_intent, source_definition_id='test:heavy-path')
    H.on_hold(monkeypatch, attack)
    assert act(table, mid, H.HOLD)['status'] == 'COMMITTED'
    _, _, e = cold(tmp_path, mid)
    roll = next(ev for ev in e.events if ev.event_type == 'ATTACK_ROLLED' and ev.source_definition_id == 'test:heavy-path')
    assert roll.payload['mode'] == expected


def test_own_breath_does_not_damage_caster_or_offer_own_guard_after_reload(tmp_path):
    combat, table, mid = H.table_fight(tmp_path, [BREATH, AUGMENT, GUARD], cl=10,
                                      primary='Stamina', ask=True, ally_talents=[])
    _, _, before = cold(tmp_path, mid)
    hp = before.state.actors[H.LEFT].current_hp
    origin = before.state.actors[H.LEFT].position
    area = {'shape': 'cone', 'size_ft': 30, 'include_self': True}
    aim = Position(x=8, y=4)
    assert not te.in_area(before, origin, aim, origin, area)
    assert te.in_area(before, origin, aim, origin, {**area, 'include_origin': True})
    # The explicit choice must not inherit the default raster's derived cache.
    from combat.area_projection import cells
    assert origin not in cells(before, origin, aim, area)
    assert origin in cells(before, origin, aim, {**area, 'include_origin': True})
    send = cast_sender(combat, table, mid, 'Hunger-Refining Breath', at=(8, 4), contains='Bonus Damage')
    prompts = commit(send, lambda p: ('cell:8,4,0', True) if p.get('choice') and 'square' in p['context']['reaction_source_id'] else (None, False))
    _, _, e = cold(tmp_path, mid)
    assert not any(p.get('reaction') == 'Stamina Guard' for p in prompts)
    assert e.state.actors[H.LEFT].current_hp == hp
    assert not any(ev.event_type in {'DAMAGE_COMMITTED', 'SAVE_ROLLED'}
                   and (H.LEFT in ev.target_ids or ev.event_type == 'SAVE_ROLLED' and ev.actor_id == H.LEFT)
                   and BREATH in ev.source_definition_id for ev in e.events)
    assert any(ev.event_type == 'DAMAGE_COMMITTED' and H.RIGHT in ev.target_ids
               and BREATH in ev.source_definition_id for ev in e.events)


def test_hostile_breath_guard_prompt_names_actual_source_and_target_after_reload(monkeypatch, tmp_path):
    combat, table, mid = H.table_fight(tmp_path, [GUARD], cl=10, primary='Stamina', ask=True,
                                      ally_talents=[BREATH, AUGMENT])
    def breath(e):
        caster, target = e.state.actors[H.ALLY], e.state.actors[H.LEFT]
        action = next(a for a in e.action_catalog.values() if a.owner_id == H.ALLY
                      and BREATH in a.source_definition_id and 'Bonus Damage' in a.display_name)
        script(e, [1] * 100)
        intent = SimpleNamespace(destination=Position(x=3, y=3), target_ids=(), option_ids=())
        te.resolve_typed(e, caster, None, action, intent, e._active_intent)
    H.on_hold(monkeypatch, breath)
    cold(tmp_path, mid)
    state = table.state(mid)
    menu = state['menu']
    cid = next(g['options'][0]['candidate_id'] for g in menu['actions'] if g['source_definition_id'] == H.HOLD)
    send = lambda answers=(): table.act(mid, cid, menu['decision_id'], menu['state_version'], state['last_sequence'], list(answers))
    prompts = commit(send, lambda p: (None, False))
    guards = [p for p in prompts if p.get('reaction') == 'Stamina Guard']
    assert guards
    for prompt in guards:
        assert 'Ally' in prompt['trigger'] and 'Left' in prompt['trigger']
        assert 'Hunger-Refining Breath' in prompt['trigger']
        assert "Left's Hunger" not in prompt['trigger']
        assert prompt['trigger_actor'] == 'Ally'
    _, _, e = cold(tmp_path, mid)
    assert any(ev.event_type == 'DAMAGE_COMMITTED' and ev.actor_id == H.ALLY
               and H.LEFT in ev.target_ids and BREATH in ev.source_definition_id for ev in e.events)
