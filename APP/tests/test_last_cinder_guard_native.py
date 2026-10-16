"""Native table coverage for the complete Last Cinder Guard consumer.

Dynamic inputs: authority/Tianxia_Typed_Mechanics_Authority_R1.json,
authority/typed_mechanics/rules_text.json, combat/rules/feature_blocks.json,
combat/rules/feature_blocks.d, non_sphere_authority/authority/,
character_creation/authority/. No live model or owner data is read.
Enemy packets are deterministic sealed initial scenario actions with explicit
provenance. Resource generation always comes from paid, compiled Ashen Burial.
"""
import pytest

from combat.canonical import canonical_sha256
from combat.factory_compiler import compile_character
from combat.ext.foundation_combat import CINDER_GUARD, CINDER_POOL, CINDER_SOURCES
from non_sphere_authority.foundation_mechanics import resolve_initial_foundation_state, verified_foundation_records
from tests.h1_support import sheet
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, reload, turn

# Literal compiler inputs are declared for the safe-export dependency scanner.
SOURCE_INPUTS = ('authority/Tianxia_Typed_Mechanics_Authority_R1.json',
    'authority/typed_mechanics/rules_text.json', 'combat/rules/feature_blocks.json',
    'combat/rules/feature_blocks.d/last_cinder_guard.json',
    'non_sphere_authority/authority/Foundation_Runtime_Authority_v0_4C.json')
ASH = 'ash_born_remnant_core_v0_2B'
REACTION = 'reaction:typed.' + CINDER_GUARD


