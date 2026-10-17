"""Canonical Realm suppression must cap native Subpath actions and passives.

Synthetic NS1R acquisition and table commits only; no private package or history.
"""
import ast
from pathlib import Path

import pytest

from combat.ext.qi_subpaths_five import FEATHER, feather_fall
from combat.factory_compiler import compile_character
from tests.test_seamfix_subpath_healing_melody import (
    acquired, public_background_catalog, scenario, play, medium, MELODY,
)
from tests.worker2_support import fixture, reload, turn, OWNER, ALLY, FOE

CLOUD_SUBPATH = 'tianxia.subpath.qi.cloud_walker'


def test_primary_regression_imports_only_public_safe_test_support():
    """Prevent the project helper from dragging in unrelated package/archive tests."""
    source = Path(__file__).with_name('test_seamfix_subpath_healing_melody.py').read_text()
    imports = {node.module for node in ast.walk(ast.parse(source))
               if isinstance(node, ast.ImportFrom) and (node.module or '').startswith('tests.')}
    assert imports <= {
        'tests.h1_support', 'tests.ns1r_evidence_helpers', 'tests.ns1r_public_schema', 'tests.worker2_support',
        'tests.test_r9i_karma_persistence',
    }


def test_public_acquisition_installation_declares_only_runtime_inputs(acquired):
    # Native service construction already checked these declared file hashes.
    authority = acquired.service
    assert authority.identity['files']
    assert all(name.endswith(('.json', '.py')) for name in authority.identity['files'])
    assert all((authority.authority_root / name).is_file() for name in authority.identity['files'])


def test_recorded_realm_suppression_caps_healing_after_commit_and_cold_reload(tmp_path, acquired):
    combat, table, mid = scenario(tmp_path, acquired, cl=18, realm_cl=6)
    play(combat, table, mid, 'Instrument of Qi: Thunder', FOE)
    before = reload(tmp_path, mid)
    hp = before.state.actors[FOE].current_hp
    qi = before.state.actors[OWNER].resources['resource:core.qi']
    play(combat, table, mid, 'Healing Melody', FOE,
         choices={'choice:needle.qi5_melody': ['move']})
    after = reload(tmp_path, mid)
    healing = [roll for roll in after.rolls if roll.reason.startswith('HEALING:')][-1]
    assert healing.expression.startswith('2d8')
    assert after.state.actors[FOE].current_hp == min(60, hp + healing.total)
    assert after.state.actors[OWNER].resources['resource:core.qi'] == qi - 2
    actions = [action for action in after.action_catalog.values()
               if (action.parameters.get('typed') or {}).get('source') == MELODY]
    assert actions
    assert all(action.parameters['typed']['numbers']['cl'] == 6 for action in actions)


@pytest.mark.parametrize('condition,source_cl,realm_cl,removable', [
    ('deafened', 10, 6, False), ('deafened', 10, 10, True),
    ('frightened', 14, 6, False), ('frightened', 14, 14, True),
])
def test_recorded_realm_suppression_caps_cleansing_authority(
        tmp_path, acquired, condition, source_cl, realm_cl, removable):
    # The condition's native technique retains its own printed source authority.
    foe = acquired(source_cl)
    foe['ability_scores_and_statistics']['technique_save_dc'] = 100
    combat, table, mid = scenario(tmp_path, acquired, cl=18, realm_cl=realm_cl, foe=foe, media=medium())
    turn(table, mid, FOE)
    if condition == 'deafened':
        play(combat, table, mid, 'Shattering Note', at=(3, 6))
        recipient = ALLY
    else:
        play(combat, table, mid, 'Song of Fear')
        recipient = OWNER
    turn(table, mid, OWNER)
    before = reload(tmp_path, mid)
    assert any(c.condition_id == 'condition:typed.' + condition
               for c in before.state.actors[recipient].conditions.values())
    prompts = play(combat, table, mid, 'Healing Melody', recipient,
                   choices={'choice:needle.qi5_melody': [condition] if removable else ['move']})
    prompt = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.qi5_melody')
    assert (condition in {option['id'] for option in prompt['choice']['options']}) is removable
    after = reload(tmp_path, mid)
    assert any(c.condition_id == 'condition:typed.' + condition
               for c in after.state.actors[recipient].conditions.values()) is not removable


@pytest.mark.parametrize('realm_cl', [1, 5])
def test_recorded_realm_suppression_withholds_native_and_stale_melody(acquired, realm_cl):
    doc = acquired(18)
    doc['path_and_subpath']['source_granted_subpath_feature_record_ids'] = [MELODY]
    doc['identity']['effective_cultivation_level'] = realm_cl
    bundle = compile_character(doc, actor_id=OWNER)
    assert not any((action.get('parameters') or {}).get('typed', {}).get('source') == MELODY
                   for action in bundle['action_catalog'])


@pytest.mark.parametrize('path_cl,realm_cl,expected_cl', [(18, 6, 6), (3, 6, 3), (18, 18, 18)])
def test_recorded_realm_suppression_caps_passive_after_table_commit(
        tmp_path, acquired, path_cl, realm_cl, expected_cl):
    doc = acquired(18, CLOUD_SUBPATH)
    doc['identity']['effective_cultivation_level'] = realm_cl
    row = next(row for row in doc['path_and_subpath']['paths']
               if row['path_id'] == 'tianxia.path.qi_cultivation')
    row['effective_cl'] = path_cl
    bundle = compile_character(doc, actor_id=OWNER)
    combat, table, mid = fixture(tmp_path, [], cl=18, owner_bundle=bundle)
    play(combat, table, mid, 'Dodge')
    engine = reload(tmp_path, mid)
    passive = next(row for row in engine.typed_passive_rows[OWNER] if row['feature_id'] == FEATHER)
    assert passive['cl'] == expected_cl
    assert feather_fall(engine, engine.state.actors[OWNER], 100, None, None) == {
        'amount': 100 - 5 * expected_cl,
    }
