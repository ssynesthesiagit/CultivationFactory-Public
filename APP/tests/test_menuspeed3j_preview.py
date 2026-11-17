"""Offline coverage of the production lazy picker and its hover highlight path."""
import json
from pathlib import Path
import subprocess

import pytest
from tests.test_menuspeed3_review import offline_menu_embeddings


def assert_client_preview(choice, hover, height, expected):
    source = (Path(__file__).resolve().parents[1] / 'static/tabletop/tabletop.js').read_text()
    def function(start, end):
        offset = source.index(start)
        return source[offset:source.index(end, offset)]
    code = function('function mapPickCells(', '// A place choice is always')
    code += function('function renderHighlights()', 'function hint(')
    script = '''
      const app = {mapPick: null, hoverCell: HOVER, menu: null};
      const moveHeight = () => HEIGHT;
      let shown;
      const board = {setHighlights: value => {shown = value;}, setMovementExplanation() {}};
      const heightMovement = () => null, selectedMoves = () => [], renderTokens = () => {};
      CODE
      const choice = CHOICE;
      app.mapPick = {...mapPickCells(choice), prompt: {choice}};
      renderHighlights();
      if (JSON.stringify(shown.areaCells) !== JSON.stringify(EXPECTED))
        throw new Error('Native hover footprint missing: ' + JSON.stringify(shown));
      if (shown.moves.length !== choice.options.length) throw new Error('Legal aims were removed');
      app.hoverCell = {x: 999, y: 999};
      renderHighlights();
      if (shown.areaCells?.length) throw new Error('Stale footprint on an illegal square');
    '''
    for key, value in [('HOVER', hover), ('HEIGHT', height), ('CHOICE', choice), ('EXPECTED', expected)]:
        script = script.replace(key, json.dumps(value))
    script = script.replace('CODE', code)
    result = subprocess.run(['node', '-e', script], text=True, capture_output=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize('height', [0, 4])
def test_live_highlight_path_keeps_each_altitude_footprint(height):
    areas = {'cell:2,3,0': [{'x': 2, 'y': 3}, {'x': 3, 'y': 3}],
             'cell:2,3,4': [{'x': 2, 'y': 3, 'z': 4}, {'x': 2, 'y': 4, 'z': 4}]}
    choice = {'options': [{'id': key, 'cell': {'x': 2, 'y': 3, 'z': z}}
                          for key, z in zip(areas, [0, 4])], 'map_pick': {'areas': areas}}
    assert_client_preview(choice, {'x': 2, 'y': 3}, height, areas[f'cell:2,3,{height}'])


@pytest.mark.parametrize('shape', ['sphere', 'cone', 'line'])
def test_real_lazy_picker_uses_native_footprints_for_each_aim(tmp_path, shape):
    from combat.canonical import canonical_sha256
    from combat.placement_menu import CHOICE, cells
    from combat.typed_executor import area_cells
    from combat.ext.needle import cell_id
    from tests.worker2_support import OWNER, fixture, settle

    area = {'shape': shape, 'size_ft': 10, 'width_ft': 5}
    def probe(bundles):
        bundle = bundles[0]
        sid = 'action:test.preview'
        bundle['actor_template']['action_ids'].append(sid)
        bundle['action_catalog'].append({'source_definition_id': sid, 'owner_id': OWNER,
            'display_name': 'Area preview probe', 'economy': 'ACTION', 'resolution_kind': 'TYPED',
            'target_kind': 'CELL', 'range_ft': 60, 'radius_ft': 10, 'parameters': {'typed': {
                'area': area, 'effects': [], 'numbers': {}, 'duration': {'kind': 'instant'}, 'riders': []}}})
        bundle.pop('bundle_sha256', None)
        bundle['bundle_sha256'] = canonical_sha256(bundle)
    combat, table, mid = fixture(tmp_path, [], bundle_transform=probe)
    state = table.state(mid)
    group = next(g for g in state['menu']['actions'] if g['label'].startswith('Area preview probe'))
    assert group['placement_picker']
    assert len(group['options']) == 1 and not group['options'][0]['area']
    engine = combat._load_session(mid).engine
    root = next(c for c in combat._legal_candidates(combat._load_session(mid))
                if c.candidate_id == group['options'][0]['candidate_id'])
    native = list(cells(engine, root))
    chosen = native[-1]
    prompts = settle(table, mid, root.candidate_id,
                     picks={CHOICE: cell_id(chosen.destination, include_altitude=True)})
    picker = next(p for p in prompts if p['context']['reaction_source_id'] == CHOICE)
    choice = picker['choice']
    assert {o['id'] for o in choice['options']} == {cell_id(c.destination, include_altitude=True) for c in native}
    expected = {cell_id(c.destination, include_altitude=True): [p.model_dump(mode='json')
                for p in area_cells(engine, engine.state.actors[OWNER].position, c.destination, area)] for c in native}
    assert choice['map_pick']['areas'] == expected
    assert_client_preview(choice, chosen.destination.model_dump(mode='json'), chosen.destination.z,
                          expected[cell_id(chosen.destination, include_altitude=True)])


@pytest.mark.parametrize('shape', ['cone', 'line'])
def test_preview_uses_selected_origin_and_restores_geometry_scope(shape):
    from types import SimpleNamespace
    from combat.gate2_engine import Gate2Engine
    from combat.gate2_runtime_models import Position
    from combat.ext.placement_picker import area_previews
    from combat.ext.needle import cell_id
    from combat.typed_executor import area_cells
    engine = Gate2Engine(Path(__file__).resolve().parents[1], match_seed='PREVIEW-ORIGIN')
    actor = SimpleNamespace(entity_id='actor:test', position=Position(x=1, y=1))
    origin = {'id': 'origin:test', 'label': 'Raised source', 'position': {'x': 5, 'y': 5, 'z': 4}}
    aim = Position(x=7, y=5, z=4)
    area = {'shape': shape, 'size_ft': 10, 'width_ft': 5}
    action = SimpleNamespace(source_definition_id='action:test', parameters={'typed': {'area': area}})
    row = SimpleNamespace(area=True, destination=aim, metadata={'effect_origin': origin})
    before = getattr(engine, '_effect_origin', None)
    previews = area_previews(engine, actor, action, [row])
    expected = [p.model_dump(mode='json') for p in area_cells(engine, Position(**origin['position']), aim, area)]
    assert expected and previews == {cell_id(aim, include_altitude=True): expected}
    assert expected != [p.model_dump(mode='json') for p in area_cells(engine, actor.position, aim, area)]
    assert getattr(engine, '_effect_origin', None) == before
    assert area_previews(engine, actor, SimpleNamespace(parameters={}), [row]) == {}


def test_optional_footprint_transport_is_a_string_and_default_inert():
    from types import SimpleNamespace
    from combat.ext.needle import ask
    actor = SimpleNamespace(entity_id='actor:test', position=SimpleNamespace(x=2, y=3), active=True)
    seen = []
    def decision(*args, context):
        seen.append(context)
        return None
    engine = SimpleNamespace(state=SimpleNamespace(actors={actor.entity_id: actor}),
                             _gate4_reaction_cache={}, _reaction_decision=decision)
    intent = SimpleNamespace(actor_id=actor.entity_id)
    areas = {'cell:2,3,0': [{'x': 2, 'y': 3}]}
    for preview in (None, areas):
        assert ask(engine, intent, 'test', actor, 'choice:test', list(areas), space_areas=preview) == list(areas)
    assert 'space_areas' not in seen[0]
    assert isinstance(seen[1]['space_areas'], str)
    assert json.loads(seen[1]['space_areas']) == areas
