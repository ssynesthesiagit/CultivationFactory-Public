"""Pure cover descriptors and native Table reaction delivery/preview parity."""
import pytest

from combat import ext
from combat.attack_provenance import describe
from combat.directional_cover import tactical_cover
from combat.gate2_runtime_models import Position
from tests.test_auto_tabik import _engine, ME, AN
from tests.test_lock_choices import install


@pytest.mark.parametrize('kind,expected', [('weapon', 'weapon'), ('cultivation_ranged', 'cultivation'), ('', 'unknown')])
def test_resolving_spec_is_immutable_and_does_not_guess_from_range(kind, expected):
    engine, _ = _engine([])
    actor = engine.state.actors[ME]
    spec = {'range_ft': 60, 'parameters': {'attack_kind': kind, 'nested': {'value': [1]}}}
    result = describe(engine, actor, spec, 'test:actual')
    assert result['delivery'] == expected and result['source_id'] == 'test:actual'
    with pytest.raises(TypeError):
        result['parameters']['nested']['value'] = ()
    spec['parameters']['nested']['value'].append(2)
    assert result['parameters']['nested']['value'] == (1,)


def test_native_reaction_retains_delivering_source_identity():
    engine, _ = _engine([])
    result = describe(engine, engine.state.actors[ME], {'source_definition_id': 'test:bow',
        'range_ft': 60, 'parameters': {'attack_kind': 'weapon'}}, 'system:combat.opportunity_attack')
    assert result['source_id'] == 'system:combat.opportunity_attack'
    assert result['delivering_source_id'] == result['weapon_source_id'] == 'test:bow'


def test_actual_typed_effect_overrides_equipped_weapon():
    engine, _ = _engine([])
    spec = {'range_ft': 60, 'typed': {'weapon': {'name': 'Bow'}, 'delivered_by': 'test:bow#shot'},
            'parameters': {'attack_kind': 'weapon'},
            'checkpoint_context': {'effect': {'type': 'attack', 'attack_kind': 'cultivation_ranged'}}}
    result = describe(engine, engine.state.actors[ME], spec, 'test:spell')
    assert result['delivery'] == 'cultivation'
    spec['checkpoint_context']['effect']['on_hit'] = [{'weapon_damage': True}]
    result = describe(engine, engine.state.actors[ME], spec, 'test:spell')
    assert result['delivery'] == 'weapon' and result['weapon_source_id'] == 'test:bow'


@pytest.mark.parametrize('kind,expected', [('weapon', 5), ('cultivation_ranged', 0), ('', 0)])
def test_native_table_opportunity_cover_preview_commit_reload(tmp_path, monkeypatch, kind, expected):
    from combat.gate2_runtime_content import BASIC_MELEE
    from tests.test_lock13_native_opportunity import fight, move, checked, OA
    monkeypatch.setitem(BASIC_MELEE, AN, {**BASIC_MELEE[AN], 'range_ft': 60,
        'parameters': {'attack_kind': kind, 'opportunity_of': 'test:roster-bow'}})
    observed = []
    def cover(engine, attacker, target, ray):
        descriptor = ray['attack']
        if descriptor and descriptor['source_id'] == OA:
            observed.append(descriptor)
            return 5 if descriptor['delivery'] == 'weapon' else None
    install(monkeypatch, 'directional_cover', cover)
    svc, table, mid = fight(tmp_path, owned=False)
    before = svc._load_session(mid).engine.state.model_dump(mode='json')
    table.state(mid)
    assert svc._load_session(mid).engine.state.model_dump(mode='json') == before
    move(svc, table, mid)
    engine = checked(svc, tmp_path, mid)
    rolls = [e for e in engine.events if e.event_type == 'ATTACK_ROLLED' and e.source_definition_id == OA]
    assert len(rolls) == 1 and rolls[0].payload['cover_bonus'] == expected
    assert observed and all(d['parameters']['opportunity_of'] == 'test:roster-bow' for d in observed)


@pytest.mark.parametrize('kind,expected', [('weapon', 5), ('cultivation_ranged', 0), ('', 0)])
def test_prospective_cover_is_pure_and_attack_aware(kind, expected):
    from combat.ext.wall_cover import restricted_wall_cover
    engine, _ = _engine([], foe_at=(7, 6))
    a, t = engine.state.actors[ME], engine.state.actors[AN]
    engine._cover_ranged_weapon = {(6, 6)}
    spec = {'range_ft': 60, 'parameters': {'attack_kind': kind}}
    attack = describe(engine, a, spec, 'test:threat')
    before = engine.state.model_dump(mode='json')
    assert tactical_cover(engine, a, t, Position(x=8, y=6), [attack]) == expected
    assert engine.state.model_dump(mode='json') == before
    assert restricted_wall_cover(engine, a, t, {'ranged': True, 'attack': None}) is None


def test_prospective_cover_retains_map_baseline_and_mixed_attack_shelter(monkeypatch):
    engine, _ = _engine([], foe_at=(7, 6))
    a, t = engine.state.actors[ME], engine.state.actors[AN]
    engine._cover_ranged_weapon = {(6, 6)}
    monkeypatch.setattr(engine.grid, 'cover_bonus', lambda *args: 2)
    threats = [describe(engine, a, {'range_ft': 60, 'parameters': {'attack_kind': k}}, 'test:'+k)
               for k in ('weapon', 'cultivation_ranged')]
    assert tactical_cover(engine, a, t, Position(x=8, y=6), threats) == 5
    assert tactical_cover(engine, a, t, Position(x=8, y=6), threats[1:]) == 2


