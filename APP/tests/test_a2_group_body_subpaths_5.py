"""Printed Body Subpaths 5 effects through accepted service/table actions."""
from copy import deepcopy

import pytest

from combat import ext, flight
from combat.canonical import canonical_sha256
from combat.gate2_runtime_models import Position, RuntimeObjectState
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, reload, prompt_turn

BODY = 'tianxia.subpath.body.'
STAR = BODY + 'sun_piercing_bow_body.feature.star_piercing_shot'
PARA = BODY + 'ten_thousand_parasite_vessel.feature.'
GATES = BODY + 'eight_gates_of_the_heaven_defying_body.feature.'
STAMINA = 'resource:core.stamina'
BROOD = 'resource:named.brood'


def seal(bundles):
    for b in bundles:
        b['actor_template']['maximum_hp'] = 500
        b['actor_template']['initiative_bonus'] = 100 if b['actor_id'] == OWNER else -100
        for r in b['actor_template'].get('resources') or []:
            if r['resource_id'] == BROOD:
                r['initial'] = 4
        base = next(a for a in b['action_catalog'] if a['parameters'].get('typed'))
        for name, effects, kind in [
            ('Place obstruction', [{'type': 'test_a2body5_object'}], 'SELF'),
            ('Void probe', [{'type':'damage','flat':10,'damage_types':['void'],'applies_to':'self'}], 'SELF'),
            ('Shell fire', [{'type': 'object_damage', 'flat': 20, 'damage_types': ['fire']}], 'OBJECT'),
            ('Disease probe', [{'type': 'save', 'ability': 'con', 'save_categories': ['disease'],
                'on_fail': [{'type': 'condition', 'condition': 'poisoned', 'applies_to': 'target'}], 'on_success': []}], 'HOSTILE_ENTITY'),
            ('Poison probe', [{'type': 'save', 'ability': 'con',
                'on_fail': [{'type': 'condition', 'condition': 'poisoned', 'applies_to': 'target'}], 'on_success': []}], 'HOSTILE_ENTITY'),
            ('Substitution probe', [{'type': 'save', 'ability': 'dex',
                'on_fail': [{'type': 'damage', 'flat': 60, 'damage_types': ['force'], 'applies_to': 'target'}], 'on_success': []}], 'HOSTILE_ENTITY'),
            ('Nested Substitution probe', [{'type': 'save', 'ability': 'dex', 'on_success': [],
                'on_fail': [{'type': 'save', 'ability': 'con', 'save_categories': ['disease'],
                    'on_fail': [{'type': 'damage', 'flat': 60, 'damage_types': ['force'], 'applies_to': 'target'}],
                    'on_success': []}]}], 'HOSTILE_ENTITY'),
        ]:
            action = deepcopy(base)
            source = 'test:a2body5.' + b['actor_id'] + '.' + name.replace(' ', '_')
            action.update(source_definition_id=source, display_name=name, economy='NONE', target_kind=kind, range_ft=120, costs=[])
            typed = action['parameters']['typed']
            action['parameters'] = {'typed': typed, 'expected_damage': 1}
            typed.update(source=source, effects=effects, riders=[], area=None, zone_spec={}, range_ft=120,
                         duration={'kind': 'instant'}, numbers={'cl': 18, 'pb': 4, 'save_dc': 100})
            typed.pop('weapon', None)
            b['action_catalog'].append(action)
            b['actor_template']['action_ids'].append(source)
        b.pop('bundle_sha256', None)
        b['bundle_sha256'] = canonical_sha256(b)


def obstacle(monkeypatch, hp):
    ext.effects()
    def place(ctx, row):
        ctx.engine._update_object(RuntimeObjectState(object_id='object:a2body5.door', object_kind='DOOR',
            position=Position(x=5, y=6), unattended=True, flammable=False, ac=10,
            current_hp=hp, maximum_hp=hp, damage_immunities=(), damage_threshold=None,
            component={'name': 'Test gate', 'blocks': True, 'structure': True, 'material': 'wood', 'size': 'medium'}),
            ctx.source, ctx.actor.entity_id)
        from combat import zones
        zones.sync_walls(ctx.engine)
    monkeypatch.setitem(ext._EFFECTS, 'test_a2body5_object', place)


