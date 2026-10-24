"""Native portable Water Lash imports and cold replay, without private fixtures."""
import json
import zipfile
from pathlib import Path
import pytest
from combat.gate5_service import CombatService
from combat.tabletop import ButtonStore
from combat.tabletop_service import TabletopService
from tests.h1_support import sheet

APP = Path(__file__).resolve().parents[1]
CUTTING = 'TAL_WATER_CUTTING_CURRENT'
OWNER, FOE = 'actor:factory.aaaaaaaa', 'actor:factory.bbbbbbbb'
# Literal dynamic registry/authority dependencies for the safe exporter.
DEPENDENCIES = ('authority/Tianxia_Typed_Mechanics_Authority_R1.json',
    'authority/typed_mechanics/reviewed_final.d/mgr_t15_cutting_current.json',
    'combat/rules/feature_blocks.d/a2_water.json', 'combat/rules/objects.json')


def settle(send, kind='BLUDGEONING'):
    answers, prompts = [], []
    for _ in range(20):
        result = send(answers)
        if result['status'] == 'COMMITTED': return prompts
        assert result['status'] == 'REACTION_REQUIRED', result
        p = result['reaction']; prompts.append(p)
        use = p['context'].get('reaction_source_id') == 'choice:needle.cutting_current' and kind != 'DECLINE'
        answers.append({**p['context'], 'selection': 'USE' if use else 'DECLINE', 'option_ids': [kind] if use else []})
    raise AssertionError('unresolved native choices')


def end(table, mid):
    s = table.state(mid); m = s['menu']
    settle(lambda a: table.act(mid, m['end_turn'], m['decision_id'], m['state_version'], s['last_sequence'], a))


def turn(table, mid, actor):
    for _ in range(10):
        if table.state(mid)['menu']['actor_id'] == actor: return
        end(table, mid)
    raise AssertionError('turn unavailable')


def native(tmp_path, *, owned=True, material=None, attended=False, magical=False,
           owner_mids=None, foe_mids=None, cl=1, dc=16):
    for path in DEPENDENCIES: assert (APP / path).is_file()
    for pid, name, mids in [('aaaaaaaa', 'Cutting', owner_mids if owner_mids is not None else
                            ([CUTTING] if owned else ['TAL_WATER_WATER_BREATHING'])),
                            ('bbbbbbbb', 'Target', foe_mids if foe_mids is not None else ['TAL_WATER_WATER_BREATHING'])]:
        d = sheet(mids, cl=cl, dc=dc, key='WIS', name=name)
        d['identity'].update(display_name=name, proficiency_bonus=2)
        b = d['spheres_and_talents']
        b['learned_talent_record_ids'] = [i for i in b['learned_talent_record_ids'] if i not in b['automatic_sphere_component_record_ids']]
        folder = tmp_path / 'portable_characters' / pid; folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / 'current.zip', 'w') as z: z.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(d))
        ButtonStore(tmp_path / 'tabletop_buttons').save_reactions(pid, {'mode': 'ask'}, set())
    combat = CombatService(APP, tmp_path)
    arena = {'display_name': 'Cutting Current native', 'width_squares': 10, 'height_squares': 8,
             'starts': {'team1': [[3, 3]], 'team2': [[4, 3]]}}
    if material:
        arena['objects'] = [{'id': 81, 'kind': 'custom', 'name': 'Recorded material', 'material': material,
            'x': 4, 'y': 4, 'ac': 1, 'hp': 100, 'blocks': False, 'unattended': not attended,
            'artifact': magical, 'resist': ['slashing']}]
    saved = combat.tabletop_maps.save(arena)
    mid = combat.create_factory_match(project_ids=['aaaaaaaa'], opponent_actor_ids=[FOE],
        control_modes={OWNER: 'MANUAL', FOE: 'MANUAL'}, arena_id='battlefield:map.' + saved['map_id'],
        match_seed='cutting-current-native')['match_id']
    table = TabletopService(combat, tmp_path); turn(table, mid, OWNER)
    return combat, table, mid


def cold(tmp_path, mid):
    combat = CombatService(APP, tmp_path); session = combat._load_session(mid)
    assert session.verify()['canonical_state_sha256'] == session.mechanical.replay()['canonical_state_sha256']
    return combat, TabletopService(combat, tmp_path), session.engine


def lash(combat, table, mid, target, kind='BLUDGEONING'):
    s = table.state(mid)
    rows = [c for c in combat._load_session(mid).engine.legal_candidates() if c.display_name.startswith('Water Lash') and target in c.target_ids]
    assert rows, target
    c = min(rows, key=lambda c: len(c.display_name))
    return settle(lambda a: table.act(mid, c.candidate_id, c.decision_id, c.state_version, s['last_sequence'], a), kind)


