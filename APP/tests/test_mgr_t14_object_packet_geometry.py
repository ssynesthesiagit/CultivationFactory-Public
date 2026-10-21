"""Native map admission -> acquired technique -> table commit -> cold replay.

Object classifications enter through the GM map store, never a fabricated
runtime object or packet receipt. The Stars receipt is the published sphere
component producer used by the existing native Starbolt tests.
"""
import pytest

from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.tabletop import TabletopError, TabletopMapStore
from combat.ext import stars
from tests.h1_support import ROOT
from tests.test_mgr_t14_starbolt_base import native_fight, TYPE_CHOICE
from tests.auto_worker1_support import LEFT, RIGHT, act, resolve, turn


def start(tmp_path, *, attended=False, owns=True, extra_talents=(), cl=15,
          object_hp=100, seed='OBJECT-PACKET'):
    # Produce portable, acquired character sheets using the same public packet
    # producer as the base creature matrix; then admit the real saved map.
    if owns and extra_talents:
        from tests.auto_worker1_support import fight
        from tests.test_mgr_t14_starbolt_base import acquired_starbolt
        def acquire(doc, actor_id):
            learned = list((doc.get('spheres_and_talents') or {}).get('learned_talent_record_ids', []))
            acquired_starbolt(doc, actor_id)
            if actor_id == LEFT:
                doc['spheres_and_talents']['learned_talent_record_ids'] = learned
        combat, _, _ = fight(tmp_path, extra_talents, cl=cl, left_attack_bonus=100, sheet_edit=acquire)
    elif owns:
        combat, _, _ = native_fight(tmp_path, cl=cl)
    else:
        from tests.auto_worker1_support import fight
        combat, _, _ = fight(tmp_path)
    saved = combat.tabletop_maps.save({
        'display_name': 'Object packet yard', 'width_squares': 20, 'height_squares': 18,
        'starts': {'team1': [[3, 6]], 'team2': [[13, 6]]},
        'objects': [{'id': 1, 'kind': 'custom', 'name': 'Sturdy astral target',
                     'x': 5, 'y': 6, 'material': 'glass', 'hp': object_hp,
                     'fragile': False, 'temporary_barrier': True, 'formation_anchor': True,
                     'asset_declaration': {'actor': 'table-owner', 'authority': 'GM',
                         'source_rule': 'Authored scene Formation Anchor', 'visibility': 'gm', 'expiry': 'source_rule'},
                     'world_scale': False, 'unattended': not attended, 'blocks': False,
                     'width_cells': 2, 'length_cells': 1, 'rotation': 270}],
    })
    mid = combat.create_factory_match(
        project_ids=[LEFT.removeprefix('actor:factory.')], opponent_actor_ids=[RIGHT],
        arena_id='battlefield:map.' + saved['map_id'], match_seed=seed,
        control_modes={LEFT: 'MANUAL', RIGHT: 'MANUAL'})['match_id']
    table = TabletopService(combat, tmp_path)
    turn(table, mid, LEFT)
    return combat, table, mid


@pytest.mark.parametrize('attended', [False, True])
def test_starbolt_real_object_hit_damage_choice_mark_reload_and_expiry(tmp_path, attended):
    combat, table, mid = start(tmp_path, attended=attended)
    _, prompts = resolve(lambda answers: act(table, mid, 'Starbolt', answers,
                                            target_id='object:map.1'), {TYPE_CHOICE: ['FORCE']})
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    assert session.verify()['status'] == 'PASS'
    assert session.mechanical.replay()['status'] == 'PASS'
    obj = session.engine.state.objects['object:map.1']
    assert obj.current_hp < 100
    assert stars.bears_mark(obj, LEFT) and not stars.bears_mark(obj, RIGHT)
    assert any(p['context']['reaction_source_id'] == TYPE_CHOICE for p in prompts)
    assert any(p['context']['reaction_source_id'] == TYPE_CHOICE and 'Sturdy astral target' in str(p)
               for p in prompts)
    damage = next(e.payload['damage'] for e in session.engine.events
                  if e.event_type == 'OBJECT_UPDATED' and e.payload.get('damage'))
    assert damage['after_hp'] == obj.current_hp
    assert damage['before_hp'] - damage['after_hp'] == damage['taken']
    assert damage['hp_damage'] == damage['before_hp'] - damage['after_hp']
    assert damage['packets'] == [{'amount': damage['taken'], 'damage_type': 'FORCE'}]
    turn(table, mid, RIGHT)
    turn(table, mid, LEFT)
    assert not stars.bears_mark(CombatService(ROOT, tmp_path)._load_session(mid).engine.state.objects[obj.object_id], LEFT)


