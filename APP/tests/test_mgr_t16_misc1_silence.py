"""Assigned Forbidden Field contracts through table commits and cold replay."""
import pytest

from combat import speech, typed_executor
from combat.canonical import canonical_sha256
from combat.ext.forbidden_silence import FIELD, caster_admission, sound_path
from tests.worker2_support import (OWNER, ALLY, FOE, candidate, fixture, reload,
                                  sealed_native_attack, settle, turn)

NOTE = 'TAL_SOUND_RESONANT_NOTE'
SOUL = 'TAL_SOUND_SOUL_ECHO_HEARING'


def fight(tmp_path, *, extras=(), center=(3, 6), seed='T16-FIELD', bundle_transform=None):
    def clear(arena):
        arena['terrain_regions'] = []
    combat, table, mid = fixture(tmp_path, [FIELD, *extras], seed=seed,
        bundle_transform=bundle_transform,
        positions={OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 8, 'y': 6},
                   FOE: {'x': 13, 'y': 6}}, battlefield_transform=clear)
    settle(table, mid, candidate(combat, mid, 'Forbidden Silence Field', at=center).candidate_id)
    reload(tmp_path, mid)
    return combat, table, mid


def move(combat, table, mid, actor, at):
    turn(table, mid, actor)
    engine = combat._load_session(mid).engine
    row = next(c for c in engine.legal_candidates() if c.kind == 'MOVE'
               and c.destination and (c.destination.x, c.destination.y, c.destination.z) == (*at, 0))
    settle(table, mid, row.candidate_id)


def hearing(engine, who):
    return typed_executor.cant_hear(engine.state.actors[who])


def thunder(engine, who):
    return [m for m in engine.state.actors[who].modifiers.values()
            if m.target_field == 'damage_resistance' and m.value == 'THUNDER']


def test_deafened_follows_entrant_exit_and_cold_reload(tmp_path):
    combat, table, mid = fight(tmp_path)
    assert not hearing(reload(tmp_path, mid), ALLY)
    move(combat, table, mid, ALLY, (7, 6))
    assert hearing(reload(tmp_path, mid), ALLY)
    move(combat, table, mid, ALLY, (8, 6))
    assert not hearing(reload(tmp_path, mid), ALLY)
    assert hearing(reload(tmp_path, mid), OWNER), 'owner still inside'


def test_thunder_protection_follows_entrant_exit_and_cold_reload(tmp_path):
    combat, table, mid = fight(tmp_path)
    assert not thunder(reload(tmp_path, mid), ALLY)
    move(combat, table, mid, ALLY, (7, 6))
    assert thunder(reload(tmp_path, mid), ALLY)
    move(combat, table, mid, ALLY, (8, 6))
    assert not thunder(reload(tmp_path, mid), ALLY)
    assert thunder(reload(tmp_path, mid), OWNER)


@pytest.mark.parametrize('height,allowed', [(0, False), (5, True)])
def test_structured_sound_crosses_actual_sphere_not_infinite_column(tmp_path, height, allowed):
    # Both endpoints remain outside the field. At height 5 cells the ray passes
    # above the 20-foot sphere rather than crossing it.
    combat, table, mid = fight(tmp_path, center=(8, 6))
    engine = reload(tmp_path, mid)
    a, b = engine.state.actors[OWNER], engine.state.actors[FOE]
    assert not typed_executor.cant_hear(a) and not typed_executor.cant_hear(b)
    if height:
        # Geometry-only query uses copied endpoints; persisted state stays native.
        a = a.model_copy(update={'position': a.position.model_copy(update={'z': height})})
        b = b.model_copy(update={'position': b.position.model_copy(update={'z': height})})
    assert (sound_path(engine, a, b, '') is not False) is allowed
    if not height:
        assert not speech.can_hear_from(engine, a, b)
        assert sound_path(engine, a, b, SOUL) is None, 'explicit soul-sound exception'