@pytest.mark.parametrize('hp', [1, 10000])
def test_star_piercing_shot_destroys_or_stops_at_barrier_once(tmp_path, monkeypatch, hp):
    obstacle(monkeypatch, hp)
    combat, table, mid = fixture(tmp_path, [STAR], cl=18, primary='Stamina', owner_path='Body Refining',
        owner_dc=100, bundle_transform=seal, ally_position={'x':4,'y':6}, foe_position={'x':8,'y':6})
    settle(table, mid, candidate(combat, mid, 'Place obstruction').candidate_id)
    before = reload(tmp_path, mid)
    settle(table, mid, candidate(combat, mid, 'Star-Piercing Shot (at an object)', at=(5,6)).candidate_id)
    final = reload(tmp_path, mid)
    obj = final.state.objects['object:a2body5.door']
    rolled = next(e.payload for e in final.events if e.event_type == 'DAMAGE_ROLLED' and e.source_definition_id.endswith(STAR+'#object'))
    # Exactly one shared roll, with double object damage and unchanged Threshold/Immunity rules.
    updates = [e for e in final.events if e.event_type == 'OBJECT_UPDATED' and e.payload.get('damage') and obj.object_id in e.target_ids]
    assert len(updates) == 1
    assert updates[0].payload['damage']['taken'] == 2 * rolled['total']
    assert obj.destroyed == (hp == 1)
    assert (final.state.actors[FOE].current_hp < before.state.actors[FOE].current_hp) == (hp == 1)
    assert final.state.actors[ALLY].current_hp == before.state.actors[ALLY].current_hp
    assert final.state.actors[OWNER].resources[STAMINA] == before.state.actors[OWNER].resources[STAMINA] - 8
    prompt_turn(table, mid, FOE)
    prompt_turn(table, mid, OWNER)
    assert not any('Star-Piercing Shot' in c.display_name for c in reload(tmp_path,mid).legal_candidates())


@pytest.mark.parametrize('automatic', [False, True])
def test_star_line_uses_enemy_recipients_and_shared_roll(tmp_path, automatic):
    combat, table, mid = fixture(tmp_path, [STAR], cl=18, primary='Stamina', owner_path='Body Refining',
        owner_dc=100, bundle_transform=seal, ask=not automatic,
        ally_position={'x':5,'y':6}, foe_position={'x':6,'y':6})
    before = reload(tmp_path, mid)
    chosen = candidate(combat, mid, 'Star-Piercing Shot', at=(6,6)).candidate_id
    if automatic:
        from tests.r1i_service_support import force_ai_candidate
        force_ai_candidate(combat, mid, OWNER, chosen)
    settle(table, mid, chosen, auto=automatic)
    final = reload(tmp_path, mid)
    assert final.state.actors[ALLY].current_hp == before.state.actors[ALLY].current_hp
    assert final.state.actors[OWNER].current_hp == before.state.actors[OWNER].current_hp
    assert final.state.actors[FOE].current_hp < before.state.actors[FOE].current_hp
    saves = [e.actor_id for e in final.events if e.event_type == 'SAVE_ROLLED' and e.source_definition_id.endswith(STAR)]
    assert saves == [FOE]
    rolls = [e for e in final.events if e.event_type == 'DAMAGE_ROLLED' and e.source_definition_id.endswith(STAR)]
    assert len(rolls) == 1