def test_automatic_seat_can_commit_starbolt_against_an_attended_real_object(tmp_path):
    from tests.auto_worker1_support import action_sender
    from combat.ext import stars
    combat, table, mid = start(tmp_path, attended=True)
    engine = combat._load_session(mid).engine
    use = next(c for c in engine.legal_candidates()
               if 'Starbolt' in c.display_name and 'object:map.1' in c.target_ids)
    assert not engine.action_catalog[use.source_definition_id].parameters.get('player_only')
    _, prompts = resolve(action_sender(combat, table, mid, 'Starbolt', target_id='object:map.1', ai=True))
    assert not any(p['context']['reactor_id'] == LEFT for p in prompts)
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    obj = session.engine.state.objects['object:map.1']
    assert not obj.unattended and obj.current_hp < obj.maximum_hp
    assert stars.bears_mark(obj, LEFT)
    damage = next(e.payload['damage'] for e in session.engine.events
                  if e.event_type == 'OBJECT_UPDATED' and e.payload.get('damage'))
    assert all(packet['damage_type'] == 'RADIANT' for packet in damage['packets'])
    assert session.verify()['status'] == session.mechanical.replay()['status'] == 'PASS'


@pytest.mark.parametrize('automatic', [False, True])
def test_declared_native_barrier_receives_the_actual_impact_packet(tmp_path, automatic):
    from tests.test_mgr_t14_impact_collision import start as impact_start, shove, OWNER as BRUTE_OWNER
    from combat.ext.fight_ownership import owns_block
    barrier = {'kind': 'custom', 'name': 'Declared temporary barrier', 'x': 5, 'y': 6,
        'size': 'medium', 'material': 'iron', 'hp': 500, 'blocks': True, 'temporary_barrier': True,
        'source_cl': 1, 'asset_declaration': {'actor': 'table-owner', 'authority': 'GM',
            'source_rule': 'Declared scene barrier profile', 'visibility': 'gm', 'expiry': 'source_rule'}}
    combat, table, mid = impact_start(tmp_path, objects=[barrier])
    engine = combat._load_session(mid).engine
    assert owns_block(engine, engine.state.actors[BRUTE_OWNER], 'brute_hammer_owned'), 'Full native Hammer authority is required.'
    _, engine, rolls, _ = shove(tmp_path, combat, table, mid, auto=automatic)
    assert len(rolls) == 1
    obj = engine.state.objects['object:map.1']
    assert obj.component['temporary_barrier'] is True
    assert obj.component['asset_declaration']['object_id'] == 1
    assert obj.maximum_hp - obj.current_hp == rolls[0].total


def test_native_map_classifications_and_geometry_survive_cold_load(tmp_path):
    combat, table, mid = start(tmp_path)
    from combat.object_geometry import target_cells
    from combat.object_rules import has_tag
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    obj = session.engine.state.objects['object:map.1']
    assert not has_tag(obj, 'fragile') and not has_tag(obj, 'world_scale')
    assert has_tag(obj, 'temporary_barrier') and has_tag(obj, 'formation_anchor')
    assert obj.component['asset_declaration']['object_id'] == 1
    shown = table.state(mid)['map']['objects'][0]
    assert 'formation_anchor' not in shown and 'asset_declaration' not in shown
    assert {(c.x, c.y) for c in target_cells(session.engine, obj)} == {(5, 6), (5, 7)}
    assert session.mechanical.replay()['status'] == 'PASS'