@pytest.mark.parametrize('kind,weapon_damage,expected', [
    ('weapon', False, True), ('weapon_melee', False, True), ('weapon_ranged', False, True),
    ('unarmed', False, False), ('cultivation_ranged', False, False), ('cultivation_melee', True, True),
])
@pytest.mark.parametrize('opportunity', [False, True])
def test_cover_and_hit_riders_share_delivery_and_weapon_identity(kind, weapon_damage, expected, opportunity):
    from types import SimpleNamespace
    from combat.ext.weapon_hits import is_weapon_hit, weapon_identity
    from combat.gate2_runtime_models import ActionDefinition, EconomyKind
    engine, _ = _engine([])
    typed = {'weapon': {'name': 'Test weapon'}, 'delivered_by': 'test:weapon#variant'}
    base = ActionDefinition(source_definition_id='test:base', owner_id=ME, display_name='Test attack',
        economy=EconomyKind.ACTION, resolution_kind='TYPED', target_kind='HOSTILE_ENTITY', parameters={'typed': typed})
    engine.action_catalog['test:base'] = base
    if opportunity:
        typed = {'weapon': {'name': 'Test weapon'}, 'opportunity_of': 'test:base'}
        action = base.model_copy(update={'source_definition_id': 'test:opportunity', 'parameters': {'typed': typed}})
    else:
        action = base
    effect = {'type': 'attack', 'attack_kind': kind, 'on_hit': [{'weapon_damage': True}] if weapon_damage else []}
    ctx = SimpleNamespace(engine=engine, typed=typed, action=action)
    attack = describe(engine, engine.state.actors[ME], {'typed': typed, 'parameters': action.parameters,
        'range_ft': 30, 'checkpoint_context': {'effect': effect}}, action.source_definition_id)
    assert is_weapon_hit(ctx, effect) is expected
    assert (attack['delivery'] == 'weapon') is expected
    assert attack['weapon_source_id'] == weapon_identity(ctx) == 'test:weapon'


def _shelter(engine, attacker_id, defender_id):
    """Use the rider's explicit restricted-cell fixture, not a supplied descriptor."""
    attacker, defender = engine.state.actors[attacker_id], engine.state.actors[defender_id]
    # Isolate the real compiled equipment from the compiler's universal
    # improvised-throw option, which would independently grant ranged shelter.
    original_ids = attacker.action_ids
    attacker.action_ids = tuple(s for s in original_ids if '.improvised.' not in s)
    engine._cover_ranged_weapon = {(attacker.position.x, attacker.position.y)}
    try:
        rows = engine._movement_candidates(defender)
    finally:
        attacker.action_ids = original_ids
    return [c.metadata.get('cover_from_nearest_hostile', 0) for c in rows
            if c.destination == Position(x=4, y=5)]


def test_real_melee_only_catalogue_does_not_award_ranged_shelter(tmp_path):
    from tests.test_tabletop_hunt6 import table_fight, LEFT, RIGHT
    kit = {'starting_kit': {'items': [{'item_id': 'tianxia.mortal.weapon.dao', 'quantity': 1}]}}
    service, _, mid = table_fight(tmp_path, [], kit=kit)
    engine = service._load_session(mid).engine
    from combat.attack_provenance import ranged_attacks
    engine.state.actors[LEFT].action_ids = tuple(s for s in engine.state.actors[LEFT].action_ids if '.improvised.' not in s)
    assert not list(ranged_attacks(engine, engine.state.actors[LEFT]))
    assert _shelter(engine, LEFT, RIGHT) == [0]


def test_thrown_weapon_shelter_tracks_table_disarm_and_pickup(tmp_path, monkeypatch):
    from combat import ext
    from combat.attack_provenance import ranged_attacks
    from tests.test_tabletop_hunt6 import table_fight, answer_action, LEFT, RIGHT, HOLD
    from combat.gate5_service import CombatService
    from tests.h1_support import ROOT
    kit = {'starting_kit': {'items': [{'item_id': 'tianxia.mortal.weapon.fu', 'quantity': 1}]}}
    service, table, mid = table_fight(tmp_path, [], kit=kit)
    def loaded():
        return CombatService(ROOT, tmp_path)._load_session(mid)
    e = loaded().engine
    weapon = next(a.source_definition_id for a in e.action_catalog.values() if a.owner_id == LEFT
                  and a.source_definition_id.endswith('.weapon.fu'))
    assert any(a['delivering_source_id'] == weapon+'#thrown' for a in ranged_attacks(e, e.state.actors[LEFT]))
    assert _shelter(e, LEFT, RIGHT) == [5]
    def disarm(engine, kind, kwargs):
        if kind == 'HOLD_POSITION_COMMITTED' and kwargs.get('actor_id') == LEFT:
            actor = engine.state.actors[LEFT]
            engine._apply_condition(actor, 'condition:typed.disarmed', HOLD, LEFT,
                expires_on='UNTIL_REMOVED', data={'disables_action': weapon, 'dropped_at': actor.position.model_dump(mode='json')})
    ext.effects()
    with monkeypatch.context() as fixture:
        fixture.setitem(ext._HOOKS, 'event', [*ext._HOOKS.get('event', []), disarm])
        assert answer_action(table, mid, HOLD)['status'] == 'COMMITTED'
    e = loaded().engine
    assert not any(a['weapon_source_id'] == weapon for a in ranged_attacks(e, e.state.actors[LEFT]))
    assert _shelter(e, LEFT, RIGHT) == [0]
    assert answer_action(table, mid, weapon+'.pickup')['status'] == 'COMMITTED'
    restored = loaded()
    assert _shelter(restored.engine, LEFT, RIGHT) == [5]
    assert restored.verify()['status'] == 'PASS'
