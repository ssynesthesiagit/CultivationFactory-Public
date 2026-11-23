"""The map editor's sight preview matches the fight for free-standing blocking objects (review F3R2 finding 1).

The editor preview (static/tabletop/vision.js mapCenterlines, fed the server's object presets) must mark the same
centre-plus squares the fight's object zones resolve (combat/ext/objects.py via combat/object_rules.py sight). Without
the presets it drew nothing for a boulder, so a player building a map saw clear sight that the fight then blocked.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from combat import object_rules
from combat.tabletop import normalize_map

APP = Path(__file__).resolve().parents[1]
OBJECTS = [
    {'kind': 'boulder_pile', 'x': 3, 'y': 3},
    {'kind': 'pillar', 'x': 5, 'y': 1},
    {'kind': 'statue', 'x': 1, 'y': 6},
    {'kind': 'door', 'x': 6, 'y': 6},          # a closed door fills its square: a whole-square blocker, not a plus
    {'kind': 'crate', 'x': 2, 'y': 2},         # a crate does not block sight at all
]


def _editor_preview(tmp_path, document, presets):
    fixture = tmp_path / 'editor_sight.json'
    fixture.write_text(json.dumps({'doc': document, 'presets': presets}), encoding='utf-8')
    result = subprocess.run(['node', 'tests/editor_object_sight.mjs', str(fixture)], cwd=APP, text=True,
                            capture_output=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    return {tuple(cell) for cell in json.loads(result.stdout)}


def test_editor_preview_marks_the_server_centre_plus_for_each_placed_object(tmp_path):
    document = normalize_map({'display_name': 'Yard', 'width_squares': 8, 'height_squares': 8, 'objects': OBJECTS})
    rows = {(row['x'], row['y']): row for row in document['objects']}
    # The server's own resolved shape for each object is the reference; the editor must reproduce it.
    # Whether a kind blocks at all is combat/object_rules.py stats (the fight's own answer, an authored
    # 'blocks' wins); the resolved sight shape is the row's, written by normalize_map from object_rules.sight.
    server_plus = {cell for cell, row in rows.items()
                   if object_rules.stats(row)['blocks'] and row['occluder'] == 'centerline'}
    assert server_plus == {(3, 3), (5, 1), (1, 6)}
    assert rows[(6, 6)]['occluder'] == 'cell' and rows[(6, 6)]['sight_class'] == 'door'
    presets = json.loads(json.dumps(object_rules.editor_defaults()['presets']))
    # The editor's own copy of the document carries no resolved fields: it must read them from the presets.
    bare = {'width_squares': 8, 'height_squares': 8,
            'objects': [{k: row[k] for k in ('kind', 'x', 'y')} for row in document['objects']]}
    assert _editor_preview(tmp_path, bare, presets) == server_plus


def test_editor_preview_without_presets_draws_no_plus_for_a_placed_boulder(tmp_path):
    # Regression guard: the preview used to ignore doc.objects entirely.
    bare = {'width_squares': 8, 'height_squares': 8, 'objects': [{'kind': 'boulder_pile', 'x': 3, 'y': 3}]}
    assert _editor_preview(tmp_path, bare, {}) == set()
    assert _editor_preview(tmp_path, bare, object_rules.editor_defaults()['presets']) == {(3, 3)}


def test_preset_sight_and_blocks_are_the_servers_own_answer():
    presets = object_rules.editor_defaults()['presets']
    assert presets['boulder_pile']['sight'] == object_rules.sight('boulder_pile') == {'occluder': 'centerline', 'sight_class': 'object'}
    assert presets['door']['sight'] == {'occluder': 'cell', 'sight_class': 'door'}
    assert presets['boulder_pile']['blocks'] is True and presets['crate']['blocks'] is False


def _strip_resolved(document):
    """The editor's copy of a map before its first save: the rows keep their shape but carry no resolved occluder."""
    bare = json.loads(json.dumps(document))
    for row in bare.get('trees') or []:
        row.pop('occluder', None)
    for row in bare.get('materials') or []:
        row.pop('occluder', None)
    for row in bare.get('walls') or []:
        row.pop('occluder', None)
        row.pop('sight_class', None)
    return bare


def test_unsaved_trees_thickets_and_drawn_walls_preview_what_the_fight_blocks(tmp_path):
    # Review F4R findings 1 and 2: before its first save a tree, a painted thicket or a drawn wall has no resolved
    # occluder. The preview must still show the fight's own answer for each: a centre plus, or a full square for a rect.
    raw = {'display_name': 'Grove', 'width_squares': 12, 'height_squares': 12,
           'trees': [{'x': 5, 'y': 5, 'size': 1}, {'x': 7, 'y': 7, 'size': 1, 'occluder': 'cell'}],
           'materials': [{'material': 'terrain:bamboo thicket', 'cells': [[2, 2], [2, 3], [3, 2], [3, 3]]}],
           'walls': [{'id': 'drum', 'shape': 'circle', 'points': [[9, 9], [10, 9]], 'filled': True, 'blocks': 'sight_and_movement'},
                     {'id': 'gate-wall', 'shape': 'rect', 'points': [[7, 1], [8, 2]], 'filled': True, 'blocks': 'sight_and_movement'}]}
    server = normalize_map(raw)
    presets = json.loads(json.dumps(object_rules.editor_defaults()['presets']))
    server_preview = _editor_preview(tmp_path, server, presets)
    bare = _strip_resolved(server)
    bare['trees'][1]['occluder'] = 'cell'                              # the author's own choice survives an unsaved edit
    bare_preview = _editor_preview(tmp_path, bare, presets)
    assert bare_preview == server_preview
    assert {(5, 5), (2, 2), (2, 3), (3, 2), (3, 3)} <= bare_preview   # tree and thicket: centre plus per square
    assert not {(7, 1), (8, 2)} & bare_preview                         # a rect wall fills its squares: no plus
    assert (7, 7) not in bare_preview                                  # an authored 'cell' tree keeps its whole square


# The full-square kinds, and why each fills its square (combat/rules/objects.json "occluder": "cell"). Every other
# blocking kind is seen through the centre plus (owner 2026-10-23: plus symbols are the default for most objects).
FULL_SQUARE_KINDS = {
    'door': 'a closed door fills its opening',
    'gate': 'a barred gate fills its opening',
    'barricade': 'stakes lashed into a solid barrier across the square',
    'wall_section': 'dressed masonry filling its square',
    'fence_section': 'a run of fence boards across the square',
    'palisade_section': 'upright logs filling the square',
    'sandbag_wall': 'a stacked wall of sandbags filling the square',
}


def test_default_sight_shape_is_the_centre_plus_except_listed_square_fillers():
    presets = object_rules.editor_defaults()['presets']
    full = {kind for kind, preset in presets.items() if preset['sight']['occluder'] == 'cell'}
    assert full == set(FULL_SQUARE_KINDS)
    # Every other blocking object (boulders, pillars, statues, carts, furnaces ...) is seen through its plus.
    plus = {kind for kind, preset in presets.items() if preset['blocks'] and kind not in full}
    assert {'boulder_pile', 'pillar', 'statue', 'cart', 'alchemy_furnace', 'village_well'} <= plus
    assert all(presets[kind]['sight']['occluder'] == 'centerline' for kind in plus)
    # Scenery that does not block sight at all (a crate, a barrel) is not a plus either.
    assert presets['crate']['blocks'] is False and presets['barrel']['blocks'] is not True
