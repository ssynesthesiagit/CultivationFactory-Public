"""Refraction's supported owner declaration -> native payment -> cold replay.

These table fixtures isolate the state; they do not certify authenticated
Foundation progression. No live models, private campaign inputs or GUI.
"""
import hashlib
import json
from pathlib import Path

import pytest

from combat.ext.glass_heart_refraction import SOURCE
from combat.ext.foundation_combat import held, pool
from combat.tabletop_service import TabletopError
from combat.target_knowledge import recent_events
from tests.test_a2_foundations_two import table_fixture, use
from tests.worker2_support import OWNER, ALLY, FOE, reload, turn


def declare(combat, table, mid, scene='Major combat', clarity='Yes', actor_id=OWNER):
    forms = table.source_inputs(mid)
    return table.record_source_input(mid, SOURCE, actor_id,
        {'scene': scene, 'clarity': clarity,
         'reason': 'The mirror tribunal has become a decisive confrontation. I acknowledge the painful truth.'},
        forms['state_version'])


def available(engine):
    return [c for c in engine.legal_candidates() if SOURCE in c.source_definition_id]


def test_exact_source_and_owner_form(tmp_path):
    rules = json.loads((Path(__file__).resolve().parents[1] /
                        'authority/typed_mechanics/rules_text.json').read_text())
    assert hashlib.sha256(rules[SOURCE].encode()).hexdigest() == '61816edc9a444066bdb28e17dbde5d325392650930e0ceaa01f899faca3fcced'
    combat, table, mid = table_fixture(tmp_path, 'glass', current=0)
    form = table.source_inputs(mid)['forms'][0]
    assert form['actor_id'] == OWNER
    assert 'Bonus Action' in form['description'] and '2 CP' in form['description']
    assert not available(reload(tmp_path, mid))
    for stage in ('Awakened', 'Refined'):
        c, t, m = table_fixture(tmp_path / stage, 'glass', current=0, stage=stage)
        assert not t.source_inputs(m)['forms']
        with pytest.raises(TabletopError):
            declare(c, t, m)
    c, t, m = table_fixture(tmp_path / 'wrong', 'origin', current=0)
    assert not t.source_inputs(m)['forms']


@pytest.mark.parametrize('scene,clarity,qualifies', [
    ('Major combat', 'Yes', True), ('Emotionally decisive scene', 'Yes', True),
    ('Neither', 'Yes', False), ('Major combat', 'No', False)])
def test_private_scene_intent_and_native_paid_state(tmp_path, scene, clarity, qualifies):
    combat, table, mid = table_fixture(tmp_path, 'glass', current=0)
    before = reload(tmp_path, mid).state.actors[OWNER]
    declare(combat, table, mid, scene, clarity)
    engine = reload(tmp_path, mid)
    assert bool(available(engine)) == qualifies
    assert held(engine.state.actors[OWNER], 'glass_refraction') is None
    assert not any(e['source_definition_id'] == 'system:combat.table_fact'
                   for e in recent_events(engine, engine.state.actors[FOE], engine.events))
    assert not any('tribunal' in str(e) for e in table.events(mid, 0)['events'])
    if not qualifies:
        assert engine.state.actors[OWNER].resources == before.resources
        return
    assert available(engine)[0].kind.value == 'BONUS_ACTION'
    use(combat, table, mid, 'Perfected — Glass Heart Refraction')
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    assert owner.resources['resource:core.qi'] == before.resources['resource:core.qi'] - 2
    assert owner.resources[pool('glass')] == 0
    assert owner.resource_maximums[pool('glass')] == 1
    assert held(owner, 'glass_refraction')
    assert not held(engine.state.actors[ALLY], 'glass_refraction')
    assert not available(engine)
    for _ in range(9):
        turn(table, mid, FOE); turn(table, mid, OWNER)
    assert held(reload(tmp_path, mid).state.actors[OWNER], 'glass_refraction')
    turn(table, mid, FOE); turn(table, mid, OWNER)
    assert not held(reload(tmp_path, mid).state.actors[OWNER], 'glass_refraction')
    declare(combat, table, mid)
    assert not available(reload(tmp_path, mid))  # Fresh scene cannot bypass once/rest.


def test_declaration_correction_staleness_and_other_turn(tmp_path):
    combat, table, mid = table_fixture(tmp_path, 'glass', current=0)
    turn(table, mid, FOE)
    declare(combat, table, mid)
    engine = reload(tmp_path, mid)
    assert not available(engine)  # No Bonus Action on the foe's turn.
    declare(combat, table, mid, clarity='No')
    turn(table, mid, OWNER)
    assert not available(reload(tmp_path, mid))
    with pytest.raises(TabletopError):
        table.record_source_input(mid, SOURCE, OWNER,
            {'scene': 'Major combat', 'clarity': 'Yes', 'reason': 'Actual scene'}, -1)
    with pytest.raises(TabletopError):
        declare(combat, table, mid, actor_id=ALLY)


def test_insufficient_cp_cannot_pay_state(tmp_path):
    from combat.canonical import canonical_sha256
    def poor(bundles):
        for r in bundles[0]['actor_template']['resources']:
            if r['resource_id'] == 'resource:core.qi':
                r['initial'] = 1
        bundles[0].pop('bundle_sha256', None)
        bundles[0]['bundle_sha256'] = canonical_sha256(bundles[0])
    combat, table, mid = table_fixture(tmp_path, 'glass', current=0, transform=poor)
    declare(combat, table, mid)
    engine = reload(tmp_path, mid)
    assert not available(engine)
    assert engine.state.actors[OWNER].resources['resource:core.qi'] == 1
    assert not held(engine.state.actors[OWNER], 'glass_refraction')
