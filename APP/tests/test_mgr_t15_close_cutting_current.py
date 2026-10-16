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
OWNER, FOE = 'actor:factory.cutting', 'actor:factory.target'
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
        use = p['context'].get('reaction_source_id') == 'choice:needle.cutting_current'
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


def native(tmp_path, *, owned=True, material=None, attended=False, magical=False):
    for path in DEPENDENCIES: assert (APP / path).is_file()
    for pid, mids in [('cutting', [CUTTING] if owned else ['TAL_WATER_WATER_WHIP']), ('target', ['TAL_WATER_WATER_WHIP'])]:
        d = sheet(mids, cl=1, name=pid.title())
        d['identity'].update(display_name=pid.title(), proficiency_bonus=2)
        b = d['spheres_and_talents']
        b['learned_talent_record_ids'] = [i for i in b['learned_talent_record_ids'] if i not in b['automatic_sphere_component_record_ids']]
        folder = tmp_path / 'portable_characters' / pid; folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / 'current.zip', 'w') as z: z.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(d))
        ButtonStore(tmp_path / 'tabletop_buttons').save_reactions(pid, {'mode': 'ask'}, set())
    combat = CombatService(APP, tmp_path)
    arena = {'display_name': 'Cutting Current native', 'width_squares': 10, 'height_squares': 8,
             'starts': {'team1': [[3, 3]], 'team2': [[4, 3]]}}
    if material:
        arena['map_objects'] = [{'id': 81, 'kind': 'custom', 'name': 'Recorded material', 'material': material,
            'x': 4, 'y': 4, 'ac': 1, 'hp': 100, 'blocks': False, 'unattended': not attended,
            'artifact': magical, 'resist': ['slashing']}]
    saved = combat.tabletop_maps.save(arena)
    mid = combat.create_factory_match(project_ids=['cutting'], opponent_actor_ids=[FOE],
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


@pytest.mark.parametrize('kind', ['BLUDGEONING', 'SLASHING'])
@pytest.mark.parametrize('wet', [False, True])
def test_native_dry_and_pre_soaked_damage_and_choice(tmp_path, kind, wet):
    combat, table, mid = native(tmp_path)
    if wet:
        lash(combat, table, mid, FOE); end(table, mid); turn(table, mid, OWNER)
    combat, table, before = cold(tmp_path, mid)
    target = before.state.actors[FOE]
    assert any(c.condition_id.startswith('condition:typed.mark.soaked.') for c in target.conditions.values()) is wet
    start = len(before.events); prompts = lash(combat, table, mid, FOE, kind)
    _, _, engine = cold(tmp_path, mid); events = engine.events[start:]
    attack = next(e for e in events if e.event_type == 'ATTACK_ROLLED'); assert attack.payload['hit'], attack.payload
    p = next(p for p in prompts if p['context'].get('reaction_source_id') == 'choice:needle.cutting_current')
    assert {o['id'] for o in p['choice']['options']} == {'BLUDGEONING', 'SLASHING'}
    assert all(word in p['moment'] for word in ('Cutting Current', 'Water Lash', 'Target'))
    damage = next(e for e in events if e.event_type == 'DAMAGE_ROLLED')
    assert damage.payload['expression'].endswith('+' + str(2 + (2 if wet else 0))), damage.payload
    committed = next(e for e in events if e.event_type == 'DAMAGE_COMMITTED')
    assert committed.payload['damage_type'] == kind
    assert engine.state.actors[FOE].current_hp < target.current_hp
    assert engine.state.actors[OWNER].resources == before.state.actors[OWNER].resources


def test_nonowner_keeps_bludgeoning(tmp_path):
    combat, table, mid = native(tmp_path, owned=False)
    prompts = lash(combat, table, mid, FOE); _, _, engine = cold(tmp_path, mid)
    assert not any(p['context'].get('reaction_source_id') == 'choice:needle.cutting_current' for p in prompts)
    damage = next(e for e in engine.events if e.event_type == 'DAMAGE_ROLLED')
    assert damage.payload['expression'].endswith('+2')


@pytest.mark.parametrize('material,attended,magical,eligible', [
    ('rope', False, False, True), ('cloth', False, False, True), ('paper', False, False, True),
    ('ash', False, False, True), ('salt', False, False, True), ('mud', False, False, True),
    ('clay', False, False, True), ('soft_stone', False, False, True), ('wood', False, False, False),
    ('stone', False, False, False), ('steel', False, False, False), ('rope', True, False, False), ('rope', False, True, False)])
def test_native_objects_and_erosion_adjudication_boundary(tmp_path, material, attended, magical, eligible):
    combat, table, mid = native(tmp_path, material=material, attended=attended, magical=magical)
    combat, table, before = cold(tmp_path, mid); obj = before.state.objects['object:map.81']
    assert obj.component['material'] == material and obj.unattended is not attended
    start = len(before.events); lash(combat, table, mid, obj.object_id, 'SLASHING')
    _, _, engine = cold(tmp_path, mid); events = engine.events[start:]
    update = next(e for e in events if e.event_type == 'OBJECT_UPDATED' and 'damage' in e.payload)
    assert update.payload['damage']['taken'] > 0
    assert engine.state.objects[obj.object_id].current_hp == 100 - update.payload['damage']['taken']
    assert bool([e for e in events if e.event_type == 'GM_RIDER' and 'Scouring Erosion' in str(e.payload)]) is eligible
    assert not any(e.event_type == 'SCOURING_EROSION_APPLIED' for e in events)
