"""SOL90: explicit magic classification, real table commits, and legacy opt-out.

Fixture suppressors opt into magical_only to exercise the general seam without
inventing a magical-only restriction for Lattice Unraveling's printed rules.
"""
import copy
import json
import subprocess
import sys
from types import SimpleNamespace

import pytest

from combat import zone_sources
from combat.canonical import canonical_sha256
from combat.ext import area_suppression, end_effect
from combat.gate5_service import CombatService
from tests.h1_support import ROOT, mechanics
from tests.r1i_service_support import OWNER, FOE, fixture, candidate
from tests.test_carry import KIT

LATTICE = 'TAL_UNMAKING_LATTICE_UNRAVELING'
WALL = 'TAL_MAGMA_LAVA_WALL'
NEEDLES = ['TAL_FENCING_EMPTY_HAND_OPEN_MERIDIAN', 'TAL_FENCING_SHADOW_STRIKE', 'TAL_FENCING_SOUL_STRIKE']


def fresh(tmp_path, mid):
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    assert session.verify()['status'] == 'PASS'
    assert session.mechanical.replay()['status'] == 'PASS'
    return session.engine


@pytest.mark.parametrize('classification', ['magical', 'mundane', 'legacy'])
def test_magical_area_eligibility_and_suppression_survive_table_reload(tmp_path, classification):
    def setup(bundles):
        for bundle in bundles:
            for action in bundle['action_catalog']:
                typed = action['parameters'].get('typed') or {}
                for row in typed.get('effects') or []:
                    if row.get('type') == 'suppress_area':
                        row['magical_only'] = True
                        row.pop('check', None)  # eligibility and expiry, independent of check luck
                if typed.get('source') == WALL:
                    profile = typed['zone_spec']['source_profile']
                    if classification == 'mundane':
                        profile['mundane'] = 1
                    elif classification == 'legacy':
                        profile.pop('mundane', None)
            bundle.pop('bundle_sha256', None)
            bundle['bundle_sha256'] = canonical_sha256(bundle)

    combat, table, mid, send, commit = fixture(tmp_path, [LATTICE], foe_talents=[WALL],
        positions={OWNER: {'x': 3, 'y': 6}, FOE: {'x': 14, 'y': 6},
                   'actor:factory.r1i-second': {'x': 16, 'y': 10}}, bundle_transform=setup)

    def turn(actor):
        while table.state(mid)['menu']['actor_id'] != actor:
            commit(table.state(mid)['menu']['end_turn'])

    def cell_candidate(name, at):
        return next(c for c in combat._load_session(mid).engine.legal_candidates()
                    if c.display_name.startswith(name) and c.destination is not None
                    and (c.destination.x, c.destination.y) == at)

    turn(FOE)
    commit(cell_candidate('Lava Wall', (8, 5)).candidate_id)
    turn(OWNER)
    engine = fresh(tmp_path, mid)
    wall = next(z for z in engine.state.zones.values() if z.owner_id == FOE)
    assert area_suppression.magical(wall) is {'magical': True, 'mundane': False, 'legacy': None}[classification]
    original = wall.model_dump(mode='json')
    action = next(a for a in engine.action_catalog.values()
                  if a.owner_id == OWNER and a.parameters.get('typed', {}).get('source') == LATTICE)
    probe = SimpleNamespace(destination=wall.affected_cells[0])
    assert area_suppression.only_where_something_is(engine, engine.state.actors[OWNER], probe, action) is (classification == 'magical')
    assert area_suppression.ai_only_against_foes(engine, engine.state.actors[OWNER], probe, action) is (classification == 'magical')
    available = [c for c in engine.legal_candidates() if c.display_name.startswith('Lattice Unraveling')]
    if classification != 'magical':
        assert not available
        assert area_suppression.areas_at(engine, wall.affected_cells[0])
        assert not area_suppression.areas_at(engine, wall.affected_cells[0], magical_only=True)
        return
    chosen = available[0]
    commit(chosen.candidate_id)
    engine = fresh(tmp_path, mid)
    suppressed = engine.state.zones[wall.zone_id]
    assert not suppressed.affected_cells and area_suppression.suppressed(suppressed)
    assert suppressed.trigger_profile['source_profile']['mundane'] == 0
    assert type(suppressed.trigger_profile['source_profile']['mundane']) is int
    commit(table.state(mid)['menu']['end_turn'])
    turn(OWNER)
    restored = fresh(tmp_path, mid).state.zones[wall.zone_id]
    assert restored.model_dump(mode='json') == original


