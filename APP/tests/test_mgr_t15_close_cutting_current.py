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
RIVER = 'TAL_WATER_RIVER_CUTS_THE_GATE'
OWNER, FOE = 'actor:factory.aaaaaaaa', 'actor:factory.bbbbbbbb'
# Literal dynamic registry/authority dependencies for the safe exporter.
DEPENDENCIES = ('authority/Tianxia_Typed_Mechanics_Authority_R1.json',
    'authority/typed_mechanics/reviewed_final.d/mgr_t15_cutting_current.json',
    'combat/rules/feature_blocks.d/a2_water.json', 'combat/rules/objects.json')


def settle(send, kind='BLUDGEONING', scour=True):
    answers, prompts = [], []
    for _ in range(20):
        result = send(answers)
        if result['status'] == 'COMMITTED': return prompts
        assert result['status'] == 'REACTION_REQUIRED', result
        p = result['reaction']; prompts.append(p)
        source = p['context'].get('reaction_source_id')
        if source == 'choice:needle.scouring_erosion':
            # The owner pays 1 CP to apply Scouring Erosion, or declines and keeps the ordinary damage.
            use = scour
            answers.append({**p['context'], 'selection': 'USE' if use else 'DECLINE', 'option_ids': ['APPLY'] if use else []})
            continue
        use = source == 'choice:needle.cutting_current' and kind != 'DECLINE'
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


def lash(combat, table, mid, target, kind='BLUDGEONING', scour=True, river_variant=False):
    s = table.state(mid)
    rows = [c for c in combat._load_session(mid).engine.legal_candidates() if c.display_name.startswith('Water Lash') and target in c.target_ids]
    assert rows, target
    c = (max if river_variant else min)(rows, key=lambda c: len(c.display_name))
    return settle(lambda a: table.act(mid, c.candidate_id, c.decision_id, c.state_version, s['last_sequence'], a), kind, scour)


def landed(tmp_path, combat, table, mid, target, kind='BLUDGEONING', wet=False, scour=True):
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
        prompts = lash(combat, table, mid, target, kind, scour)
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
def test_native_objects_and_scouring_erosion_effects(tmp_path, material, attended, magical, eligible):
    combat, table, mid = native(tmp_path, material=material, attended=attended, magical=magical, owner_mids=[CUTTING, RIVER])
    combat, table, recorded = cold(tmp_path, mid)
    obj = recorded.state.objects['object:map.81']
    assert obj.component['material'] == material and obj.unattended is not attended
    before, engine, events, prompts = landed(tmp_path, combat, table, mid, obj.object_id, 'SLASHING')
    # Scouring Erosion is a choice that costs 1 CP (River Cuts the Gate). Only the eligible, applied hit pays it.
    paid = before.state.actors[OWNER].resources['resource:core.qi'] - engine.state.actors[OWNER].resources['resource:core.qi']
    assert paid == (1 if eligible else 0), paid
    asked = any(p['context'].get('reaction_source_id') == 'choice:needle.scouring_erosion' for p in prompts)
    assert asked is eligible
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
    # Scouring Erosion's printed effects follow the classification: the damage ignores
    # the object's ordinary Resistance to slashing and is doubled against the mundane
    # object. Nothing is left for the GM to agree, so no rider is asked.
    assert not [e for e in events if e.event_type == 'GM_RIDER' and 'Scouring Erosion' in str(e.payload)]
    rolled = next(e for e in events if e.event_type == 'DAMAGE_ROLLED')
    if eligible:
        assert update.payload['damage']['taken'] == rolled.payload['total'] * 2
    else:
        # An ordinary hit: the object's own Resistance to slashing still halves it.
        assert update.payload['damage']['taken'] == rolled.payload['total'] // 2


def test_river_variant_payment_is_not_charged_again_on_object_application(tmp_path):
    combat, table, mid = native(tmp_path, material='rope', owner_mids=[CUTTING, RIVER])
    combat, table, recorded = cold(tmp_path, mid)
    obj = recorded.state.objects['object:map.81']
    before, engine, events, prompts = landed(tmp_path, combat, table, mid, obj.object_id, 'SLASHING')
    # Existing River-paid candidate remains legal and its one activation CP covers application.
    # The ordinary source action remains available; this regression specifically exercises the paid variant.
    end(table, mid); turn(table, mid, OWNER)
    s = table.state(mid)
    rows = [c for c in combat._load_session(mid).engine.legal_candidates()
            if c.display_name.startswith('Water Lash') and obj.object_id in c.target_ids]
    assert len(rows) > 1, [c.display_name for c in rows]
    chosen = max(rows, key=lambda c: len(c.display_name))
    prompts = settle(lambda a: table.act(mid, chosen.candidate_id, chosen.decision_id, chosen.state_version,
                                         s['last_sequence'], a), 'SLASHING', True)
    assert not any(p['context'].get('reaction_source_id') == 'choice:needle.scouring_erosion' for p in prompts)
    _, _, after = cold(tmp_path, mid)
    assert before.state.actors[OWNER].resources['resource:core.qi'] - after.state.actors[OWNER].resources['resource:core.qi'] == 1


