"""Protection attribution after a native forced save outcome, through the table."""

import json
from pathlib import Path

import pytest

from combat.ext.inner_soul_gate import CROWN, RESONANCE
from combat.factory_compiler import compile_character
from tests.h1_support import sheet
from tests.test_a2_foundations3 import pool
from tests.test_spirit_dew_maintenance import REFRAIN
from tests.test_spirit_dew_protection import AEGIS
from tests.test_spirit_dew_reduction import OWNER_ROW
from tests.test_spirit_dew_review_boundaries import _supporter
from tests.worker2_support import OWNER, ALLY, FOE, candidate, fixture, reload, settle, turn


@pytest.mark.parametrize('numeric_failure,use_rescue', [
    pytest.param(True, True, id='independent-rescue-earns-no-dew'),
    pytest.param(True, False, id='declined-rescue-still-fails'),
    pytest.param(False, False, id='numeric-success-retains-support-credit'),
])
def test_crown_opening_preserves_only_successful_protection_credit(tmp_path, numeric_failure, use_rescue):
    # These ownership contracts are runtime directory inputs. Check the actual
    # fixture data explicitly so a partial test snapshot cannot omit them.
    root = Path(__file__).resolve().parents[1]
    for relative, feature in [
        ('combat/rules/feature_blocks.d/foundations3.json', OWNER_ROW),
        ('combat/rules/feature_blocks.d/riders_c8.json', CROWN),
    ]:
        assert feature in json.loads((root / relative).read_text())['features']

    def delivery(bundles):
        bundles[1] = compile_character(sheet([CROWN], cl=18, primary='Resonance', name='Tobin'),
                                       actor_id=ALLY, reaction_plan={'ask': True})
        # Even Advantage cannot change these numeric outcomes at DC 99.
        bundles[1]['actor_template']['saving_throws']['WIS'] = -100 if numeric_failure else 100
        bundles[2] = compile_character(sheet([REFRAIN], cl=18, dc=99, name='Mara'),
                                       actor_id=FOE, reaction_plan={'ask': True})

    combat, table, mid = fixture(tmp_path, [], cl=18, owner_bundle=_supporter(AEGIS),
        bundle_transform=delivery, seed='DEW-NATIVE-CROWN-RESCUE', named=True)
    settle(table, mid, candidate(combat, mid, 'Radiant Aegis of the Heart', target=ALLY).candidate_id,
           choices={})
    turn(table, mid, ALLY)
    settle(table, mid, candidate(combat, mid, 'Crown Opening').candidate_id, choices={})
    opened = reload(tmp_path, mid)
    before = opened.state.actors[ALLY].resources[RESONANCE]
    assert any(c.condition_id == 'condition:typed.gate_opening' and c.data['gate'] == 'crown'
               for c in opened.state.actors[ALLY].conditions.values())
    assert any(c.source_actor_id == OWNER and AEGIS in c.source_definition_id
               for c in opened.state.actors[ALLY].conditions.values())
    assert opened.state.actors[OWNER].resources.get(pool('spirit'), 0) == 0
    turn(table, mid, FOE)
    rescue_source = 'reaction:typed.' + CROWN
    prompts = settle(table, mid,
        candidate(combat, mid, 'Soul-Stirring Refrain: Fear (any creature)', target=ALLY).candidate_id,
        picks={'choice:willing.consent': ['refuse'],
               rescue_source: 'USE' if use_rescue else None})
    rescues = [p for p in prompts if p['context']['reaction_source_id'] == rescue_source]
    assert bool(rescues) is numeric_failure
    if rescues:
        assert rescues[0]['context']['reactor_id'] == ALLY
        assert 'Crown Opening' in str(rescues[0]) and 'Tobin' in str(rescues[0])
    engine = reload(tmp_path, mid)  # A fresh service also checks mechanical replay.
    saved = next(e for e in reversed(engine.events) if e.event_type == 'SAVE_ROLLED'
                 and REFRAIN in e.source_definition_id and e.actor_id == ALLY)
    assert saved.payload['mode'] == 'ADVANTAGE'
    assert saved.payload['success'] is (use_rescue or not numeric_failure)
    if use_rescue:
        assert saved.payload['total_before_outcome'] < saved.payload['dc']
        assert saved.payload['total'] >= saved.payload['dc']
        assert saved.payload['forced_outcome'] == 'success'
        assert saved.payload['outcome_source_id'] == CROWN
    else:
        assert 'forced_outcome' not in saved.payload
        assert (saved.payload['total'] < saved.payload['dc']) is numeric_failure
    assert engine.state.actors[ALLY].resources[RESONANCE] == before - (2 if use_rescue else 0)
    assert any(c.condition_id == 'condition:typed.frightened'
               for c in engine.state.actors[ALLY].conditions.values()) is (numeric_failure and not use_rescue)
    assert not getattr(engine, '_typed_roll_outcome', {})
    assert engine.state.actors[OWNER].resources.get(pool('spirit'), 0) == int(not numeric_failure)