@pytest.mark.parametrize('ability', NEEDLES)
def test_printed_magical_exploit_is_classified_after_actual_hit_commit_and_reload(tmp_path, ability):
    combat, table, mid, send, commit = fixture(tmp_path,
        ['TAL_FENCING_FEINT', 'TAL_FENCING_EXPERT_FEINT', ability],
        owner_kit={'starting_kit': KIT}, foe_ac=1, foe_score=1, seed='SOL90-'+ability)
    label = mechanics()[ability]['name']
    commit(candidate(table, mid, 'Exploit: '+label))
    commit(candidate(table, mid, 'Feint (Bonus Action)', FOE))
    commit(candidate(table, mid, 'Bi Shou (Dagger) attack', FOE))
    engine = fresh(tmp_path, mid)
    holder = engine.state.actors[FOE]
    source = 'passive:'+ability
    items = [x for x in [*holder.conditions.values(), *holder.modifiers.values()]
             if x.source_definition_id == source]
    assert items, 'the real Exploit must land before classification is tested'
    assert area_suppression.effect_mundane(engine, source, OWNER) is False
    names = [c.condition_id.removeprefix('condition:typed.') for c in holder.conditions.values()
             if c.source_definition_id == source]
    fields = [m.target_field for m in holder.modifiers.values() if m.source_definition_id == source]
    row = {'conditions': names, 'modifiers': fields, 'select': 'any', 'magical_only': True}
    assert end_effect.found(engine, holder, row)
    # A sealed legacy option has no flag, so a magic-only suppressor cannot assume it is magical.
    legacy = copy.deepcopy(engine.typed_passive_rows[OWNER])
    for entry in legacy:
        for option in entry.get('options') or []:
            if option.get('id') == ability:
                for effect in option['effects']:
                    effect.pop('mundane', None)
    engine.typed_passive_rows[OWNER] = legacy
    assert area_suppression.effect_mundane(engine, source, OWNER) is None
    assert not end_effect.found(engine, holder, row)
    assert end_effect.found(engine, holder, {**row, 'magical_only': False})


@pytest.mark.parametrize('rows,expected', [
    ([{'type': 'zone', 'mundane': False}], True),
    ([{'type': 'zone', 'mundane': True}], False),
    ([{'type': 'zone'}], None),
    ([{'type': 'zone', 'mundane': False}, {'type': 'zone', 'mundane': True}], None),
    ([{'type': 'zone', 'mundane': False}, {'type': 'zone'}], None),
])
def test_zone_magic_is_explicit_and_unanimous_never_inferred_from_fire_flavour(rows, expected):
    typed = {'sphere': 'tianxia.sphere.fire', 'effects': rows}
    profile = zone_sources.compile_profile(typed, {}, {})
    zone = SimpleNamespace(trigger_profile={'source_profile': profile, 'visual': {'material': 'fire'}})
    assert area_suppression.magical(zone) is expected
    if expected is None:
        assert 'mundane' not in profile


def test_three_gm_classification_riders_are_replaced_by_explicit_typed_flags():
    for ability in NEEDLES:
        row = mechanics()[ability]
        assert all(effect['mundane'] is False for effect in row['effects'])
        assert not any('for the GM' in rider for rider in row['riders'])


def test_nested_classification_can_override_parent_and_action_defaults():
    assert zone_sources.mundane_rows([{'type': 'save', 'on_fail': [{'type': 'condition'}]}], False) is False
    assert zone_sources.mundane_rows([{'type': 'save', 'mundane': False,
                                      'on_fail': [{'type': 'condition', 'mundane': True}]}]) is None
    assert zone_sources.mundane_rows([{'type': 'condition', 'mundane': 'false'}]) is None


def test_stock_saved_ai_continuation_matches_base_commit_byte_for_byte():
    """Compare 12 stock decisions/events/rolls/state from the retained prior save.

    A subprocess imports a coherent round 24 combat/authority revision from Git
    objects; it does not patch engine functions, edit files or copy a checkout.
    """
    code = r'''
import hashlib, json, pathlib, sys
from tests.git_source_overlay import load_git_sources
if sys.argv[1] == 'base':
    load_git_sources(pathlib.Path.cwd().parent, 'b221edf6')
from tests.test_hunt32_inert_replay import _capture
data = _capture()
print(json.dumps({'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}))
'''
    captures = [json.loads(subprocess.check_output([sys.executable, '-c', code, version], cwd=ROOT))
                for version in ('base', 'current')]
    assert captures[0] == captures[1]
