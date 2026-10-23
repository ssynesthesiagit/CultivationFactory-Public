"""Public-safe source-shaped Water import -> table choice -> cold replay.

Literal dynamic dependencies for the safe exporter (no historical captures):
authority/Tianxia_Typed_Mechanics_Authority_R1.json
authority/typed_mechanics/rules_text.json
catalog/sphere_talent_authority_v1.json
"""
import json
import zipfile
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

import pytest

from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.ext.water_tidal_wave import TIDAL, CURRENT, COURT, bend_corners, wave_cells

ROOT = Path(__file__).resolve().parents[1]
OWNER, FRIEND, FOE = ('actor:factory.tidal-owner', 'actor:factory.tidal-friend', 'actor:factory.tidal-foe')
QI = 'resource:core.qi'
NAME = 'Shape Current: Mist Basin + Tidal Wave'
PUBLIC_TEST_DYNAMIC_DEPENDENCIES = (
    'authority/Tianxia_Typed_Mechanics_Authority_R1.json',
    'authority/typed_mechanics/rules_text.json',
    'catalog/sphere_talent_authority_v1.json',
    'combat/rules/arenas/Pillar_Arena.json',
)


def document(name, talents, *, dc=16, cp=30):
    """A complete initial Water character, not a patched compiled loadout."""
    return {
        'identity': {'name': name, 'cultivation_level': 15, 'proficiency_bonus': 4,
                     'path': 'Qi Cultivation', 'key_ability': 'CON'},
        'ability_scores_and_statistics': {
            'abilities': [{'ability': a, 'score': 14, 'modifier': 2} for a in ('STR','DEX','CON','INT','WIS','CHA')],
            'primary_resource': {'name': 'Qi', 'maximum': cp}, 'armor_class': {'base_value': 14},
            'hit_points': {'maximum': 100}, 'speed': {'walking_ft': 30},
            'technique_save_dc': dc, 'technique_attack_bonus': 8},
        'spheres_and_talents': {'sphere_record_ids': ['tianxia.sphere.water'],
                               'automatic_sphere_component_record_ids': ['WATER_BASE_WATER_LASH', CURRENT],
                               'learned_talent_record_ids': talents}}


def fixture(tmp_path, *, dc=30, cp=30, owned=True, court=False, foe=(7,6), friend=(7,7), obstacle=False,
            sight_wall=False, friend_hostile=False, wide=False, clear=False):
    docs = [document('Wren', ([TIDAL] if owned else []) + ([COURT] if court else []), dc=dc, cp=cp),
            document('Tobin', []), document('Mara', [])]
    ids = [OWNER, FRIEND, FOE]
    # Native portable-character producer reads these exact source documents on
    # continuation; no test writes an owned benefit or receipt into fight state.
    for aid, doc in zip(ids, docs):
        folder = tmp_path/'portable_characters'/aid.removeprefix('actor:factory.')
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder/'current.zip', 'w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(doc))
    bundles = [compile_character(doc, actor_id=aid, reaction_plan={'ask': True}) for aid,doc in zip(ids,docs)]
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    arena = combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena']
    if wide or clear:
        arena = deepcopy(arena)
    if wide:
        arena['width_squares'] = 28
    if clear:
        arena['terrain_regions'] = []
    if obstacle:
        arena = deepcopy(arena)
        arena['terrain_regions'] = [{'region_id':'tidal-obstacle', 'terrain_type':'BLOCKED',
                                    'movement_cost':0, 'cells':[{'x':6,'y':6}]}]
        if sight_wall:
            arena['terrain_regions'].append({'region_id':'tidal-screen','terrain_type':'SIGHT_BLOCKED',
                                            'movement_cost':0,'cells':[{'x':5,'y':y} for y in range(14)]})
    mid = combat._finish_factory_match(bundles, ids, {OWNER:'team:a', FRIEND:'team:b' if friend_hostile else 'team:a', FOE:'team:b'},
        {OWNER:{'x':3,'y':6}, FRIEND:{'x':friend[0],'y':friend[1]}, FOE:{'x':foe[0],'y':foe[1]}},
        arena, [OWNER] if friend_hostile else [OWNER,FRIEND], [FOE,FRIEND] if friend_hostile else [FOE],
        control_modes={aid:'MANUAL' for aid in ids},
        match_seed='MGR-T15-TIDAL', display_name='Tidal Wave native record', maximum_rounds=10)['match_id']
    for _ in range(5):
        if table.state(mid)['menu']['actor_id'] == OWNER:
            break
        settle(table, mid, table.state(mid)['menu']['end_turn'])
    assert table.state(mid)['menu']['actor_id'] == OWNER
    return combat, table, mid