def test_explicit_scene_object_profile_roundtrip_and_identity_guard(tmp_path):
    from combat.tabletop import TabletopError
    maps = TabletopMapStore(tmp_path / 'declared-map')
    declaration = {'actor': 'table-owner', 'authority': 'GM',
        'source_rule': 'Explicit scene object source', 'visibility': 'gm', 'expiry': 'source_rule'}
    saved = maps.save({'display_name': 'Declared object yard', 'width_squares': 12, 'height_squares': 12,
        'objects': [{'kind': 'custom', 'x': 3, 'y': 3, 'source_cl': 11,
                     'formation_anchor': True, 'asset_declaration': declaration}]})
    loaded = maps.get(saved['map_id'])
    assert loaded['objects'][0]['source_cl'] == 11
    assert loaded['objects'][0]['asset_declaration'] == {**declaration, 'object_id': 1}
    again = maps.save(loaded)
    assert maps.get(again['map_id'])['objects'] == loaded['objects']
    loaded['objects'][0]['asset_declaration']['object_id'] = 2
    with pytest.raises(TabletopError, match='actual map object identity'):
        maps.save(loaded)


def test_cultivated_scene_profile_requires_explicit_owner_declaration(tmp_path):
    from combat.tabletop import TabletopError
    maps = TabletopMapStore(tmp_path / 'undeclared-map')
    with pytest.raises(TabletopError, match='GM authority'):
        maps.save({'display_name': 'Undeclared object yard', 'width_squares': 12, 'height_squares': 12,
            'objects': [{'kind': 'custom', 'x': 3, 'y': 3, 'formation_anchor': True}]})


def test_acquired_incarnation_preserves_its_starbolt_damage_on_real_objects(tmp_path):
    sovereign = 'tianxia.talent.stars.star_sovereign_incarnation'
    # The production SHA256 die stream naturally rolls 20 after the two
    # initiative draws for this seed. No roller override or hit flag is used.
    combat, table, mid = start(tmp_path, extra_talents=[sovereign], cl=17,
        object_hp=10, seed='OBJECT-PACKET-CRIT-7')
    engine = combat._load_session(mid).engine
    incarnation = next(a.display_name for a in engine.action_catalog.values()
        if a.owner_id == LEFT and a.parameters.get('typed', {}).get('source') == sovereign)
    resolve(lambda answers: act(table, mid, incarnation, answers))
    engine = CombatService(ROOT, tmp_path)._load_session(mid).engine
    assert any(c.condition_id == stars.SOVEREIGN for c in engine.state.actors[LEFT].conditions.values())
    assert engine.state.actors[LEFT].resources['resource:core.qi'] == 85
    resolve(lambda answers: act(table, mid, 'Starbolt', answers, target_id='object:map.1'),
            {TYPE_CHOICE: ['FORCE'], 'choice:needle.starbolt_mark': []})
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    rolls = [r for r in session.engine.rolls if r.reason.startswith('DAMAGE:')]
    attack = next(e for e in session.engine.events if e.event_type == 'ATTACK_ROLLED'
                  and e.payload.get('object_id') == 'object:map.1')
    assert attack.payload['natural_result'] == 20
    assert [r.expression for r in rolls] == ['6d10+2', '6d10+0']
    assert session.engine.state.actors[LEFT].resources['resource:core.qi'] == 85
    assert session.engine.state.objects['object:map.1'].current_hp < 100
    damage = next(e.payload['damage'] for e in session.engine.events
                  if e.event_type == 'OBJECT_UPDATED' and e.payload.get('damage'))
    assert damage['hp_damage'] == damage['before_hp'] - damage['after_hp']
    assert damage['hp_damage'] == 10 < damage['taken']
    assert session.verify()['status'] == 'PASS'
    assert session.mechanical.replay()['status'] == 'PASS'


