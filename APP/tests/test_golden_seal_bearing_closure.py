"""Bearing's paid table lifecycle and consequence-scoped save regression.

The save probes isolate Bearing from the independently owned Vessel passive;
they are not proof of perceptible authority or legitimacy adjudication.
"""
import pytest

from combat.canonical import canonical_sha256
from combat.ext import foundation_combat as foundation
from combat.factory_compiler import compile_character
from tests.h1_support import sheet
from tests.worker2_support import OWNER, FOE, candidate, fixture, reload, settle, turn

# Literal dynamic compiler/rules inputs for the safe export's resource closure.
RUNTIME_INPUTS = (
    'APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json',
    'APP/combat/rules/feature_blocks.json',
    'APP/combat/rules/feature_blocks.d/a2_foundations_2.json',
    'APP/non_sphere_authority/authority/Foundation_Runtime_Authority_v0_4C.json',
)
BEARING = foundation.feature('mandate', 'golden_seal_bearing')
VESSEL = foundation.feature('mandate', 'golden_mandate_vessel')
SEAL = foundation.pool('mandate')
TALISMAN = 'tianxia.talent.talismans.binding_talisman'


def setup(tmp_path, *, named=(), score=14, stage='Awakened', isolate=False, ask=True, friendly=False):
    document = sheet([TALISMAN, BEARING], cl=15, dc=100, score=score,
                     foundation={'foundation_id': foundation.GROUPS['mandate'][0], 'stage': stage,
                                 'resource': {'name': 'Edict Seal', 'resource_id': 'fixture:edict_seal',
                                              'maximum': 1, 'current': 0}})
    # No starting Seal: obtain it by resolving the actual compiled Binding
    # Talisman against a hostile creature before selecting Bearing.
    owner = compile_character(document, actor_id=OWNER, reaction_plan={'ask': ask})

    def probes(bundles):
        if isolate:
            bundles[0]['typed_passives'] = [r for r in bundles[0]['typed_passives']
                                          if r.get('feature_id') != VESSEL]
        foe = bundles[2]
        source = 'action:test.bearing_save_probe'
        foe['action_catalog'].append({
            'source_definition_id': source, 'display_name': 'Saving throw probe',
            'owner_id': FOE, 'economy': 'ACTION', 'resolution_kind': 'TYPED',
            'target_kind': 'ANY_CREATURE', 'range_ft': 60, 'costs': [],
            'parameters': {'typed': {'source': source, 'numbers': {'save_dc': 15},
                'effects': [{'type': 'save', 'ability': 'wis', 'applies_to': 'target',
                             'save_categories': list(named), 'on_fail': [], 'on_success': []}],
                'duration': {'kind': 'instant'}, 'riders': []}}})
        foe['actor_template']['action_ids'].append(source)
        for bundle in bundles:
            bundle.pop('bundle_sha256', None)
            bundle['bundle_sha256'] = canonical_sha256(bundle)

    return fixture(tmp_path, [], owner_bundle=owner, bundle_transform=probes, ask=ask,
                   extra_foes=1 if friendly else 0,
                   team_overrides={FOE: 'team:factory'} if friendly else None)


def use(combat, table, mid, name, target=None):
    settle(table, mid, candidate(combat, mid, name, target=target).candidate_id, choices={})


def activate(combat, table, mid):
    before = combat._load_session(mid).engine
    assert before.state.actors[OWNER].resources[SEAL] == 0
    assert not [c for c in before.legal_candidates()
                if before.action_catalog[c.source_definition_id].display_name == 'Golden Seal Bearing']
    target = next(a.entity_id for a in before.state.actors.values()
                  if a.team_id != before.state.actors[OWNER].team_id)
    use(combat, table, mid, 'Binding Talisman', target)
    generated = combat._load_session(mid).engine
    assert generated.state.actors[OWNER].resources[SEAL] == 1
    use(combat, table, mid, 'Golden Seal Bearing')


@pytest.mark.parametrize('score,stage,expected', [(14, 'Awakened', 6), (6, 'Awakened', 2),
                                                 (6, 'Refined', 6)])