@pytest.mark.parametrize('threshold,immunities,expected', [
    (10_000, (), 0),
    (None, ('PIERCING', 'FORCE'), 0),
])
def test_star_object_delivery_keeps_native_threshold_and_immunity(tmp_path, monkeypatch, threshold, immunities, expected):
    """Ordered delivery still delegates object defense to the native object resolver."""
    ext.effects()
    def place(ctx, row):
        ctx.engine._update_object(RuntimeObjectState(object_id='object:a2body5.defended', object_kind='DOOR',
            position=Position(x=5, y=6), unattended=True, flammable=False, ac=10,
            current_hp=100, maximum_hp=100, damage_immunities=immunities, damage_threshold=threshold,
            component={'name': 'Defended test gate', 'blocks': True, 'structure': True, 'material': 'stone', 'size': 'medium'}),
            ctx.source, ctx.actor.entity_id)
        from combat import zones
        zones.sync_walls(ctx.engine)
    monkeypatch.setitem(ext._EFFECTS, 'test_a2body5_object', place)
    combat, table, mid = fixture(tmp_path, [STAR], cl=18, primary='Stamina', owner_path='Body Refining',
        owner_dc=100, bundle_transform=seal, ally_position={'x':4,'y':6}, foe_position={'x':8,'y':6})
    settle(table, mid, candidate(combat, mid, 'Place obstruction').candidate_id)
    settle(table, mid, candidate(combat, mid, 'Star-Piercing Shot (at an object)', at=(5,6)).candidate_id)
    final = reload(tmp_path, mid)
    updates = [e for e in final.events if e.event_type == 'OBJECT_UPDATED' and e.payload.get('damage')
        and 'object:a2body5.defended' in e.target_ids]
    assert len(updates) == 1
    assert updates[0].payload['damage']['taken'] == expected
    assert final.state.objects['object:a2body5.defended'].current_hp == 100 - expected


@pytest.mark.parametrize('count', [6, 8])
def test_gate_heaven_grants_current_speed_hover_then_falls_when_closed(tmp_path, count):
    features = [GATES+k for k in ('first_and_second_gates', 'third_and_fourth_gates', 'fifth_gate_gate_of_thunder',
        'sixth_and_seventh_gates', 'eighth_gate_heaven_defying_gate')]
    combat, table, mid = fixture(tmp_path, features, cl=18, primary='Stamina', owner_path='Body Refining', bundle_transform=seal)
    before = reload(tmp_path, mid).state.actors[OWNER].resources[STAMINA]
    settle(table, mid, candidate(combat, mid, 'Open the Gates').candidate_id, {'choice:needle.eight_gates': str(count)})
    e = reload(tmp_path, mid)
    actor = e.state.actors[OWNER]
    assert actor.resources[STAMINA] == before-count
    assert flight.profile(e,actor).speed_ft == e._effective_speed(actor) == (80 if count == 8 else 40)
    assert flight.profile(e,actor).hover
    hp=actor.current_hp
    settle(table,mid,candidate(combat,mid,'Void probe').candidate_id)
    e=reload(tmp_path,mid)
    assert e.state.actors[OWNER].current_hp==hp-(5 if count==8 else 10)
    move = next(c for c in e.legal_candidates() if c.kind=='MOVE' and c.destination == Position(x=3,y=6,z=2))
    settle(table, mid, move.candidate_id)
    assert reload(tmp_path,mid).state.actors[OWNER].position.z == 2
    settle(table,mid,table.state(mid)['menu']['end_turn'], choices={})
    prompt_turn(table,mid,OWNER)
    settle(table,mid,candidate(combat,mid,'Close the Gates').candidate_id)
    final = reload(tmp_path,mid)
    assert flight.profile(final,final.state.actors[OWNER]).speed_ft == 0
    assert final.state.actors[OWNER].position.z == 0


def test_worm_body_crosses_creatures_at_double_cost_without_occupied_endpoint(tmp_path):
    combat,table,mid=fixture(tmp_path,[PARA+'ten_thousand_worm_demon_body'],cl=18,primary='Stamina',
        owner_path='Body Refining',bundle_transform=seal,foe_position={'x':15,'y':6})
    settle(table,mid,candidate(combat,mid,'Ten-Thousand Worm Demon Body').candidate_id)
    e=reload(tmp_path,mid)
    assert not any(c.kind=='MOVE' and c.destination==e.state.actors[ALLY].position for c in e.legal_candidates())
    from combat.movement_routes import explicit_candidate
    move=explicit_candidate(e,OWNER,[Position(x=3,y=6),Position(x=4,y=6),Position(x=5,y=6)],'walk')
    menu=table.state(mid)['menu']
    before=e.state.actors[OWNER].movement_remaining_ft
    result=table.act(mid,move.candidate_id,menu['decision_id'],menu['state_version'],0,[],
        movement_path=[{'x':3,'y':6},{'x':4,'y':6},{'x':5,'y':6}],movement_mode='walk',actor_id=OWNER)
    assert result['status']=='COMMITTED',result
    final=reload(tmp_path,mid)
    assert final.state.actors[OWNER].position==Position(x=5,y=6)
    assert final.state.actors[OWNER].movement_remaining_ft==before-15