@pytest.mark.parametrize('bad', [{'fragile': 'true'}, {'formation_anchor': 1},
                                {'width_cells': 2}, {'width_cells': 30, 'length_cells': 1}])
def test_map_rejects_unknown_or_outside_profiles(tmp_path, bad):
    with pytest.raises(TabletopError):
        TabletopMapStore(tmp_path).save({'display_name': 'Invalid profile',
            'width_squares': 20, 'height_squares': 18,
            'objects': [{'kind': 'custom', 'x': 5, 'y': 6, **bad}]})


def test_wrong_owner_gets_no_starbolt_object_action(tmp_path):
    combat, table, mid = start(tmp_path, owns=False)
    engine = combat._load_session(mid).engine
    assert not any('Starbolt' in engine.action_catalog[c.source_definition_id].display_name
                   for c in engine.legal_candidates() if c.source_definition_id in engine.action_catalog)


def glass_surface_fight(tmp_path, *, hidden=False, extra_foes=0, owner_pb=None, visit_foe=True):
    from tests.worker2_support import OWNER, FOE, ALLY, fixture, candidate, settle, turn as visit, reload
    from combat.ext.glass_pane import panes_of
    from tests.mgr_t14_acquisition_support import acquire_owner
    # The pane is created by the acquired printed technique. A saved-map solid
    # surface supplies its real anchor; no pane, owner or attack flag is injected.
    maps = TabletopMapStore(tmp_path / 'surface-maps')
    saved = maps.save({'display_name': 'Glass anchor yard', 'width_squares': 20, 'height_squares': 18,
        'objects': [{'kind': 'custom', 'x': 5, 'y': 5, 'blocks': True, 'material': 'stone'}]})
    from combat.tabletop import to_battlefield
    battlefield = to_battlefield(saved)
    def ordered_initiative(bundles):
        from tests.cw2_service_support import seal
        order = [OWNER, FOE, FOE + '1', FOE + '2', ALLY]
        for bundle in bundles:
            bundle['actor_template']['initiative_bonus'] = 100 - 20 * order.index(bundle['actor_id'])
            seal(bundle)
    combat, table, mid = fixture(tmp_path, ['GLASS_BASE_FAULTLINE_MARKS', 'TAL_GLASS_RAISED_PANE_SCRIPTURE'],
        battlefield=battlefield, named=True, foe_position={'x': 6, 'y': 6},
        extra_foes=extra_foes, owner_pb=owner_pb,
        sheet_edit=acquire_owner('tianxia.sphere.glass', OWNER),
        bundle_transform=ordered_initiative if extra_foes else None,
        foe_kit={'starting_kit': {'items': [{'item_id': 'tianxia.mortal.weapon.dao', 'quantity': 1}]}})
    settle(table, mid, candidate(combat, mid, 'Raised Pane Scripture', at=(5, 6)).candidate_id)
    panes = panes_of(reload(tmp_path, mid), OWNER)
    assert panes
    if hidden:
        state = table.state(mid)
        move = next(o for o in state['menu']['moves'] if o.get('destination') == {'x': 3, 'y': 3})
        settle(table, mid, move['candidate_id'])
        from combat.senses import perceives
        engine = reload(tmp_path, mid)
        assert not perceives(engine, engine.state.actors[OWNER], engine.state.actors[FOE])
    if visit_foe:
        visit(table, mid, FOE)
    return combat, table, mid, panes[0].object_id


@pytest.mark.parametrize('accept', [False, True])
def test_actual_created_glass_surface_attack_offers_its_owner_mark(tmp_path, accept):
    from tests.worker2_support import OWNER, FOE, settle, reload
    from combat.ext.glass_refraction import marked
    combat, table, mid, pane_id = glass_surface_fight(tmp_path)
    engine = reload(tmp_path, mid)
    options = [c for c in engine.legal_candidates() if pane_id in c.target_ids]
    assert options
    prompts = settle(table, mid, options[0].candidate_id,
                     {'choice:needle.glass_surface_mark': 'mark' if accept else None})
    assert any(p['context']['reactor_id'] == OWNER and
               p['context']['reaction_source_id'] == 'choice:needle.glass_surface_mark' for p in prompts)
    assert marked(reload(tmp_path, mid).state.actors[FOE], OWNER) == accept
    if accept:
        from combat.typed_executor import mark_condition_id
        condition = next(c for c in reload(tmp_path, mid).state.actors[FOE].conditions.values()
                         if c.condition_id == mark_condition_id('Faultline Mark', OWNER))
        assert condition.source_actor_id == OWNER
        assert condition.source_definition_id == 'GLASS_BASE_FAULTLINE_MARKS'


