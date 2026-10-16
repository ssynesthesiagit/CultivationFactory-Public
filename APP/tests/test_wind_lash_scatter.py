"""Native Scatter choices, transactional commits and cold mechanical replay."""
import pytest

from combat.tabletop import normalize_map, to_battlefield
from tests.cw2_service_support import seal
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, reload


def setup(tmp_path, *, mode='MANUAL', hit=True, blocked=False, eligible=True, occluded=False):
    def bundles(rows):
        for bundle, initiative in zip(rows, (100, -100, 0)):
            bundle['actor_template']['initiative_bonus'] = initiative
            bundle['actor_template']['maximum_hp'] = 500
            for action in bundle['action_catalog']:
                if action['display_name'].startswith('Wind Lash:'):
                    action['parameters']['typed']['numbers']['attack_bonus'] = 100 if hit else -100
            seal(bundle)
    objects = [
        {'id': 1, 'name': 'Copper bead', 'x': 7, 'y': 6, 'size': 'tiny' if eligible else 'small'},
        {'id': 2, 'name': 'Silver bead', 'x': 6, 'y': 7, 'size': 'tiny' if eligible else 'small'},
        {'id': 3, 'name': 'Held bead', 'x': 7, 'y': 7, 'size': 'tiny', 'unattended': False},
        {'id': 4, 'name': 'Large box', 'x': 5, 'y': 7, 'size': 'medium'},
        {'id': 5, 'name': 'Distant bead', 'x': 9, 'y': 6, 'size': 'tiny'},
    ]
    arena = to_battlefield(normalize_map({'display_name': 'Scatter yard', 'width_squares': 16,
        'height_squares': 14, 'objects': [dict(o, kind='custom', blocks=False) for o in objects]}))
    if blocked:
        # A solid modeled obstacle is supplied at genesis, not inserted in live state.
        arena['map_objects'].append({'id': 6, 'kind': 'custom', 'name': 'Stone pillar',
                                     'x': 6, 'y': 8, 'size': 'medium', 'blocks': True})
    if occluded:
        arena['map_objects'].append({'id': 7, 'kind': 'custom', 'name': 'Screening pillar',
                                     'x': 4, 'y': 7, 'size': 'medium', 'blocks': True})
    return fixture(tmp_path, ['AIR_BASE_WIND_LASH'], bundle_transform=bundles,
        modes={OWNER: mode, ALLY: 'MANUAL', FOE: 'MANUAL'}, battlefield=arena,
        positions={OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 4, 'y': 6}, FOE: {'x': 6, 'y': 6}},
        named=True, seed='SCATTER')


@pytest.mark.parametrize('mode', ['MANUAL', 'SUGGESTED'])
@pytest.mark.parametrize('destination', ['cell:5,8', 'cell:6,8', 'cell:6,7', 'cell:6,7,1'])
def test_scatter_owned_subject_direction_shorter_zero_reload(tmp_path, mode, destination):
    combat, table, mid = setup(tmp_path, mode=mode)
    before = reload(tmp_path, mid)
    prompts = settle(table, mid, candidate(combat, mid, 'Wind Lash: Scatter', target=FOE).candidate_id,
        choices={'choice:needle.displace_object_subject': 'object:map.2',
                 'choice:needle.displace_object_destination': destination})
    subject = next(p for p in prompts if p['context']['reaction_source_id'].endswith('displace_object_subject'))
    assert {o['id'] for o in subject['choice']['options']} == {'object:map.1', 'object:map.2'}
    assert subject['context']['reactor_id'] == OWNER
    assert 'Wind Lash' in subject['moment'] and 'Mara' in subject['moment']
    engine = reload(tmp_path, mid)
    wanted = tuple(map(int, destination.split(':')[1].split(',')))
    wanted = (*wanted, 0) if len(wanted) == 2 else wanted
    position = engine.state.objects['object:map.2'].position
    assert (position.x, position.y, position.z) == wanted
    assert engine.state.objects['object:map.1'].position == before.state.objects['object:map.1'].position
    assert engine.state.actors[FOE].current_hp < before.state.actors[FOE].current_hp
    assert engine.state.actors[OWNER].position == before.state.actors[OWNER].position


@pytest.mark.parametrize('case', ['miss', 'ineligible', 'decline_subject', 'decline_destination', 'blocked'])
def test_scatter_never_invents_a_move(tmp_path, case):
    combat, table, mid = setup(tmp_path, hit=case != 'miss', eligible=case != 'ineligible', blocked=case == 'blocked')
    before = reload(tmp_path, mid)
    choices = {'choice:needle.displace_object_subject': None if case == 'decline_subject' else 'object:map.2',
               'choice:needle.displace_object_destination': None}
    prompts = settle(table, mid, candidate(combat, mid, 'Wind Lash: Scatter', target=FOE).candidate_id, choices=choices)
    engine = reload(tmp_path, mid)
    assert {k: v.position for k, v in engine.state.objects.items()} == {k: v.position for k, v in before.state.objects.items()}
    if case in ('miss', 'ineligible'):
        assert not any(p['context']['reaction_source_id'].endswith('displace_object_subject') for p in prompts)
    if case == 'blocked':
        ids = {o['id'] for p in prompts if p['context']['reaction_source_id'].endswith('displace_object_destination')
               for o in p['choice']['options']}
        assert 'cell:6,8' not in ids and 'cell:6,9' not in ids
        assert 'cell:5,7' in ids and 'cell:6,7' in ids