@pytest.mark.parametrize('disease', [False, True])
def test_internal_brood_advantage_requires_explicit_disease_source(tmp_path,disease):
    combat,table,mid=fixture(tmp_path,[PARA+'internal_brood'],cl=18,primary='Stamina',owner_path='Body Refining',bundle_transform=seal)
    prompt_turn(table,mid,FOE)
    settle(table,mid,candidate(combat,mid,'Disease probe' if disease else 'Poison probe',target=OWNER).candidate_id)
    e=reload(tmp_path,mid)
    save=next(ev for ev in reversed(e.events) if ev.event_type=='SAVE_ROLLED' and ev.actor_id==OWNER)
    assert save.payload['mode']==('ADVANTAGE' if disease else 'NORMAL')


@pytest.mark.parametrize('destroy', [False, True])
def test_brood_shell_damageable_after_packet_and_expires_or_breaks(tmp_path,destroy):
    combat,table,mid=fixture(tmp_path,[PARA+'brood_substitution'],cl=18,primary='Stamina',owner_path='Body Refining',
        bundle_transform=seal,ally_position={'x':4,'y':7},foe_position={'x':6,'y':6})
    prompt_turn(table,mid,FOE)
    starting_position = reload(tmp_path, mid).state.actors[OWNER].position
    settle(table,mid,candidate(combat,mid,'Substitution probe',target=OWNER).candidate_id,
        {'choice:needle.brood_substitution':'use','choice:needle.brood_substitution_move':'cell:1,6'})
    e=reload(tmp_path,mid)
    shell,=[o for o in e.state.objects.values() if o.component.get('name')=='Swarm-Shell' and not o.destroyed]
    assert shell.position==Position(x=3,y=6) and shell.ac==16 and shell.maximum_hp==36
    assert set(shell.damage_immunities)=={'POISON','PSYCHIC'}
    assert shell.component['vulnerable']==['FIRE','RADIANT']
    damage=next(ev.sequence for ev in e.events if ev.event_type=='DAMAGE_COMMITTED' and OWNER in ev.target_ids)
    move=next(ev.sequence for ev in e.events if ev.event_type=='MOVEMENT_COMMITTED' and ev.actor_id==OWNER and ev.source_definition_id.endswith('brood_substitution'))
    assert damage<move
    if destroy:
        settle(table,mid,candidate(combat,mid,'Shell fire',target=shell.object_id).candidate_id)
        e=reload(tmp_path,mid)
        assert e.state.objects[shell.object_id].destroyed
    else:
        prompt_turn(table,mid,OWNER)
        e=reload(tmp_path,mid)
        assert e.state.objects[shell.object_id].destroyed
    assert not any(z.active and z.trigger_profile.get('name')=='Swarm-Shell' for z in e.state.zones.values())


def test_brood_substitution_does_not_relocate_after_lethal_packet(tmp_path):
    def low_hp(bundles):
        seal(bundles)
        for bundle in bundles:
            if bundle['actor_id'] == OWNER:
                bundle['actor_template']['maximum_hp'] = 50
            bundle.pop('bundle_sha256', None)
            bundle['bundle_sha256'] = canonical_sha256(bundle)
    combat,table,mid=fixture(tmp_path,[PARA+'brood_substitution'],cl=18,primary='Stamina',owner_path='Body Refining',
        bundle_transform=low_hp,ally_position={'x':4,'y':7},foe_position={'x':6,'y':6})
    prompt_turn(table,mid,FOE)
    starting_position = reload(tmp_path, mid).state.actors[OWNER].position
    settle(table,mid,candidate(combat,mid,'Substitution probe',target=OWNER).candidate_id,
        {'choice:needle.brood_substitution':'use','choice:needle.brood_substitution_move':'cell:1,6'})
    e=reload(tmp_path,mid)
    assert e.state.actors[OWNER].current_hp == 0
    assert e.state.actors[OWNER].position == starting_position
    assert not any(o.component.get('name')=='Swarm-Shell' and not o.destroyed for o in e.state.objects.values())