def test_caster_sound_requires_explicit_delivery_and_other_creatures_are_inert(tmp_path):
    combat, table, mid = fight(tmp_path, extras=(NOTE, SOUL))
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    turn(table, mid, OWNER)
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[OWNER]
    note = next(a for a in engine.action_catalog.values() if a.owner_id == OWNER
                and (a.parameters.get('typed') or {}).get('source') == NOTE)
    soul = next(a for a in engine.action_catalog.values() if a.owner_id == OWNER
                and (a.parameters.get('typed') or {}).get('source') == SOUL)
    assert caster_admission(engine, actor, None, note) is False
    assert caster_admission(engine, actor, None, soul) is None
    assert caster_admission(engine, engine.state.actors[ALLY], None, note) is None
    assert not any(c.source_definition_id == note.source_definition_id for c in engine.legal_candidates())
    assert any(c.source_definition_id == soul.source_definition_id for c in engine.legal_candidates())


def test_field_end_removes_only_its_continuous_grants(tmp_path):
    combat, table, mid = fight(tmp_path)
    # Ending the field by native expiry is a sequence of real table commits.
    for _ in range(10):
        turn(table, mid, OWNER)
        settle(table, mid, table.state(mid)['menu']['end_turn'])
    turn(table, mid, OWNER)
    engine = reload(tmp_path, mid)
    assert not any(z.active for z in engine.state.zones.values())
    assert not hearing(engine, OWNER)
    assert not thunder(engine, OWNER)


def test_leaving_field_preserves_independent_deafness_and_thunder_resistance(tmp_path):
    def seal(bundles):
        b=bundles[1]; source='action:test.independent_protections'
        b['action_catalog'].append({'source_definition_id':source,'display_name':'Independent protections',
            'owner_id':ALLY,'economy':'BONUS_ACTION','resolution_kind':'TYPED','target_kind':'SELF',
            'costs':[], 'parameters':{'typed':{'source':source,'effects':[
                {'type':'condition','condition':'deafened','applies_to':'self','duration':'until_removed'},
                {'type':'resistance','damage_types':['thunder'],'applies_to':'self','duration':'until_removed'}]}}})
        b['actor_template']['action_ids'].append(source)
        b.pop('bundle_sha256',None); b['bundle_sha256']=canonical_sha256(b)
    combat, table, mid = fight(tmp_path,bundle_transform=seal)
    move(combat,table,mid,ALLY,(7,6))
    settle(table,mid,candidate(combat,mid,'Independent protections').candidate_id)
    move(combat,table,mid,ALLY,(8,6))
    engine=reload(tmp_path,mid)
    assert hearing(engine,ALLY)
    assert thunder(engine,ALLY)
    assert not any(c.condition_id=='condition:typed.zone_effect'
                   for c in engine.state.actors[ALLY].conditions.values())
    assert all(m.source_definition_id=='action:test.independent_protections' for m in thunder(engine,ALLY))


@pytest.mark.parametrize('inside', [True, False])
def test_live_thunder_packet_is_halved_only_inside_the_field(tmp_path, inside):
    def seal(bundles):
        sealed_native_attack(bundles[2], 'Thunder shot', damage_type='THUNDER',
                             count=1, sides=2, modifier=10, attack_bonus=100)
    combat, table, mid = fight(tmp_path, bundle_transform=seal, seed='T16-THUNDER'+str(inside))
    if inside:
        move(combat, table, mid, ALLY, (7,6))
    turn(table,mid,FOE)
    settle(table,mid,candidate(combat,mid,'Thunder shot',target=ALLY).candidate_id)
    engine=reload(tmp_path,mid)
    receipts=[e.payload for e in engine.events if e.event_type=='DAMAGE_COMMITTED'
              and e.target_ids==(ALLY,) and e.payload.get('damage_type')=='THUNDER']
    assert receipts, 'the native Thunder attack must hit to exercise the field'
    packet=receipts[-1]
    assert packet['hp_damage']==packet['rolled_or_pending_damage']//(2 if inside else 1)
