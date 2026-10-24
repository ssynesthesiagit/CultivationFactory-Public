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
    server_plus = {cell for cell, row in rows.items() if row['blocks'] and row['occluder'] == 'centerline'}
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