def setup(tmp_path, *, category=None, damage_type='FORCE', score=14, stage='Integrated',
          distance=5, packets=1, friendly=False, automatic=False, extra_talents=(), save=False,
          save_category=None, foe_sheet=None):
    doc = sheet(['ASH_TAL_ASHEN_BURIAL', *extra_talents], score=score, cl=15, name='Cinder Keeper')
    doc['foundation'] = resolve_initial_foundation_state(verified_foundation_records()[ASH],
        ['tianxia.path.qi_cultivation'], stage=stage)
    owner = compile_character(doc, actor_id=OWNER, reaction_plan={'ask': not automatic})

    def enemy(bundles):
        source_actor = ALLY if friendly else FOE
        bundle = bundles[1] if friendly else bundles[2]
        source = 'action:test.cinder.pressure'
        effects = [{'type': 'damage', 'applies_to': 'target', 'flat': 17,
                    'damage_types': [damage_type],
                    **({'source_flags': [category]} if category else {})} for _ in range(packets)]
        if save:
            effects = [{'type': 'save', 'ability': 'CON', 'applies_to': 'target',
                        **({'save_categories': [save_category]} if save_category else {}),
                        'on_fail': effects[:1], 'on_success': [{'type': 'half_damage'}]}, *effects[1:]]
        bundle['action_catalog'].append({'source_definition_id': source, 'display_name': 'Incoming pressure',
            'owner_id': source_actor, 'economy': 'ACTION', 'resolution_kind': 'TYPED',
            'target_kind': 'ANY_CREATURE', 'range_ft': 120, 'costs': [],
            'parameters': {'typed': {'source': 'scenario.explicit_pressure',
                                    'numbers': {'save_dc': 1}, 'riders': [], 'effects': effects}}})
        bundle['actor_template']['action_ids'].append(source)
        bundle.pop('bundle_sha256', None)
        bundle['bundle_sha256'] = canonical_sha256(bundle)

    return fixture(tmp_path, [], owner_bundle=owner, bundle_transform=enemy, named=True,
        foe_sheet=foe_sheet,
        ally_position={'x': 3, 'y': 6 + distance // 5}, foe_position={'x': 6, 'y': 6},
        modes={OWNER: 'LOCAL_AUTO' if automatic else 'MANUAL', ALLY: 'MANUAL', FOE: 'MANUAL'}, seed='CINDER-NATIVE')


def earn(combat, table, mid, tmp_path):
    before = reload(tmp_path, mid)
    assert before.state.actors[OWNER].resources[CINDER_POOL] == 0
    technique = candidate(combat, mid, 'Ashen Burial', target=FOE)
    settle(table, mid, technique.candidate_id)
    after = reload(tmp_path, mid)
    assert after.state.actors[OWNER].resources[CINDER_POOL] == 1
    grants = [e for e in after.events if e.event_type == 'RESOURCE_GAINED'
              and e.actor_id == OWNER and e.payload.get('resource_id') == CINDER_POOL]
    assert len(grants) == 1
    assert grants[0].source_definition_id.endswith('generate_remnant_cinder')
    assert any(e.event_type == 'RESOURCE_SPENT' and e.actor_id == OWNER
               and e.payload.get('resource_id') == 'resource:core.qi' and e.sequence < grants[0].sequence
               for e in after.events)
    assert not any(e.event_type == 'REACTION_RESOLVED' and e.source_definition_id == REACTION
                   for e in after.events)
    return after


@pytest.mark.parametrize('category,kind', [(c, 'FORCE') for c in sorted(CINDER_SOURCES)] + [(None, 'NECROTIC')])
@pytest.mark.parametrize('target', [OWNER, ALLY])
def test_each_printed_source_adds_pb_to_native_earlier_event_guard(tmp_path, category, kind, target):
    combat, table, mid = setup(tmp_path, category=category, damage_type=kind)
    earn(combat, table, mid, tmp_path)
    turn(table, mid, FOE)
    before = reload(tmp_path, mid)
    hp = before.state.actors[target].current_hp
    prompts = settle(table, mid, candidate(combat, mid, 'Incoming pressure', target=target).candidate_id,
                     picks={REACTION: 'first'})
    assert any(p['context']['reaction_source_id'] == REACTION for p in prompts)
    after = reload(tmp_path, mid)
    assert after.state.actors[target].current_hp == hp - 7  # 17 - (4 + 2 + 4)
    assert after.state.actors[OWNER].resources[CINDER_POOL] == 0
    assert not after.state.actors[OWNER].reaction_available
    resolved = [e for e in after.events if e.event_type == 'REACTION_RESOLVED'
                and e.source_definition_id == REACTION]
    assert len(resolved) == 1


@pytest.mark.parametrize('category,kind', [(None, 'FORCE'), (None, 'FIRE'), ('present_tense', 'PSYCHIC'),
                                          ('non_remnant_control', 'PSYCHIC'), ('unrelated', 'FORCE')])
def test_ordinary_damage_gets_only_base(tmp_path, category, kind):
    combat, table, mid = setup(tmp_path, category=category, damage_type=kind)
    earn(combat, table, mid, tmp_path)
    turn(table, mid, FOE)
    hp = reload(tmp_path, mid).state.actors[ALLY].current_hp
    settle(table, mid, candidate(combat, mid, 'Incoming pressure', target=ALLY).candidate_id,
           picks={REACTION: 'first'})
    assert reload(tmp_path, mid).state.actors[ALLY].current_hp == hp - 11


@pytest.mark.parametrize('category,expected', [(None, 3), ('ash', 7)])
def test_negative_path_key_is_signed_in_base_sum(tmp_path, category, expected):
    combat, table, mid = setup(tmp_path, category=category, score=8)
    earn(combat, table, mid, tmp_path)
    turn(table, mid, FOE)
    hp = reload(tmp_path, mid).state.actors[ALLY].current_hp
    settle(table, mid, candidate(combat, mid, 'Incoming pressure', target=ALLY).candidate_id,
           picks={REACTION: 'first'})
    assert reload(tmp_path, mid).state.actors[ALLY].current_hp == hp - (17 - expected)


@pytest.mark.parametrize('distance,used', [(30, True), (35, False)])
def test_range_is_to_protected_ally(tmp_path, distance, used):
    combat, table, mid = setup(tmp_path, category='ash', distance=distance)
    earn(combat, table, mid, tmp_path)
    turn(table, mid, FOE)
    prompts = settle(table, mid, candidate(combat, mid, 'Incoming pressure', target=ALLY).candidate_id,
                     picks={REACTION: 'first'})
    assert any(p['context']['reaction_source_id'] == REACTION for p in prompts) is used
    assert reload(tmp_path, mid).state.actors[OWNER].resources[CINDER_POOL] == (0 if used else 1)


def test_decline_preserves_cinder_and_reaction(tmp_path):
    combat, table, mid = setup(tmp_path, category='ash')
    earn(combat, table, mid, tmp_path)
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Incoming pressure', target=ALLY).candidate_id)
    owner = reload(tmp_path, mid).state.actors[OWNER]
    assert owner.resources[CINDER_POOL] == 1 and owner.reaction_available


def test_no_resource_no_guard(tmp_path):
    combat, table, mid = setup(tmp_path, category='ash')
    turn(table, mid, FOE)
    prompts = settle(table, mid, candidate(combat, mid, 'Incoming pressure', target=ALLY).candidate_id,
                     picks={REACTION: 'first'})
    assert not any(p['context']['reaction_source_id'] == REACTION for p in prompts)
    assert reload(tmp_path, mid).state.actors[OWNER].resources[CINDER_POOL] == 0


def test_native_expiry_at_end_of_next_turn(tmp_path):
    combat, table, mid = setup(tmp_path)
    earn(combat, table, mid, tmp_path)
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    assert reload(tmp_path, mid).state.actors[OWNER].resources[CINDER_POOL] == 1
    turn(table, mid, OWNER)
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    owner = reload(tmp_path, mid).state.actors[OWNER]
    assert owner.resources[CINDER_POOL] == 0


def test_multiple_packets_spend_one_cinder_and_one_reaction(tmp_path):
    combat, table, mid = setup(tmp_path, category='ash', packets=2)
    earn(combat, table, mid, tmp_path)
    turn(table, mid, FOE)
    hp = reload(tmp_path, mid).state.actors[ALLY].current_hp
    settle(table, mid, candidate(combat, mid, 'Incoming pressure', target=ALLY).candidate_id,
           picks={REACTION: 'first'})
    after = reload(tmp_path, mid)
    assert after.state.actors[ALLY].current_hp == hp - 24
    assert len([e for e in after.events if e.event_type == 'REACTION_RESOLVED'
                and e.source_definition_id == REACTION]) == 1


def test_automatic_off_turn_guard_uses_same_payment(tmp_path):
    combat, table, mid = setup(tmp_path, category='ash', automatic=True)
    earn(combat, table, mid, tmp_path)
    turn(table, mid, FOE)
    hp = reload(tmp_path, mid).state.actors[ALLY].current_hp
    prompts = settle(table, mid, candidate(combat, mid, 'Incoming pressure', target=ALLY).candidate_id)
    assert not any(p['context']['reaction_source_id'] == REACTION for p in prompts)
    after = reload(tmp_path, mid)
    assert after.state.actors[ALLY].current_hp == hp - 7
    assert after.state.actors[OWNER].resources[CINDER_POOL] == 0


def test_successful_save_keeps_explicit_source_classification(tmp_path):
    combat, table, mid = setup(tmp_path, category='ash', save=True)
    earn(combat, table, mid, tmp_path)
    turn(table, mid, FOE)
    hp = reload(tmp_path, mid).state.actors[ALLY].current_hp
    settle(table, mid, candidate(combat, mid, 'Incoming pressure', target=ALLY).candidate_id,
           picks={REACTION: 'first'})
    assert reload(tmp_path, mid).state.actors[ALLY].current_hp == hp  # 17 // 2 reduced by 10


def test_reaction_shortage_preserves_held_cinder(tmp_path):
    ward = 'reaction:typed.tianxia.talent.ash.ash_ward'
    combat, table, mid = setup(tmp_path, category='ash', packets=2,
                              extra_talents=['tianxia.talent.ash.ash_ward'])
    earn(combat, table, mid, tmp_path)
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Incoming pressure', target=ALLY).candidate_id,
           picks={ward: 'first'})
    after = reload(tmp_path, mid)
    assert not after.state.actors[OWNER].reaction_available
    assert after.state.actors[OWNER].resources[CINDER_POOL] == 1
    assert not any(e.event_type == 'REACTION_RESOLVED' and e.source_definition_id == REACTION for e in after.events)