def test_brood_substitution_nested_save_damage_consumes_marker_before_reload(tmp_path):
    combat,table,mid=fixture(tmp_path,[PARA+'brood_substitution'],cl=18,primary='Stamina',owner_path='Body Refining',
        bundle_transform=seal,ally_position={'x':4,'y':7},foe_position={'x':6,'y':6})
    prompt_turn(table,mid,FOE)
    settle(table,mid,candidate(combat,mid,'Nested Substitution probe',target=OWNER).candidate_id,
        {'choice:needle.brood_substitution':'use','choice:needle.brood_substitution_move':'cell:1,6'})
    e=reload(tmp_path,mid)
    assert e.state.actors[OWNER].position==Position(x=1,y=6)
    assert any(ev.event_type=='DAMAGE_COMMITTED' and OWNER in ev.target_ids for ev in e.events)
    assert any(o.component.get('name')=='Swarm-Shell' and not o.destroyed for o in e.state.objects.values())
    assert '_round_brood_swap_pending' not in e.state.actors[OWNER].turn_flags


def test_brood_substitution_native_hit_reaction_reduces_then_moves_once(tmp_path):
    """Exercise the separate native-hit Reaction, full reduction, and cold-reloaded cleanup."""
    from tests.worker2_support import sealed_native_attack
    def setup(bundles):
        seal(bundles)
        attacker = next(b for b in bundles if b['actor_id'] == FOE)
        sealed_native_attack(attacker, 'Substitution hit probe', damage_type='FORCE',
            count=1, sides=4, modifier=0, attack_bonus=30, range_ft=60)
    combat, table, mid = fixture(tmp_path, [PARA+'brood_substitution'], cl=18, primary='Stamina',
        owner_path='Body Refining', owner_ac=8, bundle_transform=setup,
        ally_position={'x':4,'y':7}, foe_position={'x':6,'y':6})
    prompt_turn(table, mid, FOE)
    before = reload(tmp_path, mid)
    hp = before.state.actors[OWNER].current_hp
    attack = candidate(combat, mid, 'Substitution hit probe', target=OWNER)
    prompts = settle(table, mid, attack.candidate_id, {
        'reaction:typed.tianxia.subpath.body.ten_thousand_parasite_vessel.feature.brood_substitution': 'use',
        'choice:needle.brood_substitution_move': 'cell:1,6',
    })
    assert any(p['context']['reaction_source_id'] ==
        'reaction:typed.tianxia.subpath.body.ten_thousand_parasite_vessel.feature.brood_substitution' for p in prompts)
    final = reload(tmp_path, mid)
    assert any(e.event_type == 'REACTION_RESOLVED' and e.source_definition_id ==
        'tianxia.subpath.body.ten_thousand_parasite_vessel.feature.brood_substitution'
        and (e.payload or {}).get('checkpoint') == 'ATTACK_HIT_BEFORE_DAMAGE' for e in final.events)
    actor = final.state.actors[OWNER]
    assert actor.current_hp == hp, [(e.event_type, e.source_definition_id, e.payload) for e in final.events[-30:]]
    assert actor.position == Position(x=1, y=6)
    assert actor.resources[BROOD] == before.state.actors[OWNER].resources[BROOD] - 2
    assert '_round_brood_swap_pending' not in actor.turn_flags
    damage = [e for e in final.events if e.event_type == 'DAMAGE_COMMITTED' and OWNER in e.target_ids
        and e.source_definition_id.endswith('substitution_hit_probe')]
    assert damage and all((e.payload or {}).get('damage', {}).get('taken', 0) == 0 for e in damage)
    shells = [o for o in final.state.objects.values() if o.component.get('name') == 'Swarm-Shell' and not o.destroyed]
    assert len(shells) == 1 and shells[0].position == Position(x=3, y=6)
    # A subsequent unrelated packet must not consume a delayed marker or move again.
    position = actor.position
    settle(table, mid, candidate(combat, mid, 'Void probe').candidate_id)
    after = reload(tmp_path, mid)
    assert after.state.actors[OWNER].position == position
    assert '_round_brood_swap_pending' not in after.state.actors[OWNER].turn_flags