@pytest.mark.parametrize('accept', [False, True])
def test_native_attack_on_tempered_body_keeps_mark_optional(tmp_path, accept):
    from tests.worker2_support import OWNER, FOE, candidate, settle, reload, turn as visit
    from combat.ext.glass_refraction import marked
    combat, table, mid, _ = glass_surface_fight(tmp_path, visit_foe=False)
    settle(table, mid, candidate(combat, mid, 'Temper Glass Surface').candidate_id)
    state = table.state(mid)
    move = next(o for o in state['menu']['moves'] if o.get('destination') == {'x': 6, 'y': 7})
    settle(table, mid, move['candidate_id'])
    visit(table, mid, FOE)
    engine = reload(tmp_path, mid)
    use = next(c for c in engine.legal_candidates() if OWNER in c.target_ids and 'Dao' in c.display_name)
    prompts = settle(table, mid, use.candidate_id,
        {'choice:needle.glass_surface_mark': 'mark' if accept else None})
    offers = [p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.glass_surface_mark']
    assert offers and all(p['context']['reactor_id'] == OWNER for p in offers)
    assert all('Dao' in p['moment'] and 'tempered Glass Surface' in p['moment'] for p in offers)
    assert marked(reload(tmp_path, mid).state.actors[FOE], OWNER) == accept
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    assert session.verify()['status'] == session.mechanical.replay()['status'] == 'PASS'


@pytest.mark.parametrize('ai_attack', [False, True])
def test_friendly_native_starbolt_still_asks_the_tempered_body_owner(tmp_path, ai_attack):
    from tests.auto_worker1_support import action_sender, fight as build_fight
    from tests.test_mgr_t14_starbolt_base import acquired_starbolt
    from canonical_catalog.service import CanonicalCatalogAuthorityService
    from sphere_component_authority import attach_sphere_automatic_component_receipt
    from combat.ext.glass_refraction import marked
    def acquire(doc, actor_id):
        acquired_starbolt(doc, actor_id)
        if actor_id != RIGHT:
            return
        parent = CanonicalCatalogAuthorityService(ROOT).get_sphere('tianxia.sphere.glass')
        ledger = {}
        packet = attach_sphere_automatic_component_receipt(ledger, parent, {
            'event_id': 'glass-friendly-attack-acquisition', 'legal_channel': 'sphere_acquisition',
            'advancement': {'target_cl': 1}})
        assert {'GLASS_BASE_FAULTLINE_MARKS', 'GLASS_BASE_TEMPER_GLASS_SURFACE'} <= set(packet['component_ids'])
        doc['spheres_and_talents'] = {'sphere_record_ids': ['tianxia.sphere.glass'],
            'learned_talent_record_ids': [], 'automatic_sphere_component_record_ids': packet['component_ids'],
            'automatic_sphere_component_receipts': ledger['automatic_sphere_component_receipts'],
            'automatic_sphere_components': ledger['automatic_sphere_components']}
    combat, table, mid = build_fight(tmp_path, sheet_edit=acquire, left_attack_bonus=100,
        right_team='team:factory', extra_witness=True)
    turn(table, mid, RIGHT)
    resolve(lambda answers: act(table, mid, 'Temper Glass Surface', answers))
    turn(table, mid, LEFT)
    _, prompts = resolve(action_sender(combat, table, mid, 'Starbolt', target_id=RIGHT, ai=ai_attack),
        {TYPE_CHOICE: ['FORCE'], 'choice:needle.starbolt_mark': [],
         'choice:needle.glass_surface_mark': ['mark'], 'choice:needle.refraction_response': []})
    offers = [p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.glass_surface_mark']
    assert offers and all(p['context']['reactor_id'] == RIGHT for p in offers)
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    engine = session.engine
    assert engine.state.actors[LEFT].team_id == engine.state.actors[RIGHT].team_id
    assert marked(engine.state.actors[LEFT], RIGHT)
    assert not marked(engine.state.actors[RIGHT], LEFT)
    assert session.verify()['status'] == session.mechanical.replay()['status'] == 'PASS'


def test_declining_an_attack_mark_still_allows_its_committed_damage_trigger(tmp_path):
    from tests.worker2_support import OWNER, FOE, settle, reload
    from combat.ext.glass_refraction import marked
    combat, table, mid, pane_id = glass_surface_fight(tmp_path)
    engine = reload(tmp_path, mid)
    use = next(c for c in engine.legal_candidates() if pane_id in c.target_ids)
    # A real attack can miss. Keep both trigger assertions, but advance through
    # native turns until damage actually commits rather than assuming a hit.
    from tests.worker2_support import turn as visit
    for _ in range(8):
        before = engine.state.event_sequence
        prompts = settle(table, mid, use.candidate_id,
            {'choice:needle.glass_surface_mark': (None, 'mark')})
        marks = [p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.glass_surface_mark']
        engine = reload(tmp_path, mid)
        damage = [e.payload['damage'] for e in engine.events if e.sequence > before
                  and e.event_type == 'OBJECT_UPDATED' and e.payload.get('damage', {}).get('hp_damage', 0) > 0]
        if damage:
            assert len(marks) == 2
            assert 'attacks' in marks[0]['moment'] and 'damage' in marks[1]['moment']
            assert marked(engine.state.actors[FOE], OWNER)
            return
        assert len(marks) == 1 and not marked(engine.state.actors[FOE], OWNER)
        settle(table, mid, table.state(mid)['menu']['end_turn'])
        visit(table, mid, FOE)
        engine = reload(tmp_path, mid)
        use = next(c for c in engine.legal_candidates() if pane_id in c.target_ids)
    raise AssertionError('No damaging native pane attack in eight turns')


def test_unseen_surface_attacker_keeps_identity_private_but_mark_remains_legal(tmp_path):
    from tests.worker2_support import OWNER, FOE, settle, reload
    from combat.ext.glass_refraction import marked
    combat, table, mid, pane_id = glass_surface_fight(tmp_path, hidden=True)
    engine = reload(tmp_path, mid)
    use = next(c for c in engine.legal_candidates() if pane_id in c.target_ids)
    prompts = settle(table, mid, use.candidate_id, {'choice:needle.glass_surface_mark': 'mark'})
    offered = [p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.glass_surface_mark']
    assert offered
    for prompt in offered:
        assert 'unseen creature' in prompt['moment']
        assert 'Mara' not in prompt['moment'] and 'Dao' not in prompt['moment']
    assert marked(reload(tmp_path, mid).state.actors[FOE], OWNER)
    assert CombatService(ROOT, tmp_path)._load_session(mid).mechanical.replay()['status'] == 'PASS'


def test_capacity_choice_does_not_reveal_an_unseen_existing_mark_recipient(tmp_path):
    from tests.worker2_support import OWNER, FOE, settle, reload, turn as visit
    from combat.ext.glass_refraction import marked
    combat, table, mid, pane_id = glass_surface_fight(tmp_path, hidden=True,
        extra_foes=2, owner_pb=2, visit_foe=False)
    capacity = []
    for attacker in (FOE, FOE + '1', FOE + '2'):
        visit(table, mid, attacker)
        engine = reload(tmp_path, mid)
        use = next(c for c in engine.legal_candidates() if pane_id in c.target_ids)
        prompts = settle(table, mid, use.candidate_id, {'choice:needle.glass_surface_mark': 'mark'})
        capacity.extend(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.glass_faultline_replace')
    assert len(capacity) == 1
    readable = str(capacity[0]['choice']['options']) + capacity[0]['moment']
    assert 'unseen creature' in readable and 'Mara' not in readable
    assert len(capacity[0]['choice']['options']) == 2
    engine = reload(tmp_path, mid)
    assert sum(marked(actor, OWNER) for actor in engine.state.actors.values()) == 2
    assert CombatService(ROOT, tmp_path)._load_session(mid).mechanical.replay()['status'] == 'PASS'


def test_gm_model_schema_checksum_tracks_committed_composite_removal(tmp_path):
    import hashlib
    import json
    from factory_authoring import command5_profile as profiles
    path = ROOT / 'factory_authoring/contracts/Tianxia_C2B3_GM_Character_Model_Profile_R1.schema.json'
    # Pin the shipped migrated public artifact, not unavailable Git history.
    assert hashlib.sha256(path.read_bytes()).hexdigest() == 'd18e82ace1aed49ec44a3179f93241e6ffc9d14f4e46e4f6b4b0f07594bf1772'
    expected = json.loads(path.read_text())
    assert 'composites' not in expected['properties']
    assert 'composites' not in expected['required']
    profile = profiles.CharacterGMCommand5Profile.__new__(profiles.CharacterGMCommand5Profile)
    schema, digest = profile._model_schema()
    assert schema == expected and digest == hashlib.sha256(path.read_bytes()).hexdigest()
    (tmp_path / path.name).write_bytes(path.read_bytes() + b'\n')
    (tmp_path / (path.name + '.sha256')).write_bytes(path.with_suffix('.json.sha256').read_bytes())
    class AlteredProfile(profiles.CharacterGMCommand5Profile):
        @property
        def _contracts_dir(self):
            return tmp_path
    with pytest.raises(profiles.FoundryError, match='checksum is stale'):
        AlteredProfile.__new__(AlteredProfile)._model_schema()


def test_projection_binding_is_the_committed_profile_migration_not_a_bypass(tmp_path):
    import hashlib
    import json
    from app.core import FoundryError, sha256_json
    from projector.v3_bridge import _read_sealed
    from character_sheet.service import CharacterSheetService
    contracts = ROOT / 'projector/contracts'
    name = 'C2AR1_Stage_Aware_Validation_Profile.json'
    current = (contracts / name).read_bytes()
    expected = json.loads(current)
    assert 'composite_playbooks' not in expected['later_stage_nodes']['gm_screen']
    assert expected['seal_sha256'] == sha256_json({k: v for k, v in expected.items() if k != 'seal_sha256'})
    path = contracts / 'C2AR1_Stage2_v3_Projection_Contract.json'
    contract = _read_sealed(path, schema_version='TianxiaFoundry.Stage2V3FactoryProjectionContract.v1',
                            mismatch_code='BAD_CONTRACT')
    assert contract['validation_profile']['sha256'] == hashlib.sha256(current).hexdigest()
    assert path.with_suffix('.json.sha256').read_text().split()[0] == hashlib.sha256(path.read_bytes()).hexdigest()
    contract['validation_profile']['sha256'] = '0' * 64
    forged = tmp_path / 'forged.json'
    forged.write_text(json.dumps(contract))
    with pytest.raises(FoundryError):
        _read_sealed(forged, schema_version=contract['schema_version'], mismatch_code='BAD_CONTRACT')
    readiness = ROOT / 'character_sheet/contracts/Tianxia_Character_Sheet_Readiness_Profile_R1.json'
    CharacterSheetService._verify_sealed_json(readiness,
        expected_schema='TianxiaFoundry.CharacterSheetReadinessProfile.v1',
        error_prefix='CHARACTER_SHEET_READINESS_PROFILE')


# Shared-engine replay coverage lives in tests/test_a2_glass_stock.py, run in
# its own heavyq chunk against the current merge base. Do not duplicate it here
# with an obsolete pre-merge base or private history imports.