def test_friendly_damage_cannot_spend_guard(tmp_path):
    combat, table, mid = setup(tmp_path, category='ash', friendly=True)
    earn(combat, table, mid, tmp_path)
    turn(table, mid, ALLY)
    hp = reload(tmp_path, mid).state.actors[OWNER].current_hp
    prompts = settle(table, mid, candidate(combat, mid, 'Incoming pressure', target=OWNER).candidate_id,
                     picks={REACTION: 'first'})
    assert not any(p['context']['reaction_source_id'] == REACTION for p in prompts)
    after = reload(tmp_path, mid)
    assert after.state.actors[OWNER].current_hp == hp - 17
    assert after.state.actors[OWNER].resources[CINDER_POOL] == 1
    assert after.state.actors[OWNER].reaction_available


def test_native_save_cinder_is_unavailable_to_later_packet_of_same_event(tmp_path):
    combat, table, mid = setup(tmp_path, category='ash', save=True, packets=2,
                              save_category='remnant_possession')
    turn(table, mid, FOE)
    hp = reload(tmp_path, mid).state.actors[OWNER].current_hp
    prompts = settle(table, mid, candidate(combat, mid, 'Incoming pressure', target=OWNER).candidate_id,
                     picks={REACTION: 'first'})
    after = reload(tmp_path, mid)
    assert after.state.actors[OWNER].current_hp == hp - 25
    assert after.state.actors[OWNER].resources[CINDER_POOL] == 1
    assert after.state.actors[OWNER].reaction_available
    assert not any(p['context']['reaction_source_id'] == REACTION for p in prompts)
    grants = [e for e in after.events if e.event_type == 'RESOURCE_GAINED'
              and e.payload.get('resource_id') == CINDER_POOL]
    damages = [e for e in after.events if e.event_type == 'DAMAGE_COMMITTED' and OWNER in e.target_ids]
    assert len(grants) == 1 and damages[0].sequence < grants[0].sequence < damages[1].sequence


@pytest.mark.parametrize('target', [OWNER, ALLY])
def test_actual_published_cinder_brand_source_gets_ash_bonus_without_scenario_flags(tmp_path, target):
    foe = sheet(['ASH_BASE_CINDER_BRAND'], cl=15, name='Ash Invader')
    foe['ability_scores_and_statistics']['technique_attack_bonus'] = 100
    combat, table, mid = setup(tmp_path, foe_sheet=foe)
    earn(combat, table, mid, tmp_path)
    turn(table, mid, FOE)
    before = reload(tmp_path, mid)
    hp = before.state.actors[target].current_hp
    settle(table, mid, candidate(combat, mid, 'Cinder Brand', target=target).candidate_id,
           picks={REACTION: 'first'})
    after = reload(tmp_path, mid)
    roll = next(e for e in after.events if e.event_type == 'DAMAGE_ROLLED' and e.actor_id == FOE)
    assert after.state.actors[target].current_hp == hp - max(0, roll.payload['total'] - 10)
    assert after.state.actors[OWNER].resources[CINDER_POOL] == 0
    assert not after.state.actors[OWNER].reaction_available