def loaded(tmp_path, mid):
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    assert session.mechanical.replay()['status'] == 'PASS'
    return session.engine


def candidate(combat, mid, name=NAME, at=(7,6)):
    engine = combat._load_session(mid).engine
    rows = [c for c in engine.legal_candidates()
            if engine.action_catalog.get(c.source_definition_id)
            and engine.action_catalog[c.source_definition_id].display_name == name
            and (at is None or c.destination and (c.destination.x,c.destination.y) == at)]
    assert rows, name
    return rows[0]


def settle(table, mid, cid, *, form='line:90', recipients=(FOE,), corner='straight', heading=None):
    answers, prompts = [], []
    for _ in range(24):
        menu = table.state(mid)['menu']
        result = table.act(mid, cid, menu['decision_id'], menu['state_version'], 0, answers)
        if result['status'] != 'REACTION_REQUIRED':
            assert result['status'] == 'COMMITTED', result
            return prompts
        p = result['reaction']; prompts.append(p)
        rid = p['context']['reaction_source_id']
        options = (p.get('choice') or {}).get('options') or []
        if rid == 'choice:water.tidal.form':
            assert {'line:5','line:90','cone:30'} <= {o['id'] for o in options}
            pick = [form]
        elif rid == 'choice:water.tidal.corner':
            pick = [corner]
        elif rid == 'choice:water.tidal.heading':
            pick = [heading] if heading else [options[0]['id']]
        elif rid == 'choice:needle.area_recipients':
            assert set(recipients) <= {o['id'] for o in options}
            pick = list(recipients)
        else:
            pick = []
        answers.append({**p['context'], 'selection':'USE' if pick else 'DECLINE', 'option_ids':pick})
        # Resume each paused choice from newly constructed services. The save,
        # cost and geometry must follow the persisted transaction and answers.
        data_root = table.combat.userdata_root
        table = TabletopService(CombatService(ROOT,data_root),data_root)
    raise AssertionError('unsettled native choice')


def soaked(actor):
    return any('mark.soaked' in c.condition_id for c in actor.conditions.values())


def prone(actor):
    return any(c.condition_id == 'condition:typed.prone' for c in actor.conditions.values())


