"""Printed Body Subpaths 4 repairs through service/table commit and cold replay."""
from copy import deepcopy
import pytest
from combat.canonical import canonical_sha256
from combat.ext.terrain_repair import CLEAR, options
from combat.ext.weapon_roll_penalty import PENALTY
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, reload, prompt_turn

BODY = 'tianxia.subpath.body.'
IRON = 'tianxia.path.body_refining.feature.iron_fist'
STAMINA = 'resource:core.stamina'
QUAKE = BODY + 'stone_fist.feature.earth_shattering_fist'
ARM = BODY + 'karate.feature.precision_strike'
WALL = BODY + 'iron_shirt.feature.iron_wall'
SHOVEL = {'starting_kit': {'items': [{'item_id': 'tianxia.mortal.gear.shovel'}]}}


def probes(bundles):
    """Sealed setup effects run in real accepted table actions; no live state edits."""
    for bundle in bundles:
        base = next(a for a in bundle['action_catalog'] if a['parameters'].get('typed'))
        for name, effects, kind in [
            ('HP price', [{'type': 'hp_cost', 'amount': 9}], 'SELF'),
            ('End rage', [{'type':'test_end_rage'}], 'SELF'),
            ('Ordinary recoil', [{'type':'damage','applies_to':'self','flat':10,'damage_types':['fire']}], 'SELF'),
            ('Weapon probe', [{'type':'attack','attack_kind':'weapon','count':1}], 'HOSTILE_ENTITY'),
            ('Spell probe', [{'type':'attack','attack_kind':'cultivation','count':1}], 'HOSTILE_ENTITY'),
        ]:
            action = deepcopy(base)
            source = 'test:a2body4.' + bundle['actor_id'] + '.' + name.replace(' ', '_')
            action.update(source_definition_id=source, display_name=name, economy='NONE',
                          target_kind=kind, range_ft=60, costs=[])
            typed = action['parameters']['typed']
            action['parameters']={'typed':typed,'expected_damage':1}
            typed.update(source=source,effects=effects,riders=[],area=None,zone_spec={},range_ft=60,
                         duration={'kind':'instant'},numbers={'cl':18,'pb':4,'attack_bonus':100,'save_dc':100})
            typed.pop('weapon',None)
            if name == 'Weapon probe':
                typed['weapon'] = {'damage':{'count':1,'sides':4,'modifier':0},'damage_types':['bludgeoning']}
            bundle['action_catalog'].append(action)
            bundle['actor_template']['action_ids'].append(source)
        bundle.pop('bundle_sha256',None)
        bundle['bundle_sha256']=canonical_sha256(bundle)


@pytest.mark.parametrize('with_tools', [False, True])
def test_earth_shattering_fist_repair_requires_tools_and_clears_one_cell(tmp_path, with_tools):
    combat, table, mid = fixture(tmp_path, [QUAKE], cl=18, primary='Stamina',owner_path='Body Refining',
        owner_kit=SHOVEL if with_tools else None,owner_dc=100,
        positions={OWNER:{'x':3,'y':6},ALLY:{'x':5,'y':6},FOE:{'x':6,'y':6}})
    before = reload(tmp_path,mid)
    ally_hp = before.state.actors[ALLY].current_hp
    settle(table,mid,candidate(combat,mid,'Earth-Shattering Fist',at=(6,6)).candidate_id)
    engine = reload(tmp_path,mid)
    assert engine.state.actors[ALLY].current_hp == ally_hp  # harmful unscoped cone hits enemies only
    assert engine.state.actors[FOE].current_hp < before.state.actors[FOE].current_hp
    zone, = [z for z in engine.state.zones.values() if z.active and z.source_definition_id.endswith(QUAKE)]
    cells = set(zone.affected_cells)
    assert zone.trigger_profile['profile']['repair_tools']
    prompt_turn(table,mid,OWNER)  # Action spent by cone; advance a full turn
    # prompt_turn is already on OWNER, so end explicitly and return.
    settle(table,mid,table.state(mid)['menu']['end_turn'])
    prompt_turn(table,mid,OWNER)
    engine = reload(tmp_path,mid)
    if not with_tools:
        assert not options(engine,engine.state.actors[OWNER])
        assert not [c for c in engine.legal_candidates() if c.source_definition_id == CLEAR]
        return
    key,entry = next(iter(options(engine,engine.state.actors[OWNER]).items()))
    cell = entry['cell']
    settle(table,mid,candidate(combat,mid,'Clear broken ground').candidate_id,{'choice:needle.repair_terrain':key})
    final = reload(tmp_path,mid)
    assert set(final.state.zones[zone.zone_id].affected_cells) == cells - {cell}
    assert not final.state.actors[OWNER].action_available
    assert not [c for c in final.legal_candidates() if c.source_definition_id == CLEAR]