@pytest.mark.parametrize('ask', [True, False])
def test_native_prior_seal_payment_signed_hp_and_owner_start(tmp_path, score, stage, expected, ask):
    combat, table, mid = setup(tmp_path, score=score, stage=stage, ask=ask)
    activate(combat, table, mid)
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    assert owner.temporary_hp == expected
    assert owner.resources[SEAL] == 0
    assert not owner.bonus_action_available
    bearing = foundation.held(owner, 'golden_bearing')
    assert bearing and 'Frightened' in bearing.data['label'] and 'Charmed' in bearing.data['label']
    gain = next(e for e in engine.events if e.event_type == 'RESOURCE_GAINED'
                and e.actor_id == OWNER and e.payload.get('resource_id') == SEAL)
    spent = next(e for e in engine.events if e.event_type == 'RESOURCE_SPENT'
                 and e.actor_id == OWNER and e.payload.get('resource_id') == SEAL)
    assert gain.sequence < spent.sequence
    assert any(e.event_type == 'SAVE_ROLLED' and e.actor_id == FOE
               and not e.payload.get('success') and e.sequence < gain.sequence for e in engine.events)
    turn(table, mid, FOE)
    assert foundation.held(reload(tmp_path, mid).state.actors[OWNER], 'golden_bearing')
    turn(table, mid, OWNER)
    assert foundation.held(reload(tmp_path, mid).state.actors[OWNER], 'golden_bearing') is None


@pytest.mark.parametrize('named,expected', [
    (['frightened'], 'ADVANTAGE'), (['charmed'], 'ADVANTAGE'),
    (['silenced', 'hostile_command'], 'ADVANTAGE'),
    (['spiritually_shamed', 'false_authority'], 'ADVANTAGE'),
    (['silenced_by_hostile_command'], 'ADVANTAGE'),
    (['spiritually_shamed_by_false_authority'], 'ADVANTAGE'),
    (['silenced'], 'NORMAL'), (['physically_silenced'], 'NORMAL'),
    (['hostile_command'], 'NORMAL'), (['false_authority'], 'NORMAL'),
    (['compelled'], 'NORMAL'), (['spiritually_shamed'], 'NORMAL'),
])
def test_bearing_save_category_matrix_through_table_reload(tmp_path, named, expected):
    combat, table, mid = setup(tmp_path, named=named, isolate=True)
    activate(combat, table, mid)
    turn(table, mid, FOE)
    use(combat, table, mid, 'Saving throw probe', OWNER)
    engine = reload(tmp_path, mid)
    saves = [e for e in engine.events if e.event_type == 'SAVE_ROLLED' and e.actor_id == OWNER]
    assert saves and saves[-1].payload['mode'] == expected
    assert foundation.held(engine.state.actors[OWNER], 'golden_bearing')


def test_bearing_fear_protection_does_not_require_a_hostile_caster(tmp_path):
    combat, table, mid = setup(tmp_path, named=['frightened'], isolate=True, friendly=True)
    activate(combat, table, mid)
    turn(table, mid, FOE)
    use(combat, table, mid, 'Saving throw probe', OWNER)
    engine = reload(tmp_path, mid)
    saves = [e for e in engine.events if e.event_type == 'SAVE_ROLLED' and e.actor_id == OWNER]
    assert saves and saves[-1].payload['mode'] == 'ADVANTAGE'


@pytest.mark.parametrize('condition', ['condition:typed.silenced', 'condition:typed.restrained'])
def test_bearing_is_withheld_while_authority_is_not_perceptible(tmp_path, condition):
    """Printed trigger 'while your authority can be made perceptible' and Limit 'does not override physical
    silence, restraints': the action is absent from the legal list, the Seal is kept, and the owner's other
    legal options are unaffected."""
    combat, table, mid = setup(tmp_path)
    before = combat._load_session(mid).engine
    target = next(a.entity_id for a in before.state.actors.values()
                  if a.team_id != before.state.actors[OWNER].team_id)
    use(combat, table, mid, 'Binding Talisman', target)
    engine = combat._load_session(mid).engine
    assert engine.state.actors[OWNER].resources[SEAL] == 1

    def bearing_offers(eng):
        return [c for c in eng.legal_candidates() if c.actor_id == OWNER
                and eng.action_catalog[c.source_definition_id].display_name == 'Golden Seal Bearing']

    offered = {c.candidate_id for c in bearing_offers(engine)}
    assert offered
    owner_options = {c.candidate_id for c in engine.legal_candidates() if c.actor_id == OWNER}
    foundation.timed_condition(engine, engine.state.actors[OWNER], condition, 'test:perceptibility', FOE,
                               'UNTIL_REMOVED', {'label': 'test'})
    assert not bearing_offers(engine)
    assert engine.state.actors[OWNER].resources[SEAL] == 1
    assert {c.candidate_id for c in engine.legal_candidates() if c.actor_id == OWNER} == owner_options - offered