def test_scatter_object_hit_uses_same_owned_choices_and_reload(tmp_path):
    combat, table, mid = setup(tmp_path)
    options = [c for c in combat._load_session(mid).engine.legal_candidates()
               if c.display_name == 'Wind Lash: Scatter (at an object)']
    assert options and all(c.target_ids != ('object:map.3',) for c in options)
    # Hit the box, then move a nearby bead, rather than substituting the box.
    chosen = next(c for c in options if c.target_ids == ('object:map.4',))
    settle(table, mid, chosen.candidate_id,
           choices={'choice:needle.displace_object_subject': 'object:map.2',
                    'choice:needle.displace_object_destination': 'cell:6,8'})
    engine = reload(tmp_path, mid)
    assert (engine.state.objects['object:map.2'].position.x, engine.state.objects['object:map.2'].position.y) == (6, 8)
    assert any(e.event_type == 'ATTACK_ROLLED' and e.target_ids == ('object:map.4',) for e in engine.events)


def test_scatter_ai_automatically_resolves_only_known_legal_options(tmp_path):
    from combat.gate4_adapters import ManualControllerAdapter
    combat, table, mid = setup(tmp_path, mode='LOCAL_AUTO')
    before = reload(tmp_path, mid)
    # The action intent remains native; the computer-controlled owner answers
    # Needle's riders automatically without a model transport.
    cid = candidate(combat, mid, 'Wind Lash: Scatter', target=FOE).candidate_id
    real = combat.controller
    combat.controller = ManualControllerAdapter(lambda context: (cid, ()),
        reaction_chooser=lambda context: real.choose_reaction(context).decision)
    prompts = settle(table, mid, cid, auto=True)
    assert not any(p['context']['reaction_source_id'].startswith('choice:needle.displace_object') for p in prompts)
    engine = reload(tmp_path, mid)
    moved = [key for key in ('object:map.1', 'object:map.2')
             if engine.state.objects[key].position != before.state.objects[key].position]
    assert len(moved) == 1
    assert any(e.event_type == 'OBJECT_UPDATED' and moved[0] in e.target_ids for e in engine.events)
    assert engine.state.objects['object:map.3'].unattended is False
    assert engine.state.objects['object:map.3'].position.x == 7


def test_scatter_pending_choice_is_transactional(tmp_path):
    from tests.test_r9i_karma_persistence import act
    combat, table, mid = setup(tmp_path)
    before = reload(tmp_path, mid)
    result = act(table, mid, candidate(combat, mid, 'Wind Lash: Scatter', target=FOE).candidate_id)
    assert result['status'] == 'REACTION_REQUIRED'
    # A paused choice has not committed even the enclosing hit/damage.
    engine = reload(tmp_path, mid)
    assert engine.state.model_dump(mode='json') == before.state.model_dump(mode='json')


@pytest.mark.parametrize('mode', ['MANUAL', 'SUGGESTED', 'LOCAL_AUTO'])
def test_scatter_direction_does_not_require_attacker_sight_of_destination(tmp_path, mode):
    from combat.senses import perceives_cell
    from combat.gate2_runtime_models import Position
    combat, table, mid = setup(tmp_path, mode=mode, occluded=True)
    engine = reload(tmp_path, mid)
    assert not perceives_cell(engine, engine.state.actors[OWNER], Position(x=5, y=8))
    choices = {'choice:needle.displace_object_subject': 'object:map.2',
               'choice:needle.displace_object_destination': 'cell:5,8'}
    cid = candidate(combat, mid, 'Wind Lash: Scatter', target=FOE).candidate_id
    seen = []
    if mode == 'LOCAL_AUTO':
        from combat.ext.object_displacement import destinations
        from combat.ext.needle import cell_id
        from combat.gate4_adapters import ManualControllerAdapter
        legal = {cell_id(cell) for cell in destinations(engine, engine.state.objects['object:map.2'], 10)}
        real = combat.controller

        def choose(context):
            decision = real.choose_reaction(context).decision
            if context.reaction_source_id in choices:
                if context.reaction_source_id.endswith('displace_object_destination'):
                    # The same extension spec is offered to local/model choosers:
                    # unseen directions and staying put remain legal choices.
                    assert set(context.extension_choice.option_ids) == legal
                    assert 'cell:6,7' in legal and 'cell:5,8' in legal
                    seen.append(context)
                return decision.model_copy(update={'selection': 'USE',
                    'option_ids': (choices[context.reaction_source_id],)})
            return decision

        combat.controller = ManualControllerAdapter(lambda context: (cid, ()), reaction_chooser=choose)
    settle(table, mid, cid, choices=choices, auto=mode == 'LOCAL_AUTO')
    if mode == 'LOCAL_AUTO':
        assert seen
    engine = reload(tmp_path, mid)
    assert engine.state.objects['object:map.2'].position == Position(x=5, y=8)