def landed(tmp_path, combat, table, mid, target, kind='BLUDGEONING', wet=False):
    """A real hit after bounded legal misses; native Lash alone prepares Soaked."""
    for _ in range(16):
        combat, table, before = cold(tmp_path, mid)
        actor = before.state.actors.get(target)
        soaked = actor is not None and any(c.condition_id.startswith('condition:typed.mark.soaked.')
                                          for c in actor.conditions.values())
        if wet and not soaked:
            lash(combat, table, mid, target)
            end(table, mid); turn(table, mid, OWNER)
            continue
        assert soaked is wet if actor is not None else not wet
        start = len(before.events)
        prompts = lash(combat, table, mid, target, kind)
        _, _, engine = cold(tmp_path, mid)
        events = engine.events[start:]
        if any(e.event_type == ('DAMAGE_COMMITTED' if actor is not None else 'OBJECT_UPDATED')
               and (actor is not None or 'damage' in e.payload) for e in events):
            return before, engine, events, prompts
        end(table, mid); turn(table, mid, OWNER)
    raise AssertionError('no actual native hit in bounded legal turns')


@pytest.mark.parametrize('kind', ['BLUDGEONING', 'SLASHING'])
@pytest.mark.parametrize('wet', [False, True])
def test_native_dry_and_pre_soaked_damage_and_choice(tmp_path, kind, wet):
    combat, table, mid = native(tmp_path)
    before, engine, events, prompts = landed(tmp_path, combat, table, mid, FOE, kind, wet)
    target = before.state.actors[FOE]
    assert any(c.condition_id.startswith('condition:typed.mark.soaked.') for c in target.conditions.values()) is wet
    attack = next(e for e in events if e.event_type == 'ATTACK_ROLLED')
    assert attack.payload['provisional_hit'], attack.payload
    p = next(p for p in prompts if p['context'].get('reaction_source_id') == 'choice:needle.cutting_current')
    assert {o['id'] for o in p['choice']['options']} == {'BLUDGEONING', 'SLASHING'}
    assert all(word in p['moment'] for word in ('Cutting Current', 'Water Lash', 'Target'))
    if wet:
        shift = next(p for p in prompts if p['context'].get('reaction_source_id') == 'choice:needle.water_lash_shift')
        assert prompts.index(p) < prompts.index(shift)
    damage = next(e for e in events if e.event_type == 'DAMAGE_ROLLED')
    assert damage.payload['expression'].endswith('+' + str(2 + (2 if wet else 0))), damage.payload
    committed = next(e for e in events if e.event_type == 'DAMAGE_COMMITTED')
    assert committed.payload['damage_type'] == kind
    # HP outcome: one packet only, and the target loses exactly that packet. A dry
    # hit must not gain a second Proficiency Bonus packet (main's old passive),
    # which is what a silent "+4 damage" regression would look like.
    packets = [e for e in events if e.event_type == 'DAMAGE_COMMITTED']
    assert len(packets) == 1, [e.payload for e in packets]
    assert packets[0].payload['hp_damage'] == damage.payload['total'], packets[0].payload
    assert target.current_hp - engine.state.actors[FOE].current_hp == packets[0].payload['hp_damage']
    assert engine.state.actors[OWNER].resources == before.state.actors[OWNER].resources


def test_declined_dry_hit_keeps_base_bludgeoning_without_rider(tmp_path):
    # Declining the printed Cutting choice keeps the Water Lash base damage: bludgeoning, no Proficiency Bonus,
    # and no extension failure recorded as a GM rider. The dry hit also loses exactly one damage packet's
    # worth of Hit Points: main's old unconditional passive added a second Proficiency Bonus packet here.
    combat, table, mid = native(tmp_path)
    before, engine, events, prompts = landed(tmp_path, combat, table, mid, FOE, 'DECLINE')
    damage = next(e for e in events if e.event_type == 'DAMAGE_ROLLED')
    assert damage.payload['expression'].endswith('+2'), damage.payload
    committed = next(e for e in events if e.event_type == 'DAMAGE_COMMITTED')
    assert committed.payload['damage_type'] == 'BLUDGEONING'
    packets = [e for e in events if e.event_type == 'DAMAGE_COMMITTED']
    assert len(packets) == 1, [e.payload for e in packets]
    assert packets[0].payload['hp_damage'] == damage.payload['total']
    assert before.state.actors[FOE].current_hp - engine.state.actors[FOE].current_hp == packets[0].payload['hp_damage']
    assert not any(e.event_type == 'GM_RIDER' and 'invalid extension choice' in str(e.payload) for e in events)


def test_nonowner_keeps_bludgeoning(tmp_path):
    combat, table, mid = native(tmp_path, owned=False)
    _, _, events, prompts = landed(tmp_path, combat, table, mid, FOE)
    assert not any(p['context'].get('reaction_source_id') == 'choice:needle.cutting_current' for p in prompts)
    damage = next(e for e in events if e.event_type == 'DAMAGE_ROLLED')
    assert damage.payload['expression'].endswith('+2')