@pytest.mark.parametrize('automatic',[False,True])
def test_brood_tide_shares_one_roll_between_enemies_and_spares_ally(tmp_path,automatic):
    from tests import r1i_service_support as support
    from tests.h1_support import sheet
    from combat.factory_compiler import compile_character
    def prepare(bundles):
        stamina=compile_character(sheet([],primary='Stamina'),actor_id='test:pool')['actor_template']['resources']
        for b in bundles:
            if b['actor_id']==support.OWNER:
                b['actor_template']['resources'] += [deepcopy(r) for r in stamina if r['resource_id']==STAMINA]
                b['actor_template']['initiative_bonus']=100
                for r in b['actor_template']['resources']:
                    if r['resource_id']==BROOD:
                        r['initial']=4
            b.pop('bundle_sha256',None)
            b['bundle_sha256']=canonical_sha256(b)
    combat,table,mid,send,commit=support.fixture(tmp_path,[PARA+'ten_thousand_worm_demon_body'],
        owner_dc=100,extra_foe=True,allies=[support.SECOND],wide=True,bundle_transform=prepare,
        positions={support.OWNER:{'x':3,'y':6},support.FOE:{'x':5,'y':6},support.SECOND:{'x':4,'y':6},support.THIRD:{'x':5,'y':7}})
    commit(support.candidate(table,mid,'Ten-Thousand Worm Demon Body'))
    before=reload(tmp_path,mid)
    action=next(c for c in before.legal_candidates() if 'Brood Tide' in c.display_name and c.destination==Position(x=5,y=6))
    if automatic:
        support.force_ai_candidate(combat,mid,support.OWNER,action.candidate_id)
    settle(table,mid,action.candidate_id,auto=automatic)
    final=reload(tmp_path,mid)
    hits=[e for e in final.events if e.event_type=='DAMAGE_COMMITTED' and e.source_definition_id.endswith('ten_thousand_worm_demon_body.brood_tide')]
    assert sorted(t for e in hits for t in e.target_ids)==sorted([support.FOE,support.THIRD])
    assert final.state.actors[support.SECOND].current_hp==before.state.actors[support.SECOND].current_hp
    losses=[before.state.actors[t].current_hp-final.state.actors[t].current_hp for t in [support.FOE,support.THIRD]]
    assert losses[0]==losses[1]>0
    rolls=[e for e in final.events if e.event_type=='DAMAGE_ROLLED' and e.source_definition_id.endswith('ten_thousand_worm_demon_body.brood_tide')]
    assert len(rolls)==1
    assert final.state.actors[support.OWNER].resources[BROOD]==before.state.actors[support.OWNER].resources[BROOD]-3


def test_brood_substitution_nested_success_clears_pending_before_later_damage(tmp_path):
    def successful_inner_save(bundles):
        seal(bundles)
        owner = next(b for b in bundles if b['actor_id'] == OWNER)
        owner['actor_template']['saving_throws']['CON'] = 100
        owner.pop('bundle_sha256', None)
        owner['bundle_sha256'] = canonical_sha256(owner)
    combat, table, mid = fixture(tmp_path, [PARA+'brood_substitution'], cl=18, primary='Stamina',
        owner_path='Body Refining', owner_dc=100, bundle_transform=successful_inner_save,
        ally_position={'x':4,'y':7}, foe_position={'x':6,'y':6})
    prompt_turn(table, mid, FOE)
    start = reload(tmp_path, mid).state.actors[OWNER].position
    settle(table, mid, candidate(combat, mid, 'Nested Substitution probe', target=OWNER).candidate_id,
        {'choice:needle.brood_substitution':'use', 'choice:needle.brood_substitution_move':'cell:1,6'})
    first = reload(tmp_path, mid)
    saves = [e for e in first.events if e.event_type == 'SAVE_ROLLED' and e.actor_id == OWNER]
    assert [e.payload['reason'].rsplit(':', 1)[-1] for e in saves[-2:]] == ['DEX', 'CON']
    assert [e.payload['success'] for e in saves[-2:]] == [False, True]
    assert not any(e.event_type == 'DAMAGE_COMMITTED' and OWNER in e.target_ids for e in first.events)
    assert first.state.actors[OWNER].position == start
    assert '_round_brood_swap_pending' not in first.state.actors[OWNER].turn_flags
    settle(table, mid, candidate(combat, mid, 'Void probe').candidate_id)
    later = reload(tmp_path, mid)
    assert later.state.actors[OWNER].position == start
    assert not any(o.component.get('name') == 'Swarm-Shell' and not o.destroyed for o in later.state.objects.values())


