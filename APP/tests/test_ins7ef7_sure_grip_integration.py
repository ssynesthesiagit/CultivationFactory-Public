"""Sure Grip must survive the canonical Athletics row used by merged lanes.

Exercise real table commits and cold reloads, rather than injecting a passive
into an engine. The metadata fixture reproduces the integration's native block
selection even when this file is run against the pre-fix branch.
"""
import pytest
import json
from pathlib import Path

from combat.typed_reactions import rules
from tests.athletics_action_support import add_action
from tests.auto8f1_table_support import (
    OWNER, FOE, fixture, candidate_id, reload_identical,
)

GRIP = 'TAL_ATHLETICS_SURE_GRIP'


def test_native_grip_metadata_selects_the_canonical_athletics_compiler():
    path = Path(__file__).resolve().parents[1] / 'combat/rules/feature_blocks.d/athletics-second-pass.json'
    spec = json.loads(path.read_text())['features'][GRIP]
    assert spec['block'] == 'athletics' and spec['kind'] == 'sure_grip'


@pytest.fixture
def canonical_grip(monkeypatch):
    features = rules()['features']
    monkeypatch.setitem(features, GRIP, {**features[GRIP], 'block': 'athletics'})


def game(tmp_path, owned):
    def prepare(bundles):
        for bundle in bundles:
            if bundle['actor_id'] != OWNER:
                bundle['actor_template']['saving_throws'] = {'STR': -60, 'DEX': -60}
                continue
            add_action(bundle, 'Become incapacitated', [
                {'type': 'condition', 'condition': 'incapacitated', 'applies_to': 'self'},
            ])
            for hazard in ('climb', 'prevent_falling', 'ordinary'):
                add_action(bundle, 'Athletics ' + hazard, [{
                    'type': 'contest_against',
                    'actor_check': {'ability': 'STR', 'skill': 'Athletics', 'hazards': [hazard]},
                    'target_check': {'kind': 'dc', 'basis': 'save_dc'},
                }])
                bundle['action_catalog'][-1].update(target_kind='HOSTILE_ENTITY', range_ft=5)
    return fixture(tmp_path, [GRIP] if owned else [], seed='INS7EF7-' + tmp_path.name,
                   bundle_transform=prepare)


def play(g, label):
    g['commit'](candidate_id(g['menu'](), label))
    reload_identical(g['combat'], g['match_id'], g['userdata'])


@pytest.mark.parametrize('owned', [True, False])
def test_canonical_grip_retains_grapple_after_table_incapacity_and_reload(tmp_path, canonical_grip, owned):
    g = game(tmp_path, owned)
    play(g, 'Grapple')
    def held():
        return any(c.condition_id == 'condition:typed.grappled' and c.source_actor_id == OWNER
                   for c in g['stored_engine']().state.actors[FOE].conditions.values())
    assert held()
    play(g, 'Become incapacitated')
    assert held() is owned


@pytest.mark.parametrize('owned', [True, False])
def test_canonical_grip_has_one_row_and_climbing_advantage_after_reload(tmp_path, canonical_grip, owned):
    from combat.roof_movement import profile
    g = game(tmp_path, owned)
    engine = g['stored_engine']()
    rows = [row for row in engine.typed_passive_rows[OWNER] if row.get('feature_id') == GRIP]
    assert len(rows) == int(owned)
    if owned:
        assert rows[0]['block'] == 'athletics' and rows[0]['kind'] == 'sure_grip'
    assert ('ADVANTAGE' in profile(engine, engine.state.actors[OWNER]).check_modes) is owned
    reload_identical(g['combat'], g['match_id'], g['userdata'])


@pytest.mark.parametrize('owned,hazard,mode', [
    (True, 'climb', 'ADVANTAGE'), (True, 'prevent_falling', 'ADVANTAGE'),
    (True, 'ordinary', 'NORMAL'), (False, 'climb', 'NORMAL'),
])
def test_canonical_grip_scopes_table_athletics_advantage(tmp_path, canonical_grip, owned, hazard, mode):
    g = game(tmp_path, owned)
    play(g, 'Athletics ' + hazard)
    rolls = [e for e in g['stored_engine']().events if e.event_type == 'CHECK_ROLLED' and e.actor_id == OWNER]
    assert rolls[-1].payload['actor']['mode'] == mode