@pytest.mark.parametrize('material,attended,magical,eligible', [
    ('rope', False, False, True), ('cloth', False, False, True), ('paper', False, False, True),
    ('ash', False, False, True), ('salt', False, False, True), ('mud', False, False, True),
    ('clay', False, False, True), ('soft_stone', False, False, True), ('wood', False, False, False),
    ('stone', False, False, False), ('steel', False, False, False), ('rope', True, False, False), ('rope', False, True, False)])
def test_native_objects_and_erosion_adjudication_boundary(tmp_path, material, attended, magical, eligible):
    combat, table, mid = native(tmp_path, material=material, attended=attended, magical=magical)
    combat, table, recorded = cold(tmp_path, mid)
    obj = recorded.state.objects['object:map.81']
    assert obj.component['material'] == material and obj.unattended is not attended
    before, engine, events, _ = landed(tmp_path, combat, table, mid, obj.object_id, 'SLASHING')
    update = next(e for e in events if e.event_type == 'OBJECT_UPDATED' and 'damage' in e.payload)
    assert update.payload['damage']['taken'] > 0
    assert engine.state.objects[obj.object_id].current_hp == 100 - update.payload['damage']['taken']
    # The printed material list applies the Scouring Erosion classification to this
    # damage itself (a durable receipt in the cold-reloaded log), not a GM request.
    applied = [e for e in events if e.event_type == 'PASSIVE_TRIGGERED'
               and (e.payload or {}).get('scouring_erosion') is True]
    assert bool(applied) is eligible, [e.payload for e in events if e.event_type == 'PASSIVE_TRIGGERED']
    if eligible:
        assert applied[0].payload['material'] == material
        assert applied[0].payload['log'] == ('Cutting Current: the Water Lash damage to Recorded material '
                                             'counts as Scouring Erosion.')
        assert tuple(applied[0].target_ids) == (obj.object_id,)
    # Only the glossary's wider benefits (doubled damage, ordinary-Resistance bypass)
    # are left to the GM, and they are never applied automatically.
    riders = [e for e in events if e.event_type == 'GM_RIDER' and 'Scouring Erosion' in str(e.payload)]
    assert bool(riders) is eligible
    if eligible:
        assert 'GM' in riders[0].payload['rider'] and 'doubled' in riders[0].payload['rider']
    rolled = next(e for e in events if e.event_type == 'DAMAGE_ROLLED')
    assert update.payload['damage']['taken'] == rolled.payload['total'] // 2


class FakeWaterProvider:
    """Only consumes the service's creature-permitted AI frame; no sockets."""
    def __init__(self): self.calls = []
    def status(self): return {'ready': True, 'provider_id': 'fixture'}
    def complete_json(self, *, prompt_text, **kwargs):
        frame = json.loads(prompt_text.split('\n\n', 1)[1]); self.calls.append(frame)
        c = min((c for c in frame['legal_candidates']
                 if c['display_name'].startswith('Water Lash') and FOE in c['target_ids']),
                key=lambda c: len(c['display_name']))
        return {'provider_id': 'fixture', 'model': 'deterministic-fixture', 'value': {
            'schema': 'TianxiaFactoryCombatAIIntent.v1', 'action_intent': {
                'decision_id': frame['decision_id'], 'state_version': frame['state_version'],
                'candidate_id': c['candidate_id'], 'actor_id': frame['active_actor_id'],
                'target_ids': c['target_ids'], 'destination': c['destination'], 'option_ids': c['option_ids']}}}


@pytest.mark.parametrize('wet', [False, True])
def test_automatic_native_lash_uses_fake_provider_and_replays(tmp_path, wet):
    combat, table, mid = native(tmp_path)
    fake = FakeWaterProvider()
    for _ in range(8):
        if wet:
            landed(tmp_path, combat, table, mid, FOE)
            end(table, mid); turn(table, mid, OWNER)
        combat = CombatService(APP, tmp_path, ai_provider=fake); table = TabletopService(combat, tmp_path)
        combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='API_AUTO')
        before = len(combat._load_session(mid).engine.events)
        state = table.state(mid)
        result = table.auto_step(mid, state['last_sequence'])
        assert result['status'] == 'COMMITTED', result
        _, _, engine = cold(tmp_path, mid)
        rolled = [e for e in engine.events[before:] if e.event_type == 'DAMAGE_ROLLED']
        if rolled:
            assert fake.calls and all(f['active_actor_id'] == OWNER for f in fake.calls)
            assert rolled[-1].payload['expression'].endswith('+' + str(2 + (2 if wet else 0))), rolled[-1].payload
            return
        combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='MANUAL')
        end(table, mid); turn(table, mid, OWNER)
    raise AssertionError('no automatic native hit in bounded legal turns')