def test_declined_scouring_erosion_keeps_ordinary_damage_and_spends_no_cp(tmp_path):
    # A printed "you may spend 1 CP" is the owner's choice: declining pays nothing, and the mundane object's
    # ordinary Resistance to slashing still halves the damage (no bypass, no double damage).
    combat, table, mid = native(tmp_path, material='rope', owner_mids=[CUTTING, RIVER])
    combat, table, recorded = cold(tmp_path, mid)
    obj = recorded.state.objects['object:map.81']
    before, engine, events, prompts = landed(tmp_path, combat, table, mid, obj.object_id, 'SLASHING', scour=False)
    assert any(p['context'].get('reaction_source_id') == 'choice:needle.scouring_erosion' for p in prompts)
    assert before.state.actors[OWNER].resources['resource:core.qi'] == engine.state.actors[OWNER].resources['resource:core.qi']
    assert not [e for e in events if e.event_type == 'PASSIVE_TRIGGERED' and (e.payload or {}).get('scouring_erosion')]
    update = next(e for e in events if e.event_type == 'OBJECT_UPDATED' and 'damage' in e.payload)
    rolled = next(e for e in events if e.event_type == 'DAMAGE_ROLLED')
    assert update.payload['damage']['taken'] == rolled.payload['total'] // 2


def test_cutting_without_river_offers_no_scouring_erosion(tmp_path):
    # Review finding (Blocking 1, TAL_WATER_RIVER_CUTS_THE_GATE): the 1 CP Scouring Erosion offer and its 1-minute
    # bypass/double damage belong to River Cuts the Gate. Cutting Current alone offers neither, so the rope's
    # ordinary Resistance to slashing halves the damage and no CP is spent.
    combat, table, mid = native(tmp_path, material='rope')
    combat, table, recorded = cold(tmp_path, mid)
    obj = recorded.state.objects['object:map.81']
    before, engine, events, prompts = landed(tmp_path, combat, table, mid, obj.object_id, 'SLASHING', scour=True)
    assert not any(p['context'].get('reaction_source_id') == 'choice:needle.scouring_erosion' for p in prompts), prompts
    assert before.state.actors[OWNER].resources['resource:core.qi'] == engine.state.actors[OWNER].resources['resource:core.qi']
    assert not [e for e in events if e.event_type == 'PASSIVE_TRIGGERED' and (e.payload or {}).get('scouring_erosion')]
    assert 'scouring_erosion_until' not in (engine.state.objects[obj.object_id].component or {})
    update = next(e for e in events if e.event_type == 'OBJECT_UPDATED' and 'damage' in e.payload)
    rolled = next(e for e in events if e.event_type == 'DAMAGE_ROLLED')
    assert update.payload['damage']['taken'] == rolled.payload['total'] // 2


def test_owner_without_cutting_gets_no_cutting_or_scouring_prompt(tmp_path):
    # Review finding (Blocking 2): an owner holding only Water Breathing gets no Cutting Current choice on a Water
    # Lash, and therefore no Scouring Erosion offer, even on a material object in the same arena.
    combat, table, mid = native(tmp_path, owned=False, material='rope')
    _, engine, events, prompts = landed(tmp_path, combat, table, mid, FOE, 'SLASHING', scour=True)
    sources = {p['context'].get('reaction_source_id') for p in prompts}
    assert 'choice:needle.cutting_current' not in sources and 'choice:needle.scouring_erosion' not in sources, sources
    damage = next(e for e in events if e.event_type == 'DAMAGE_ROLLED')
    committed = [e for e in events if e.event_type == 'DAMAGE_COMMITTED']
    assert [e.payload['damage_type'] for e in committed] == ['BLUDGEONING'], [e.payload for e in committed]
    assert damage.payload['expression'].endswith('+2'), damage.payload


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


def test_river_cuts_the_gate_minute_carries_to_the_next_lash_hit(tmp_path):
    # Review finding (F8, TAL_WATER_RIVER_CUTS_THE_GATE): the paid Scouring Erosion hit must not be the only hit that
    # gets the printed 1-minute benefit. A second Water Lash on the same rope, a few rounds later and after a table
    # commit and cold reload, ignores the object's Resistance to slashing and deals double damage without a new CP.
    from combat.ext import effect_durations
    combat, table, mid = native(tmp_path, material='rope', owner_mids=[CUTTING, RIVER])
    combat, table, recorded = cold(tmp_path, mid)
    obj = recorded.state.objects['object:map.81']
    _, engine, _, first_prompts = landed(tmp_path, combat, table, mid, obj.object_id, 'SLASHING', scour=True)
    assert any(p['context'].get('reaction_source_id') == 'choice:needle.scouring_erosion' for p in first_prompts)
    until = engine.state.objects[obj.object_id].component.get('scouring_erosion_until')
    assert until and not effect_durations.due(engine, until)
    end(table, mid); turn(table, mid, OWNER)  # the next round's turn: a fresh Water Lash
    combat, table, _ = cold(tmp_path, mid)
    before, engine, events, prompts = landed(tmp_path, combat, table, mid, obj.object_id, 'SLASHING', scour=False)
    assert not any(p['context'].get('reaction_source_id') == 'choice:needle.scouring_erosion' for p in prompts)
    paid = before.state.actors[OWNER].resources['resource:core.qi'] - engine.state.actors[OWNER].resources['resource:core.qi']
    assert paid == 0, paid
    assert not [e for e in events if e.event_type == 'PASSIVE_TRIGGERED' and (e.payload or {}).get('scouring_erosion')]
    rolled = next(e for e in events if e.event_type == 'DAMAGE_ROLLED')
    update = next(e for e in events if e.event_type == 'OBJECT_UPDATED' and 'damage' in e.payload)
    assert update.payload['damage']['taken'] == rolled.payload['total'] * 2, update.payload
    # The minute is ten rounds: once the round clock reaches it, the bypass and double damage end.
    engine.state.round_number += 10  # the printed minute, as ten rounds
    from combat.ext.water_second_pass import active_erosion
    assert active_erosion(engine, engine.state.objects[obj.object_id]) is None