def test_star_line_shares_one_roll_between_mixed_save_enemies_after_reload(tmp_path):
    def mixed_saves(bundles):
        seal(bundles)
        for bundle in bundles:
            if bundle['actor_id'] == FOE:
                bundle['actor_template']['saving_throws']['DEX'] = -100
            elif bundle['actor_id'] == 'actor:factory.worker2-foe1':
                bundle['actor_template']['saving_throws']['DEX'] = 100
            bundle.pop('bundle_sha256', None)
            bundle['bundle_sha256'] = canonical_sha256(bundle)
    combat, table, mid = fixture(tmp_path, [STAR], cl=18, primary='Stamina', owner_path='Body Refining',
        owner_dc=50, bundle_transform=mixed_saves, extra_foes=1,
        positions={OWNER:{'x':3,'y':6}, ALLY:{'x':4,'y':6}, FOE:{'x':5,'y':6}, 'actor:factory.worker2-foe1':{'x':7,'y':6}})
    before = reload(tmp_path, mid)
    shot = candidate(combat, mid, 'Star-Piercing Shot', at=(8,6))
    settle(table, mid, shot.candidate_id, {'choice:needle.piercing_area_type':'PIERCING'})
    final = reload(tmp_path, mid)
    second = 'actor:factory.worker2-foe1'
    saves = [e for e in final.events if e.event_type == 'SAVE_ROLLED' and e.source_definition_id.endswith(STAR)]
    assert {e.actor_id for e in saves} == {FOE, second}
    assert {e.actor_id:(e.payload or {}).get('success') for e in saves} == {FOE:False, second:True}
    rolls = [e for e in final.events if e.event_type == 'DAMAGE_ROLLED' and e.source_definition_id.endswith(STAR)]
    assert len(rolls) == 1
    amount = rolls[0].payload['total']
    losses = {aid:before.state.actors[aid].current_hp-final.state.actors[aid].current_hp for aid in (FOE,second)}
    assert losses == {FOE:amount, second:(amount+1)//2}
    assert final.state.actors[ALLY].current_hp == before.state.actors[ALLY].current_hp


@pytest.mark.parametrize('cover',[2,5])
def test_star_partial_cover_is_removed_from_spatial_dex_save(tmp_path, monkeypatch, cover):
    ext.effects()
    def scoped_cover(engine, target, ability, dc, source_id, intent):
        if ability == 'DEX' and source_id.endswith(STAR):
            return {'bonus':cover,'contributions':{'cover':cover}}
    monkeypatch.setitem(ext._HOOKS, 'save_bonus_details', [*ext._HOOKS.get('save_bonus_details', []), scoped_cover])
    combat, table, mid = fixture(tmp_path, [STAR], cl=18, primary='Stamina', owner_path='Body Refining',
        owner_dc=100, bundle_transform=seal, foe_position={'x':6,'y':6})
    settle(table, mid, candidate(combat, mid, 'Star-Piercing Shot', at=(6,6)).candidate_id,
        {'choice:needle.piercing_area_type':'PIERCING'})
    final = reload(tmp_path, mid)
    save = next(e for e in reversed(final.events) if e.event_type == 'SAVE_ROLLED' and
        e.actor_id == FOE and e.source_definition_id.endswith(STAR))
    assert 'cover' not in (save.payload or {}).get('save_bonus_contributions', {})
    assert save.payload['success'] is False


@pytest.mark.parametrize('case', ['use', 'decline', 'single', 'success', 'unowned'])
def test_star_line_preserves_area_save_guard_service_reload(tmp_path, case):
    """Ordered singleton delivery keeps area provenance; a target save does not.

    Real compiled Equipment ownership and the real Star row run through table
    intents, the service session's execute_intent, cold loading and replay.
    """
    from tests.h1_support import sheet
    guard = 'tianxia.talent.equipment.iron_rain_readiness'

    def prepare(bundles):
        seal(bundles)
        for bundle in bundles:
            if bundle['actor_id'] == FOE:
                bundle['actor_template']['saving_throws']['DEX'] = 100 if case == 'success' else -100
            bundle.pop('bundle_sha256', None)
            bundle['bundle_sha256'] = canonical_sha256(bundle)

    combat, table, mid = fixture(tmp_path, [STAR], cl=18, primary='Stamina',
        owner_path='Body Refining', owner_dc=50, bundle_transform=prepare,
        foe_sheet=sheet([] if case == 'unowned' else [guard], cl=18),
        ally_position={'x':4, 'y':7}, foe_position={'x':6, 'y':6})
    before = reload(tmp_path, mid)
    defender = before.state.actors[FOE]
    assert defender.reaction_available
    assert defender.resources['resource:core.qi'] >= 2
    if case != 'unowned':
        assert any(r.get('kind') == 'iron_rain_area' for r in before.typed_passive_rows[FOE])
    shot = candidate(combat, mid, 'Substitution probe', target=FOE) if case == 'single' else \
        candidate(combat, mid, 'Star-Piercing Shot', at=(6,6))
    prompts = settle(table, mid, shot.candidate_id, {
        'choice:needle.piercing_area_type': 'FORCE',
        'choice:needle.iron_rain_area': None if case == 'decline' else 'use',
    })
    final = reload(tmp_path, mid)
    actor = final.state.actors[FOE]
    guards = [p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.iron_rain_area']
    receipts = [e for e in final.events if e.event_type == 'REACTION_RESOLVED'
        and e.source_definition_id == guard and e.actor_id == FOE]
    assert len(guards) == int(case in {'use', 'decline'})
    assert len(receipts) == int(case == 'use')
    saves = [e for e in final.events if e.event_type == 'SAVE_ROLLED'
        and e.source_definition_id == shot.source_definition_id and e.actor_id == FOE]
    assert len(saves) == 1 and saves[0].payload['success'] == (case == 'success')
    packets = [e for e in final.events if e.event_type == 'DAMAGE_COMMITTED'
        and e.source_definition_id == shot.source_definition_id and FOE in e.target_ids]
    assert len(packets) == 1
    rolls = [e for e in final.events if e.event_type == 'DAMAGE_ROLLED'
        and e.source_definition_id == shot.source_definition_id]
    if case == 'single':
        assert not rolls, 'the control delivers a flat 60-damage packet'
        amount = 60
    else:
        assert len(rolls) == 1
        amount = rolls[0].payload['total']
    if case == 'success':
        amount = (amount + 1) // 2
    reduction = 0
    if case == 'use':
        assert 'Star-Piercing Shot' in str(guards)
        assert 'Reaction' in guards[0]['moment']
        assert '2 Qi' in guards[0]['cost']
        assert guards[0]['context']['reactor_id'] == FOE
        roll, = [r for r in final.rolls if r.reason == f'DAMAGE_REDUCTION:{guard}']
        assert len(roll.dice) == 2 and all(1 <= die <= 8 for die in roll.dice)
        assert roll.modifier == actor.proficiency_bonus
        assert roll.total == sum(roll.dice) + actor.proficiency_bonus
        reduction = min(amount, roll.total)
        assert receipts[0].payload['reduction'] == reduction
    assert packets[0].payload['hp_damage'] == amount - reduction
    assert actor.current_hp == defender.current_hp - (amount - reduction)
    assert actor.resources['resource:core.qi'] == defender.resources['resource:core.qi'] - 2 * int(case == 'use')
    assert actor.reaction_available == (case != 'use')
    assert final.state.actors[ALLY].current_hp == before.state.actors[ALLY].current_hp