@pytest.mark.parametrize('form', ['line:90','cone:30'])
@pytest.mark.parametrize('dc,failed', [(30,True),(1,False)])
def test_actual_shape_choices_save_branches_payment_and_cold_replay(tmp_path, form, dc, failed):
    # Unobstructed arena: the printed 20-foot push must not stop at Pillar Arena's blocked cells.
    combat, table, mid = fixture(tmp_path, dc=dc, clear=True)
    before = loaded(tmp_path, mid)
    cp = before.state.actors[OWNER].resources[QI]
    pos = before.state.actors[FOE].position
    prompts = settle(table, mid, candidate(combat,mid).candidate_id, form=form)
    after = loaded(tmp_path,mid)
    assert after.state.actors[OWNER].resources[QI] == cp-3
    target = after.state.actors[FOE]
    assert soaked(target) and prone(target) is failed
    assert (target.position != pos) is failed
    if failed:
        # Straight-wave failure uses the printed 20-foot push (four 5-foot squares).
        assert after.state.actors[FOE].position.x - pos.x == 4
        assert after.state.actors[FOE].position.y == pos.y
    assert not soaked(after.state.actors[FRIEND])
    # The actual save branch must deliver half of the same rolled 4d8 packet.
    damage = [e for e in after.events if e.event_type == 'DAMAGE_ROLLED' and e.actor_id == OWNER]
    assert damage
    roll = damage[-1].payload
    assert roll['expression'].startswith('4d8') and len(roll['dice']) == 4
    amount = roll.get('adjusted_total', roll['total'])
    assert 100-target.current_hp == (amount if failed else amount//2)
    zone = next(z for z in after.state.zones.values() if z.active and z.owner_id == OWNER)
    assert zone.trigger_profile['shape'] == form.split(':')[0]
    assert zone.trigger_profile['size_ft'] == int(form.split(':')[1])
    assert zone.trigger_profile['footprint_is_authoritative'] == 1
    assert any(p['context']['reaction_source_id'] == 'choice:water.tidal.form' for p in prompts)


@pytest.mark.parametrize('recipients', [(), (FOE,), (FRIEND,), (FOE,FRIEND)])
def test_no_or_individual_creature_selection(tmp_path, recipients):
    combat, table, mid = fixture(tmp_path)
    settle(table, mid, candidate(combat,mid).candidate_id, recipients=recipients)
    after = loaded(tmp_path,mid)
    assert soaked(after.state.actors[FOE]) is (FOE in recipients)
    assert soaked(after.state.actors[FRIEND]) is (FRIEND in recipients)
    assert after.state.actors[OWNER].resources[QI] == 27


@pytest.mark.parametrize('cp,owned', [(2,True),(30,False)])
def test_insufficient_cp_and_no_owner_do_not_offer_wave(tmp_path, cp, owned):
    combat, table, mid = fixture(tmp_path, cp=cp, owned=owned)
    engine = loaded(tmp_path,mid)
    assert not any('Tidal Wave' in c.display_name for c in engine.legal_candidates())
    assert engine.state.actors[OWNER].resources[QI] == cp


def test_short_line_edges_and_no_outside_court_bend(tmp_path):
    combat, table, mid = fixture(tmp_path)
    prompts = settle(table, mid, candidate(combat,mid).candidate_id, form='line:5', recipients=())
    assert not any(p['context']['reaction_source_id'] == 'choice:water.tidal.corner' for p in prompts)
    engine = loaded(tmp_path,mid)
    assert not soaked(engine.state.actors[FOE])
    origin = engine.state.actors[OWNER].position
    aim = engine.state.actors[FOE].position
    from combat.gate2_runtime_models import Position
    cells = set(wave_cells(engine,origin,aim,'line',15))
    assert Position(x=6,y=6) in cells
    assert Position(x=7,y=6) not in cells
    assert not bend_corners(engine, engine.state.actors[OWNER], aim, 90)


def test_owner_can_decline_modifier_by_using_unmodified_shape_current(tmp_path):
    combat,table,mid = fixture(tmp_path)
    prompts = settle(table,mid,candidate(combat,mid,'Shape Current: Mist Basin').candidate_id,recipients=())
    assert not any(p['context']['reaction_source_id'].startswith('choice:water.tidal.') for p in prompts)
    engine = loaded(tmp_path,mid)
    assert engine.state.actors[OWNER].resources[QI] == 29
    assert not soaked(engine.state.actors[FOE])


@pytest.mark.parametrize('form,x,inside',[('line:90',21,True),('line:90',22,False),
                                         ('cone:30',9,True),('cone:30',10,False)])
def test_native_wave_length_boundary_uses_emission_not_base_aim_range(tmp_path,form,x,inside):
    combat,table,mid = fixture(tmp_path,foe=(x,6),friend=(3,8),wide=True,clear=True)
    settle(table,mid,candidate(combat,mid,at=(7,6)).candidate_id,form=form,recipients=(FOE,) if inside else ())
    engine = loaded(tmp_path,mid)
    assert soaked(engine.state.actors[FOE]) is inside
    from combat.gate2_runtime_models import Position
    zone = next(z for z in engine.state.zones.values() if z.active and z.owner_id == OWNER)
    assert (Position(x=x,y=6) in zone.affected_cells) is inside
    assert engine.state.actors[OWNER].resources[QI] == 27


def test_controlling_record_hash_and_catalog_access():
    texts = json.loads((ROOT/'authority/typed_mechanics/rules_text.json').read_text())
    assert isinstance(texts.get(TIDAL), str) and texts[TIDAL].strip()
    catalog = json.loads((ROOT/'catalog/sphere_talent_authority_v1.json').read_text())
    def rows(value):
        if isinstance(value,dict):
            if value.get('record_id') == TIDAL:
                yield value
            for v in value.values():
                yield from rows(v)
        elif isinstance(value,list):
            for v in value:
                yield from rows(v)
    record = next(r for r in rows(catalog) if 'selectable_talent' in r)
    assert record['selectable_talent'] and record['minimum_cl'] is None


@pytest.mark.parametrize('form', ['line:90','cone:30'])
def test_native_owned_court_corner_cells_and_legal_push_reload(tmp_path, form):
    from combat.ext.water_tidal_wave import inside_owned_court
    combat, table, mid = fixture(tmp_path, court=True, foe=(9,7), friend=(3,8), obstacle=True)
    settle(table,mid,candidate(combat,mid,'Court of the Endless Tide',at=None).candidate_id, recipients=())
    engine = loaded(tmp_path,mid)
    assert inside_owned_court(engine,engine.state.actors[OWNER]), 'Court sibling must produce its real owned native zone'
    from combat.gate2_runtime_models import Position
    origin = engine.state.actors[OWNER].position
    assert not engine.grid.line_of_physical_transmission(origin,Position(x=9,y=7))
    corners = bend_corners(engine,engine.state.actors[OWNER],Position(x=6,y=7),90 if form.startswith('line') else 30)
    assert 'cell:6,7' in corners
    prompts = settle(table,mid,candidate(combat,mid,at=(6,7)).candidate_id,
                     form=form,corner='cell:6,7',heading='cell:7,7')
    engine = loaded(tmp_path,mid)
    assert soaked(engine.state.actors[FOE]) and prone(engine.state.actors[FOE])
    assert engine.state.actors[FOE].position == Position(x=13,y=7)
    assert engine.state.actors[OWNER].resources[QI] == 24
    zone = next(z for z in engine.state.zones.values() if z.active and z.owner_id == OWNER
                and engine.action_catalog[z.source_definition_id].display_name == NAME)
    assert Position(x=9,y=7) in zone.affected_cells
    assert Position(x=6,y=6) not in zone.affected_cells
    assert sum(p['context']['reaction_source_id'] == 'choice:water.tidal.corner' for p in prompts) == 1


def test_unperceived_corner_is_not_offered_inside_real_court(tmp_path):
    combat, table, mid = fixture(tmp_path,court=True,obstacle=True,sight_wall=True)
    settle(table,mid,candidate(combat,mid,'Court of the Endless Tide',at=None).candidate_id,recipients=())
    engine = loaded(tmp_path,mid)
    from combat.gate2_runtime_models import Position
    from combat.ext.water_tidal_wave import inside_owned_court
    assert inside_owned_court(engine,engine.state.actors[OWNER])
    assert not bend_corners(engine,engine.state.actors[OWNER],Position(x=4,y=6),90)
    prompts = settle(table,mid,candidate(combat,mid,at=(4,6)).candidate_id,recipients=())
    assert not any(p['context']['reaction_source_id'] == 'choice:water.tidal.corner' for p in prompts)
    assert loaded(tmp_path,mid).state.actors[OWNER].resources[QI] == 24


@pytest.mark.parametrize('cone_preferred',[False,True])
def test_automatic_seat_chooses_either_form_without_model_transport(tmp_path,cone_preferred):
    combat,table,mid = fixture(tmp_path,foe=(7,8) if cone_preferred else (7,6),
                              friend=(7,6) if cone_preferred else (3,8),friend_hostile=cone_preferred)
    combat.set_controller_mode(mid,actor_id=OWNER,controller_mode='LOCAL_AUTO')
    prompts = []
    for _ in range(8):
        state = table.state(mid)
        if state['menu']['actor_id'] != OWNER:
            break
        result = table.auto_step(mid, 0)
        if result['status'] == 'REACTION_REQUIRED':
            prompts.append(result['reaction'])
            continue
        assert result['status'] in ('COMMITTED', 'MODEL_DECIDING'), result
    assert not any(p['context']['reaction_source_id'].startswith('choice:water.tidal.') for p in prompts)
    engine = loaded(tmp_path,mid)
    zone = next(z for z in engine.state.zones.values() if z.active and z.owner_id == OWNER)
    # Ties on hit count go to the longer line, so a line that covers both hostiles is a legal, equally
    # good automatic choice. Require only that the automatic seat picks a legal form and catches the hostiles.
    shape = zone.trigger_profile['shape']
    assert shape in ('line', 'cone')
    if not cone_preferred:
        assert shape == 'line'
    assert soaked(engine.state.actors[FOE])
    if cone_preferred:
        assert soaked(engine.state.actors[FRIEND])


def test_bent_push_hook_is_inert_for_base_and_other_modifier_packets(tmp_path):
    """Supplemental isolation guard; positive delivery uses the native table cases above."""
    from combat.typed_executor import Context
    from combat.ext.water_tidal_wave import push_direction
    combat,table,mid = fixture(tmp_path)
    engine = loaded(tmp_path,mid)
    action = next(a for a in engine.action_catalog.values() if a.owner_id == OWNER and a.display_name == NAME)
    typed = deepcopy(action.parameters['typed'])
    typed['_tidal_corner'] = [6,7,0]
    typed['_tidal_heading'] = [1,0]
    ctx = Context(engine,engine.state.actors[OWNER],action,None,typed,
                  [engine.state.actors[FOE]],engine.state.actors[FOE])
    assert push_direction(ctx,ctx.target,10) is None
    assert push_direction(ctx.with_source('passive:'+COURT),ctx.target,10) is None


def test_zero_minimum_question_accepts_decline_as_empty_selection():
    """A zero-minimum native question may be declined; the plug-in spec must allow that DECLINE."""
    from combat.ext.needle import option_spec
    from combat.choice_checkpoints import validate
    from combat.gate4_models import ExtensionChoice
    context = {'needle_options': ['actor:a', 'actor:b'], 'minimum': 0, 'maximum': 2, 'allow_decline': False}
    spec = option_spec('choice:needle.area_recipients', context)
    assert spec['allow_decline'] is True
    class Decision:
        selection = 'DECLINE'
        option_ids = []
        spend = None
    validate(Decision(), ExtensionChoice.model_validate(spec))