def test_overlapping_broken_ground_repair_clears_physical_square_across_zones(tmp_path):
    combat, table, mid = fixture(tmp_path, [QUAKE], cl=18, primary='Stamina', owner_path='Body Refining',
        owner_kit=SHOVEL, owner_dc=100, positions={OWNER:{'x':3,'y':6},ALLY:{'x':5,'y':6},FOE:{'x':6,'y':6}})
    settle(table,mid,candidate(combat,mid,'Earth-Shattering Fist',at=(6,6)).candidate_id)
    prompt_turn(table,mid,OWNER)
    settle(table,mid,table.state(mid)['menu']['end_turn'])
    prompt_turn(table,mid,OWNER)
    settle(table,mid,candidate(combat,mid,'Earth-Shattering Fist',at=(6,6)).candidate_id)
    engine=reload(tmp_path,mid)
    zones=[z for z in engine.state.zones.values() if z.active and z.source_definition_id.endswith(QUAKE)]
    assert len(zones)>=2
    overlap=set(zones[0].affected_cells).intersection(*(set(z.affected_cells) for z in zones[1:]))
    assert overlap
    target=next(cell for cell in overlap if engine._distance_actor_to_cell(engine.state.actors[OWNER],cell)<=5)
    key=f'{target.x}|{target.y}|{target.z}'
    assert key in options(engine,engine.state.actors[OWNER])
    # End the caster's spent turn, then return to it for the repair Action.
    settle(table,mid,table.state(mid)['menu']['end_turn'])
    prompt_turn(table,mid,OWNER)
    settle(table,mid,candidate(combat,mid,'Clear broken ground').candidate_id,{'choice:needle.repair_terrain':key})
    final=reload(tmp_path,mid)
    assert all(target not in final.state.zones[z.zone_id].affected_cells for z in zones)
    assert any(cell != target for z in zones for cell in final.state.zones[z.zone_id].affected_cells)


def test_iron_wall_resistance_does_not_reduce_hp_cost(tmp_path):
    combat,table,mid=fixture(tmp_path,[WALL],cl=18,primary='Stamina',owner_path='Body Refining',bundle_transform=probes)
    settle(table,mid,candidate(combat,mid,'Iron Wall').candidate_id)
    before=reload(tmp_path,mid).state.actors[OWNER].current_hp
    settle(table,mid,candidate(combat,mid,'HP price').candidate_id)
    assert reload(tmp_path,mid).state.actors[OWNER].current_hp == before-9
    settle(table,mid,candidate(combat,mid,'Ordinary recoil').candidate_id)
    assert reload(tmp_path,mid).state.actors[OWNER].current_hp == before-14


def test_precision_arm_waits_for_weapon_roll_not_spell_roll(tmp_path, monkeypatch):
    from tests.hunt12_support import hit_dice
    hit_dice(monkeypatch)
    combat,table,mid=fixture(tmp_path,[IRON,ARM],cl=18,primary='Stamina',owner_path='Body Refining',
        owner_dc=100,bundle_transform=probes,foe_position={'x':4,'y':6},ally_position={'x':3,'y':7})
    # Strong deterministic setup attack applies the actual owned paid-hit feature.
    # Precision Strike requires unarmed delivery, so use the compiled Iron Fist.
    engine=combat._load_session(mid).engine
    unarmed=next(a.display_name for a in engine.action_catalog.values() if a.owner_id==OWNER and '.natural.iron_fist' in a.source_definition_id and '#' not in a.source_definition_id)
    settle(table,mid,candidate(combat,mid,unarmed,target=FOE).candidate_id,
        {'choice:needle.path_hit.'+ARM:['Arm']})
    engine=reload(tmp_path,mid)
    assert any(c.condition_id==PENALTY for c in engine.state.actors[FOE].conditions.values())
    prompt_turn(table,mid,FOE)
    settle(table,mid,candidate(combat,mid,'Spell probe',target=OWNER).candidate_id)
    engine=reload(tmp_path,mid)
    assert any(c.condition_id==PENALTY for c in engine.state.actors[FOE].conditions.values())
    settle(table,mid,candidate(combat,mid,'Weapon probe',target=OWNER).candidate_id)
    engine=reload(tmp_path,mid)
    assert not any(c.condition_id==PENALTY for c in engine.state.actors[FOE].conditions.values())
    event=next(e for e in reversed(engine.events) if e.event_type=='ATTACK_ROLLED' and e.actor_id==FOE)
    assert event.payload['mode']=='DISADVANTAGE'


@pytest.mark.parametrize('observer_type', ['infernal','daemonic','humanoid'])
def test_asura_early_end_applies_aftermath_and_direction_only(tmp_path,monkeypatch,observer_type):
    from combat import ext
    from combat.ext.condition_events import drop_condition
    from combat.ext.directional_signals import SIGNAL, READ, readings
    from combat.ext.jigoku import COOLED
    ext.effects()
    def end_rage(ctx,row):
        for held in list(ctx.actor.conditions.values()):
            if held.condition_id=='condition:typed.state.asura_s_rage':
                drop_condition(ctx.engine,ctx.actor,held.instance_id,ctx.source)
    monkeypatch.setitem(ext._EFFECTS,'test_end_rage',end_rage)
    def seal(bundles):
        probes(bundles)
        bundles[-1]['actor_template']['creature_types']=[observer_type]
        bundles[-1].pop('bundle_sha256',None)
        bundles[-1]['bundle_sha256']=canonical_sha256(bundles[-1])
    combat,table,mid=fixture(tmp_path,[BODY+'jigoku.feature.asura_s_rage'],cl=18,primary='Stamina',
        owner_path='Body Refining',bundle_transform=seal)
    settle(table,mid,candidate(combat,mid,"Asura's Rage").candidate_id)
    assert not any(c.condition_id==SIGNAL for c in reload(tmp_path,mid).state.actors[OWNER].conditions.values())
    settle(table,mid,candidate(combat,mid,'End rage').candidate_id)
    engine=reload(tmp_path,mid)
    actor=engine.state.actors[OWNER]
    assert any(c.condition_id==COOLED for c in actor.conditions.values())
    assert any(c.condition_id==SIGNAL for c in actor.conditions.values())
    assert any('exhaustion' in c.condition_id for c in actor.conditions.values())
    assert readings(engine,engine.state.actors[FOE]) == ([] if observer_type=='humanoid' else ['west: same Realm'])
    prompt_turn(table,mid,FOE)
    if observer_type=='humanoid':
        assert not [c for c in reload(tmp_path,mid).legal_candidates() if c.source_definition_id==READ]
    else:
        assert any(c.source_definition_id==READ for c in reload(tmp_path,mid).legal_candidates())
        # The same free read remains available to a player, but never enters
        # the built-in AI's primary-action context.
        from combat.gate4_context import build_decision_context
        session=combat._load_session(mid)
        policy,_=combat.policies.for_actor(FOE)
        ai_context=build_decision_context(session.engine,policy,for_ai=True)
        assert not any(c.source_definition_id==READ for c in ai_context.legal_candidates)
        assert combat.suggest(mid)['intent']['candidate_id'] != next(
            c.candidate_id for c in reload(tmp_path,mid).legal_candidates() if c.source_definition_id==READ)
        settle(table,mid,candidate(combat,mid,'Sense Hell-Signaled directions').candidate_id)
        final=reload(tmp_path,mid)
        notes=[e for e in final.events if e.source_definition_id==READ and e.event_type=='PASSIVE_TRIGGERED']
        assert notes and all(not e.target_ids or e.target_ids==(FOE,) for e in notes)
        assert all(e.payload['log']=='Hell-Signaled presence — west: same Realm.' for e in notes)


def test_demon_roar_cone_harms_enemies_and_leaves_ally_unharmed(tmp_path):
    combat,table,mid=fixture(tmp_path,[BODY+'oni_blood.feature.demon_roar'],cl=18,primary='Stamina',
        owner_path='Body Refining',owner_dc=100,
        positions={OWNER:{'x':3,'y':6},ALLY:{'x':5,'y':6},FOE:{'x':6,'y':6}})
    before=reload(tmp_path,mid)
    settle(table,mid,candidate(combat,mid,'Demon Roar',at=(6,6)).candidate_id)
    engine=reload(tmp_path,mid)
    assert engine.state.actors[ALLY].current_hp==before.state.actors[ALLY].current_hp
    assert engine.state.actors[FOE].current_hp<before.state.actors[FOE].current_hp
    assert not any(c.condition_id.endswith('frightened') for c in engine.state.actors[ALLY].conditions.values())
    assert any(c.condition_id.endswith('frightened') for c in engine.state.actors[FOE].conditions.values())


@pytest.mark.parametrize('name', ['Earth-Shattering Fist', 'Demon Roar'])
def test_automatic_harmful_cone_selects_enemy_side(tmp_path, name):
    from tests.r1i_service_support import force_ai_candidate
    feature=QUAKE if name=='Earth-Shattering Fist' else BODY+'oni_blood.feature.demon_roar'
    combat,table,mid=fixture(tmp_path,[feature],cl=18,primary='Stamina',owner_path='Body Refining',
        owner_dc=100,ask=False,
        positions={OWNER:{'x':3,'y':6},ALLY:{'x':5,'y':6},FOE:{'x':6,'y':6}})
    before=reload(tmp_path,mid)
    chosen=candidate(combat,mid,name,at=(6,6)).candidate_id
    force_ai_candidate(combat,mid,OWNER,chosen)
    settle(table,mid,chosen,auto=True)
    final=reload(tmp_path,mid)
    assert final.state.actors[ALLY].current_hp==before.state.actors[ALLY].current_hp
    assert final.state.actors[FOE].current_hp<before.state.actors[FOE].current_hp
    saves={e.actor_id for e in final.events if e.event_type=='SAVE_ROLLED' and e.source_definition_id.endswith(feature)}
    assert saves=={FOE}
