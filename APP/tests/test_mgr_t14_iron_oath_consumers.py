"""Whole-row native table/reload acceptance for the Iron Oath consumers."""
import json
import pytest
from combat.ext import foundation_combat as f
from combat import protected_subjects as subjects
from combat.ext.iron_oath_consumers import BOUNDARY, SCAR, FORGING, SCAR_BAR
from combat.tabletop_service import TabletopError
from tests.test_mgr_t14_iron_oath_3 import oath_table, use
from tests.worker2_support import OWNER, ALLY, FOE, turn, reload, candidate, settle
from tests.iron_oath_support import duty
from tests.h1_support import ROOT
from tests.test_mgr_t14_iron_oath_producer import native_oath_document
from functools import lru_cache
from canonical_catalog.service import CanonicalCatalogAuthorityService

# A forged technique's Primary Sphere Effect must deliver a payoff in its one
# initial resolution (forge_design.POLICY). Bodyguard is a Rescue Talent that
# only improves Interpose, so the Forge rejects it as a primary; Guardian's
# Reprisal is an owned Guardian talent whose burst form pays off.
GUARDIAN_FORGE_TALENT = 'TAL_GUARDIAN_GUARDIAN_S_REPRISAL'


@lru_cache(maxsize=1)
def project_catalog():
    return CanonicalCatalogAuthorityService(ROOT)


def activate_boundary(tmp_path, **kwargs):
    combat, table, mid = oath_table(tmp_path, stage='Perfected', **kwargs)
    turn(table, mid, FOE)
    use(combat, table, mid, 'Pressure hit', OWNER)
    turn(table, mid, OWNER)
    prompts = use(combat, table, mid, 'Iron Oath Boundary', choices={
        f.CHOICE + 'iron_boundary_allies': [ALLY]})
    return combat, table, mid, prompts


def test_boundary_native_activation_is_available(tmp_path):
    combat, table, mid, prompts = activate_boundary(tmp_path)
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[OWNER]
    assert any(c.condition_id.endswith('iron_oath_boundary') for c in actor.conditions.values())
    assert actor.resources[f.pool('oath')] == 0
    assert engine.state.actors[ALLY].temporary_hp == 4
    assert actor.temporary_hp == 0
    paid = [e for e in engine.events if e.event_type == 'RESOURCE_SPENT'
            and engine.action_catalog.get(e.source_definition_id) is not None
            and (engine.action_catalog[e.source_definition_id].parameters.get('typed') or {}).get('source') == BOUNDARY]
    assert sorted((e.payload['resource_id'], e.payload['amount']) for e in paid) == [
        ('resource:core.qi', 2), (f.pool('oath'), 1)]
    assert any('1 minute' in str(prompt) and 'Guarding Iron' in str(prompt) for prompt in prompts)
    turn(table, mid, FOE)
    use(combat, table, mid, 'Pressure hit', OWNER)
    turn(table, mid, OWNER)
    assert not any(engine.action_catalog.get(c.source_definition_id) and
                   engine.action_catalog[c.source_definition_id].display_name == 'Iron Oath Boundary'
                   for c in combat._load_session(mid).engine.legal_candidates())


@pytest.mark.parametrize('stage', ['Awakened', 'Refined'])
def test_boundary_wrong_stage_and_missing_resource_inert(tmp_path, stage):
    combat, table, mid = oath_table(tmp_path, stage=stage)
    engine = reload(tmp_path, mid)
    assert not any(a.display_name == 'Iron Oath Boundary' for a in engine.action_catalog.values())


@pytest.mark.parametrize('path_resource', [1, 30])
def test_boundary_requires_both_native_resources_before_offering(tmp_path, path_resource):
    combat, table, mid = oath_table(tmp_path, stage='Perfected', path_resource=path_resource)
    engine = reload(tmp_path, mid)
    assert not any(engine.action_catalog.get(c.source_definition_id) and
                   engine.action_catalog[c.source_definition_id].display_name == 'Iron Oath Boundary'
                   for c in engine.legal_candidates())
    if path_resource == 1:
        turn(table, mid, FOE)
        use(combat, table, mid, 'Pressure hit', OWNER)
        turn(table, mid, OWNER)
        engine = reload(tmp_path, mid)
        assert engine.state.actors[OWNER].resources[f.pool('oath')] == 1
        assert not any(engine.action_catalog.get(c.source_definition_id) and
                       engine.action_catalog[c.source_definition_id].display_name == 'Iron Oath Boundary'
                       for c in engine.legal_candidates())


def test_boundary_expires_after_ten_native_rounds(tmp_path):
    combat, table, mid, _ = activate_boundary(tmp_path)
    for _ in range(10):
        turn(table, mid, FOE)
        turn(table, mid, OWNER)
    assert f.held(reload(tmp_path, mid).state.actors[OWNER], 'iron_oath_boundary') is None


def test_boundary_names_a_separate_actual_duty_without_replacing_declaration(tmp_path):
    combat, table, mid = oath_table(tmp_path, stage='Perfected')
    turn(table, mid, FOE)
    use(combat, table, mid, 'Pressure hit', OWNER)
    turn(table, mid, OWNER)
    duty(combat, table, mid, kind='doorway', subject='scene:eastern-gate', record_id='scene:eastern-gate')
    use(combat, table, mid, 'Iron Oath Boundary', choices={f.CHOICE + 'iron_boundary_subject': ['scene:eastern-gate']})
    actor = reload(tmp_path, mid).state.actors[OWNER]
    assert f.held(actor, 'protected_subject').data['record_id'] == ALLY
    assert f.held(actor, 'iron_oath_boundary').data['record_id'] == 'scene:eastern-gate'


@pytest.mark.parametrize('status', ['defending', 'abandoned'])
def test_boundary_fact_correction_cannot_replace_named_subject(tmp_path, status):
    from combat.ext.iron_oath_consumers import active_boundary
    combat, table, mid, _ = activate_boundary(tmp_path)
    actor = reload(tmp_path, mid).state.actors[OWNER]
    assert f.held(actor, 'iron_oath_boundary').data['subject'] == ALLY
    duty(combat, table, mid, kind='doorway', subject='scene:replacement-gate', record_id=ALLY, status=status)
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[OWNER]
    assert active_boundary(engine, actor) is None
    assert f.held(actor, 'iron_oath_boundary').data['subject'] == ALLY
    assert f.held(actor, 'broken_guard_strain') is None


def test_boundary_scar_and_witness_stack_on_one_native_roll(tmp_path):
    combat, table, mid = oath_table(tmp_path, stage='Perfected', dc=1)
    use(combat, table, mid, 'Foundation expression: Scar-Ledger Defense')
    turn(table, mid, FOE)
    use(combat, table, mid, 'Pressure hit', OWNER)
    turn(table, mid, OWNER)
    use(combat, table, mid, 'Iron Oath Boundary')
    turn(table, mid, FOE)
    use(combat, table, mid, 'Pressure hit', OWNER)
    use(combat, table, mid, 'Frightful Roar', choices={f.CHOICE + 'foundation_combat': ['use']})
    engine = reload(tmp_path, mid)
    bonuses = [e.payload['bonus'] for e in engine.events if e.event_type == 'D20_REWRITTEN'
               and e.source_definition_id == f.feature('oath', 'stand_fast_witness')]
    assert bonuses == [12]
    assert any(c.condition_id == SCAR_BAR + '.' + OWNER for c in engine.state.actors[FOE].conditions.values())


def test_boundary_abandonment_is_distinct_from_forced_separation(tmp_path):
    combat, table, mid, _ = activate_boundary(tmp_path)
    duty(combat, table, mid, status='separated')
    actor = reload(tmp_path, mid).state.actors[OWNER]
    assert f.held(actor, 'iron_oath_boundary') is not None
    assert f.held(actor, 'broken_guard_strain') is None
    duty(combat, table, mid, status='abandoned')
    actor = reload(tmp_path, mid).state.actors[OWNER]
    assert f.held(actor, 'iron_oath_boundary') is None
    assert f.held(actor, 'broken_guard_strain').data['severity'] == 1


def test_boundary_witness_adds_same_roll_bonus_and_guard_reduction(tmp_path):
    combat, table, mid, _ = activate_boundary(tmp_path, dc=100, damage=40)
    turn(table, mid, FOE)
    use(combat, table, mid, 'Pressure hit', OWNER)
    use(combat, table, mid, 'Frightful Roar', choices={f.CHOICE + 'foundation_combat': ['use']})
    engine = reload(tmp_path, mid)
    changes = [e for e in engine.events if e.event_type == 'D20_REWRITTEN'
               and e.source_definition_id == f.feature('oath', 'stand_fast_witness')]
    assert changes[-1].payload['bonus'] == 8
    guard_root = tmp_path / 'guard'
    combat, table, mid, _ = activate_boundary(guard_root, damage=40, followup_attack=True)
    turn(table, mid, FOE)
    use(combat, table, mid, 'Pressure hit', OWNER)
    use(combat, table, mid, 'Follow-up pressure hit', OWNER, choices={f.CHOICE + 'foundation_combat': ['use']})
    tmp_path = guard_root
    engine = reload(tmp_path, mid)
    changes = [e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED' and OWNER in e.target_ids]
    # The native hit rolls 1d2+40; Guard reduces PB + key modifier + Boundary PB.
    assert changes[-1].payload['hp_damage'] in (31, 32)


@pytest.mark.parametrize('selected,dc,bonus,bar', [(True, 1, 8, True), (True, 100, 8, False), (False, 1, 4, False)])
def test_scar_same_roll_and_source_turn_expiry(tmp_path, selected, dc, bonus, bar):
    combat, table, mid = oath_table(tmp_path, stage='Refined', dc=dc)
    if selected:
        use(combat, table, mid, 'Foundation expression: Scar-Ledger Defense')
    turn(table, mid, FOE)
    use(combat, table, mid, 'Pressure hit', OWNER)
    use(combat, table, mid, 'Frightful Roar', choices={f.CHOICE + 'foundation_combat': ['use']})
    engine = reload(tmp_path, mid)
    changed = [e for e in engine.events if e.event_type == 'D20_REWRITTEN'
               and e.source_definition_id == f.feature('oath', 'stand_fast_witness')]
    assert changed[-1].payload['bonus'] == bonus
    assert any(c.condition_id == SCAR_BAR + '.' + OWNER for c in engine.state.actors[FOE].conditions.values()) is bar
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    assert not any(c.condition_id == SCAR_BAR + '.' + OWNER for c in reload(tmp_path, mid).state.actors[FOE].conditions.values())


def record_project(combat, table, mid, *, kind='technique_forging', sphere='guardian', limitation=True, owner=OWNER,
                   record_id='project:hold-gate', challenge_dc=16, source_reference=None, fixed_scope=False):
    if kind == 'technique_forging':
        table.canonical_catalog = project_catalog()
    engine = combat._load_session(mid).engine
    document = {'record_id': record_id, 'subject_id': record_id,
        'subject_name': 'Forge Hold the Gate' if kind == 'technique_forging' else 'Challenge: Hold the Gate',
        'subject_kind': 'plan', 'position': engine.state.actors[owner].position.model_dump(mode='json'),
        'source_reference': source_reference or 'campaign:gate-project:printed-recipe-and-GM-scene-assessment',
        'witness_ids': [owner], 'valid_through_round': engine.state.round_number + 10, 'answers': {},
        'project_check': {'actor_id': owner, 'kind': kind, 'sphere_ids': [] if kind == 'scene_check' or sphere is None else ['tianxia.sphere.' + sphere],
                          'limitation': 'This technique can be used only while defending the named eastern gate.' if limitation else '',
                          'limitation_kind': 'protected_subject' if limitation else 'none',
                          'ability': 'CON', 'skill': 'Cultivation',
                          **({'design': {'name': 'Hold the Gate', 'base_form': 'burst',
                                        'primary_talent_id': (GUARDIAN_FORGE_TALENT if sphere == 'guardian' else 'TAL_MAGMA_LAVA_SPIT'),
                                        'secondary_talent_ids': [], 'augment_ids': [], 'drawback_ids': []}}
                             if kind == 'technique_forging' else {'challenge_dc': challenge_dc})}}
    if fixed_scope:
        source = next(a.source_definition_id for a in engine.action_catalog.values()
                      if a.owner_id == owner and (a.parameters.get('typed') or {}).get('source') == 'system:combat.project_check')
        document['technique_scopes'] = [{'actor_id': owner, 'source_definition_id': source,
            'power_id': f.feature('oath', '').rstrip('.'), 'scope': 'fixed_scope',
            'reason': 'This is the bearer’s actual Iron Oath Foundation Challenge, testing the recorded protection oath.'}]
    assert table.record_fact(mid, document, expected_state_version=engine.state.state_version)['status'] == 'COMMITTED'
    return document


@pytest.mark.parametrize('kind', ['technique_forging', 'foundation_challenge'])
@pytest.mark.parametrize('selected,sphere,limitation,delta', [
    (True, 'guardian', True, -2), (False, 'guardian', True, 0),
    (True, 'guardian', False, 0), (True, 'magma', True, 0)])
def test_forging_native_project_dc_and_no_grants(tmp_path, kind, selected, sphere, limitation, delta):
    talent = GUARDIAN_FORGE_TALENT if sphere == 'guardian' else 'TAL_MAGMA_LAVA_SPIT'
    combat, table, mid = oath_table(tmp_path, stage='Refined', owner_talents=[talent])
    if selected:
        use(combat, table, mid, 'Foundation expression: Shield-Body Forging')
    record_project(combat, table, mid, kind=kind, sphere=sphere, limitation=limitation)
    before = reload(tmp_path, mid)
    known_actions = set(before.action_catalog)
    use(combat, table, mid, 'Resolve a project check')
    engine = reload(tmp_path, mid)
    event = next(e for e in engine.events if e.event_type == 'CHECK_ROLLED'
                 and e.source_definition_id.startswith('system:combat.project_check.'))
    assert event.payload['dc_adjustment'] == delta
    assert event.payload['dc'] == (13 if kind == 'technique_forging' else 16) + delta
    assert set(engine.action_catalog) == known_actions
    assert not any(e.event_type == 'RESOURCE_SPENT' and e.source_definition_id == FORGING for e in engine.events)
    assert not any(engine.action_catalog.get(c.source_definition_id) and
                   engine.action_catalog[c.source_definition_id].display_name == 'Resolve a project check'
                   for c in engine.legal_candidates())










def test_forging_does_not_reduce_an_ordinary_scene_check_with_a_protected_limitation(tmp_path):
    combat, table, mid = oath_table(tmp_path, stage='Refined')
    use(combat, table, mid, 'Foundation expression: Shield-Body Forging')
    record_project(combat, table, mid, kind='scene_check', challenge_dc=16)
    use(combat, table, mid, 'Resolve a project check')
    event = next(event for event in reversed(reload(tmp_path, mid).events)
                 if event.event_type == 'CHECK_ROLLED' and event.payload.get('project_kind') == 'scene_check')
    assert event.payload['dc_adjustment'] == 0
    assert event.payload['dc'] == event.payload['base_dc'] == 16


def test_native_forging_cannot_replace_cultivation_with_an_unrelated_skill(tmp_path):
    combat, table, mid = oath_table(tmp_path, stage='Refined', owner_talents=[GUARDIAN_FORGE_TALENT])
    document = record_project(combat, table, mid)
    document['project_check']['skill'] = 'Athletics'
    document['project_check']['ability'] = 'STR'
    with pytest.raises(TabletopError):
        table.record_fact(mid, document, expected_state_version=reload(tmp_path, mid).state.state_version)


@pytest.mark.parametrize('toward', [True, False])
def test_boundary_uses_actual_pressure_source_and_round_clock(tmp_path, toward):
    combat, table, mid, _ = activate_boundary(tmp_path, dc=100)
    engine = reload(tmp_path, mid)
    source = next(a.source_definition_id for a in engine.action_catalog.values()
                  if a.owner_id == FOE and a.display_name == 'Frightful Roar')
    document = duty(combat, table, mid)
    document['roll_pressures'] = [{'actor_id': FOE, 'source_definition_id': source,
        'target_id': OWNER, 'roll_actor_id': OWNER, 'kinds': ['save'], 'categories': ['frightened'],
        'toward_subject': toward, 'evidence': 'Mara is using this roar to drive Wren away from the eastern gate.'}]
    table.record_fact(mid, document, expected_state_version=reload(tmp_path, mid).state.state_version)
    turn(table, mid, FOE)
    use(combat, table, mid, 'Frightful Roar', choices={f.CHOICE + 'foundation_combat': None})
    engine = reload(tmp_path, mid)
    saves = [e for e in engine.events if e.event_type == 'SAVE_ROLLED' and e.actor_id == OWNER
             and e.source_definition_id == source]
    assert saves[-1].payload['mode'] == ('ADVANTAGE' if toward else 'NORMAL')
    assert engine.state.actors[OWNER].turn_flags.get('iron_boundary_round_pressure') == (engine.state.round_number if toward else None)
    assert not any(e.event_type == 'SAVE_ROLLED' and e.actor_id == ALLY and e.payload['mode'] == 'ADVANTAGE'
                   for e in engine.events)


@pytest.mark.parametrize('exact_roller', [True, False, None])
def test_boundary_enemy_save_against_bearer_defense_requires_exact_opponent(tmp_path, exact_roller):
    combat, table, mid, _ = activate_boundary(tmp_path,
        owner_talents=['tianxia.talent.warleader.frightful_roar'])
    engine = reload(tmp_path, mid)
    source = next(a.source_definition_id for a in engine.action_catalog.values()
                  if a.owner_id == OWNER and a.display_name == 'Frightful Roar')
    document = duty(combat, table, mid)
    document['roll_pressures'] = [{'actor_id': OWNER, 'source_definition_id': source,
        'target_id': OWNER, 'roll_actor_id': FOE if exact_roller else (ALLY if exact_roller is False else None),
        'kinds': ['save'], 'categories': ['bypass'], 'toward_subject': True,
        'evidence': 'The invader contests the bearer’s frightening defense to continue bypassing the bearer toward the protected gate.'}]
    table.record_fact(mid, document, expected_state_version=reload(tmp_path, mid).state.state_version)
    use(combat, table, mid, 'Frightful Roar')
    engine = reload(tmp_path, mid)
    saves = [event for event in engine.events if event.event_type == 'SAVE_ROLLED'
             and event.actor_id == FOE and event.source_definition_id == source]
    assert saves[-1].payload['mode'] == ('DISADVANTAGE' if exact_roller else 'NORMAL')
    assert engine.state.actors[OWNER].turn_flags.get('iron_boundary_round_pressure') == (engine.state.round_number if exact_roller else None)


def test_boundary_enemy_check_follows_pair_ally_override_not_roster_team(tmp_path):
    """A roster enemy made ALLY by a pair override is not an enemy of the bearer for Boundary saves."""
    combat, table, mid, _ = activate_boundary(tmp_path, dc=100,
        owner_talents=['tianxia.talent.warleader.frightful_roar'])
    engine = reload(tmp_path, mid)
    source = next(a.source_definition_id for a in engine.action_catalog.values()
                  if a.owner_id == OWNER and a.display_name == 'Frightful Roar')
    document = duty(combat, table, mid)
    document['roll_pressures'] = [{'actor_id': OWNER, 'source_definition_id': source,
        'target_id': OWNER, 'roll_actor_id': FOE, 'kinds': ['save'], 'categories': ['bypass'],
        'toward_subject': True, 'evidence': 'The invader contests the bearer’s frightening defense to continue bypassing the bearer toward the protected gate.'}]
    table.record_fact(mid, document, expected_state_version=reload(tmp_path, mid).state.state_version)
    combat.change_relations(mid, change={'kind': 'ACTOR_RELATION', 'subject': OWNER, 'other': FOE, 'relation': 'ALLY'},
                            expected_state_version=reload(tmp_path, mid).state.state_version)
    use(combat, table, mid, 'Frightful Roar', choices={f.CHOICE + 'foundation_combat': None})
    engine = reload(tmp_path, mid)
    saves = [event for event in engine.events if event.event_type == 'SAVE_ROLLED'
             and event.actor_id == FOE and event.source_definition_id == source]
    assert saves[-1].payload['mode'] == 'NORMAL'


def test_witnessed_threat_qualifies_for_automatic_oath_mark_without_prior_damage(tmp_path):
    """A GM threat the bearer witnessed qualifies on the real engine, with no prior damage or movement."""
    combat, table, mid = oath_table(tmp_path, stage='Perfected', dc=100)
    duty(combat, table, mid, kind='ally', subject=ALLY, witnesses=[OWNER],
         pressures=[{'actor_id': FOE, 'kind': 'threatened',
                     'evidence': 'The invader announces it will strike the protected ally.'}])
    engine = reload(tmp_path, mid)
    owner, foe = engine.state.actors[OWNER], engine.state.actors[FOE]
    assert subjects.qualified_pressure(engine, owner, ALLY, foe, known_only=True) is True
    assert not any(e.event_type == 'DAMAGE_COMMITTED' for e in engine.events)


def test_boundary_nested_opportunity_attack_uses_its_real_source(tmp_path):
    combat, table, mid, _ = activate_boundary(tmp_path)
    engine = reload(tmp_path, mid)
    source = next(a.source_definition_id for a in engine.action_catalog.values()
                  if a.owner_id == FOE and a.display_name == 'Opportunity Attack')
    document = duty(combat, table, mid)
    document['roll_pressures'] = [{'actor_id': FOE, 'source_definition_id': source, 'target_id': OWNER,
        'roll_actor_id': FOE, 'kinds': ['attack'], 'categories': ['bypass'], 'toward_subject': True,
        'evidence': 'This reactive strike contests the bearer holding the approach to the named protected gate.'}]
    table.record_fact(mid, document, expected_state_version=reload(tmp_path, mid).state.state_version)
    engine = reload(tmp_path, mid)
    move = next(c for c in engine.legal_candidates() if c.kind.value == 'MOVE'
                and c.destination is not None and (c.destination.x, c.destination.y) == (3, 7))
    class UseNativeReaction(dict):
        def get(self, key, default=None):
            return 'first'
    settle(table, mid, move.candidate_id, choices=UseNativeReaction())
    engine = reload(tmp_path, mid)
    rolls = [event for event in engine.events if event.event_type == 'ATTACK_ROLLED'
             and event.source_definition_id == source]
    assert rolls and rolls[-1].payload['mode'] == 'DISADVANTAGE'
    assert engine.state.actors[OWNER].turn_flags['iron_boundary_round_pressure'] == engine.state.round_number


def test_forging_reduction_has_no_unprinted_minimum_dc(tmp_path):
    combat, table, mid = oath_table(tmp_path, stage='Refined')
    use(combat, table, mid, 'Foundation expression: Shield-Body Forging')
    record_project(combat, table, mid, kind='foundation_challenge', challenge_dc=1)
    use(combat, table, mid, 'Resolve a project check')
    engine = reload(tmp_path, mid)
    event = next(event for event in reversed(engine.events)
                 if event.event_type == 'CHECK_ROLLED' and event.payload.get('project_kind') == 'foundation_challenge')
    assert event.payload['base_dc'] == 1
    assert event.payload['dc_adjustment'] == -2
    assert event.payload['dc'] == -1


def test_boundary_stock_opportunity_source_uses_public_native_profile(tmp_path):
    from combat.factory_compiler import compile_character
    from combat.gate2_runtime_content import AN
    from combat.gate2_engine import SYSTEM_OPPORTUNITY
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from tests.h1_support import sheet
    document = sheet([], cl=15)
    document['foundation'] = {'foundation_id': f.GROUPS['oath'][0], 'stage': 'Perfected',
        'resource': {'name': 'Guarding Iron', 'resource_id': 'fixture:guarding_iron', 'maximum': 1, 'current': 0}}
    document['ability_scores_and_statistics']['hit_points']['maximum'] = 500
    document['ability_scores_and_statistics']['armor_class']['base_value'] = 1
    bundles = [compile_character(document, actor_id=OWNER, reaction_plan={'ask': True}),
               compile_character(sheet([], cl=15), actor_id=ALLY, reaction_plan={'ask': True})]
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    mid = combat._finish_factory_match(bundles, [OWNER, ALLY, AN],
        {OWNER: 'team:a', ALLY: 'team:a', AN: 'team:b'},
        {OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 4, 'y': 6}, AN: {'x': 3, 'y': 5}},
        combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'], [OWNER, ALLY], [AN],
        control_modes={OWNER: 'MANUAL', ALLY: 'MANUAL', AN: 'MANUAL'},
        match_seed='IRON-BOUNDARY-NATIVE-STOCK', display_name='Native Boundary pressure', maximum_rounds=15)['match_id']
    turn(table, mid, OWNER)
    duty(combat, table, mid)
    use(combat, table, mid, 'Declare Protected Subject', choices={f.CHOICE + 'foundation_subject': [ALLY]})
    class UseNativeReaction(dict):
        def get(self, key, default=None):
            return 'first'
    def move(x, y):
        engine = combat._load_session(mid).engine
        choice = next(c for c in engine.legal_candidates() if c.kind.value == 'MOVE'
                      and c.destination is not None and (c.destination.x, c.destination.y) == (x, y))
        settle(table, mid, choice.candidate_id, choices=UseNativeReaction())
    move(3, 7)
    assert reload(tmp_path, mid).state.actors[OWNER].resources[f.pool('oath')] == 1
    use(combat, table, mid, 'Iron Oath Boundary')
    turn(table, mid, AN)
    turn(table, mid, OWNER)
    move(3, 6)
    document = duty(combat, table, mid)
    document['roll_pressures'] = [{'actor_id': AN, 'source_definition_id': SYSTEM_OPPORTUNITY,
        'target_id': OWNER, 'roll_actor_id': AN, 'kinds': ['attack'], 'categories': ['bypass'],
        'toward_subject': True, 'evidence': 'The native opponent’s reactive strike contests the bearer defending the named approach.'}]
    table.record_fact(mid, document, expected_state_version=reload(tmp_path, mid).state.state_version)
    move(3, 7)
    engine = reload(tmp_path, mid)
    rolls = [event for event in engine.events if event.event_type == 'ATTACK_ROLLED'
             and event.source_definition_id == SYSTEM_OPPORTUNITY]
    assert rolls[-1].payload['mode'] == 'DISADVANTAGE'


@pytest.mark.parametrize('category,matched', [('oath_interpretation', True), ('iron_oath_repair', True),
                                             ('oath_interpretation', False)])
def test_witness_native_external_scene_scope_requires_actual_source(tmp_path, category, matched):
    combat, table, mid = oath_table(tmp_path)
    turn(table, mid, FOE)
    use(combat, table, mid, 'Pressure hit', OWNER)
    turn(table, mid, OWNER)
    document = record_project(combat, table, mid, kind='scene_check', limitation=False)
    engine = reload(tmp_path, mid)
    actor_id = OWNER if matched else FOE
    source = next(a.source_definition_id for a in engine.action_catalog.values()
                  if a.owner_id == actor_id and a.display_name == ('Resolve a project check' if matched else 'Frightful Roar'))
    document['roll_pressures'] = [{'actor_id': actor_id, 'source_definition_id': source,
        'target_id': OWNER, 'roll_actor_id': OWNER, 'kinds': ['check'], 'categories': [category],
        'toward_subject': False, 'evidence': 'The actual hearing interprets the bearer’s protection oath and repairs its breach.'}]
    table.record_fact(mid, document, expected_state_version=engine.state.state_version)
    use(combat, table, mid, 'Resolve a project check', choices={f.CHOICE + 'foundation_combat': ['use']})
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[f.pool('oath')] == int(not matched)
    changes = [e for e in engine.events if e.event_type == 'D20_REWRITTEN'
               and e.source_definition_id == f.feature('oath', 'stand_fast_witness')]
    assert len(changes) == int(matched)




@pytest.mark.parametrize('source,evidence', [('actor:absent', 'A recorded external threat'),
                                           (OWNER, 'The check maker is not an external opponent'), (FOE, '')])
def test_scene_pressure_counterparty_requires_actual_identity_and_evidence(tmp_path, source, evidence):
    combat, table, mid = oath_table(tmp_path)
    document = record_project(combat, table, mid, kind='scene_check')
    document['project_check'].update(pressure_source_actor_id=source, pressure_evidence=evidence)
    with pytest.raises(TabletopError):
        table.record_fact(mid, document, expected_state_version=reload(tmp_path, mid).state.state_version)


def test_witness_and_scar_use_real_native_reaction_check_outcome(tmp_path):
    counter = 'TAL_QIWEAVING_COUNTERWEAVE'
    combat, table, mid = oath_table(tmp_path, stage='Refined', dc=1, owner_talents=[counter])
    use(combat, table, mid, 'Foundation expression: Scar-Ledger Defense')
    document = duty(combat, table, mid)
    document['roll_pressures'] = [{'actor_id': OWNER, 'source_definition_id': counter,
        'target_id': OWNER, 'roll_actor_id': OWNER, 'kinds': ['check'], 'categories': ['frightened'],
        'toward_subject': False, 'evidence': 'This actual Counterweave check contests the hostile fear technique driving the bearer from the protected subject.'}]
    table.record_fact(mid, document, expected_state_version=reload(tmp_path, mid).state.state_version)
    turn(table, mid, FOE)
    use(combat, table, mid, 'Pressure hit', OWNER)
    use(combat, table, mid, 'Frightful Roar', choices={
        'reaction:typed.' + counter: 'USE', f.CHOICE + 'foundation_combat': ['use']})
    engine = reload(tmp_path, mid)
    checks = [event for event in engine.events if event.event_type == 'CHECK_ROLLED'
              and event.source_definition_id == counter]
    assert checks and checks[-1].payload['success'] is True
    assert any(event.event_type == 'D20_REWRITTEN' and event.payload.get('bonus') == 8
               for event in engine.events if event.source_definition_id == f.feature('oath', 'stand_fast_witness'))
    assert any(c.condition_id == SCAR_BAR + '.' + OWNER for c in engine.state.actors[FOE].conditions.values())
    assert not any(c.condition_id.startswith(SCAR_BAR) for c in engine.state.actors[OWNER].conditions.values())


@pytest.mark.parametrize('selected', [False, True])
def test_scar_stops_native_cloud_passage_only_for_source(tmp_path, selected):
    cloud = 'tianxia.subpath.qi.cloud_walker.feature.cloud_immortal'
    combat, table, mid = oath_table(tmp_path, stage='Refined', dc=1, foe_talents=[cloud])
    if selected:
        use(combat, table, mid, 'Foundation expression: Scar-Ledger Defense')
    turn(table, mid, FOE)
    use(combat, table, mid, 'Cloud Immortal')
    turn(table, mid, OWNER)
    turn(table, mid, FOE)
    use(combat, table, mid, 'Pressure hit', OWNER)
    use(combat, table, mid, 'Frightful Roar', choices={f.CHOICE + 'foundation_combat': ['use']})
    engine = reload(tmp_path, mid)
    from combat.movement_routes import explicit_candidate
    from combat.gate2_runtime_models import Position
    path = [Position(x=3, y=y) for y in (5, 6, 7)]
    if selected:
        with pytest.raises(ValueError):
            explicit_candidate(engine, FOE, path, 'walk')
    else:
        move = explicit_candidate(engine, FOE, path, 'walk')
        # Commit the exact selected route through the normal table writer.
        result = table.act(mid, move.candidate_id, move.decision_id, move.state_version, 0,
                           movement_path=[point.model_dump(mode='json') for point in path], movement_mode='walk', actor_id=FOE)
        assert result['status'] == 'COMMITTED'
        assert reload(tmp_path, mid).state.actors[FOE].position.y == 7


def test_scar_bar_waits_for_the_final_save_outcome_not_the_preliminary_save_roll(tmp_path, monkeypatch):
    """Witness succeeds on its own d20 (SAVE_ROLLED success=True), then the save's final outcome is forced
    to failure by the engine's outcome channel (as Omen Witness does). Scar-Ledger must not bar passage."""
    from combat.gate2_engine import Gate2Engine
    real = Gate2Engine._roll_save

    def forced_failure(self, target, *args, **kwargs):
        roll = real(self, target, *args, **kwargs)
        if target.entity_id == OWNER and roll is not None:
            self._typed_roll_outcome = {**(getattr(self, '_typed_roll_outcome', None) or {}), OWNER: 'failure'}
        return roll

    monkeypatch.setattr(Gate2Engine, '_roll_save', forced_failure)
    combat, table, mid = oath_table(tmp_path, stage='Refined', dc=1)
    use(combat, table, mid, 'Foundation expression: Scar-Ledger Defense')
    turn(table, mid, FOE)
    use(combat, table, mid, 'Pressure hit', OWNER)
    use(combat, table, mid, 'Frightful Roar', choices={f.CHOICE + 'foundation_combat': ['use']})
    engine = reload(tmp_path, mid)
    saves = [e for e in engine.events if e.event_type == 'SAVE_ROLLED' and e.actor_id == OWNER]
    assert saves and saves[-1].payload['success'] is True, 'the preliminary save roll really succeeded'
    assert any(e.event_type == 'D20_REWRITTEN' and e.source_definition_id == f.feature('oath', 'stand_fast_witness')
               for e in engine.events), 'Witness was paid on this roll'
    assert not any(c.condition_id == SCAR_BAR + '.' + OWNER for c in engine.state.actors[FOE].conditions.values())


def test_boundary_allies_follow_relation_overrides_not_team_ids(tmp_path):
    """A pair ALLY override across rosters is offered; an ally flipped to ENEMY by a pair override is not."""
    combat, table, mid = oath_table(tmp_path, stage='Perfected', dc=100)
    turn(table, mid, FOE)
    use(combat, table, mid, 'Pressure hit', OWNER)
    turn(table, mid, OWNER)
    combat.change_relations(mid, change={'kind': 'ACTOR_RELATION', 'subject': OWNER, 'other': FOE, 'relation': 'ALLY'},
                            expected_state_version=reload(tmp_path, mid).state.state_version)
    combat.change_relations(mid, change={'kind': 'ACTOR_RELATION', 'subject': OWNER, 'other': ALLY, 'relation': 'ENEMY'},
                            expected_state_version=reload(tmp_path, mid).state.state_version)
    prompts = use(combat, table, mid, 'Iron Oath Boundary', choices={f.CHOICE + 'iron_boundary_allies': [FOE]})
    engine = reload(tmp_path, mid)
    assert engine.state.actors[FOE].temporary_hp == 4
    assert engine.state.actors[ALLY].temporary_hp == 0
    allies = [p for p in prompts if p['context']['reaction_source_id'] == f.CHOICE + 'iron_boundary_allies']
    assert allies, 'the ally choice is offered'
    options = {o['id'] for p in allies for o in p['choice']['options']}
    assert FOE in options and ALLY not in options


def test_boundary_native_fear_without_recorded_toward_subject_stays_neutral(tmp_path):
    """Fear aimed at the bearer does not establish pressure toward the protected subject by itself."""
    combat, table, mid, _ = activate_boundary(tmp_path, dc=100)
    turn(table, mid, FOE)
    use(combat, table, mid, 'Frightful Roar', choices={f.CHOICE + 'foundation_combat': None})
    engine = reload(tmp_path, mid)
    source = next(a.source_definition_id for a in engine.action_catalog.values()
                  if a.owner_id == FOE and a.display_name == 'Frightful Roar')
    saves = [e for e in engine.events if e.event_type == 'SAVE_ROLLED' and e.actor_id == OWNER
             and e.source_definition_id == source]
    assert saves and saves[-1].payload['mode'] == 'NORMAL'
    assert engine.state.actors[OWNER].turn_flags.get('iron_boundary_round_pressure') is None


def test_ally_declaration_follows_relation_overrides_in_record_fact(tmp_path):
    """A pair ALLY override makes a roster-enemy a valid ally duty; ALLY->ENEMY makes a roster-ally invalid."""
    combat, table, mid = oath_table(tmp_path, stage='Perfected', dc=100)
    combat.change_relations(mid, change={'kind': 'ACTOR_RELATION', 'subject': OWNER, 'other': FOE, 'relation': 'ALLY'},
                            expected_state_version=reload(tmp_path, mid).state.state_version)
    document = duty(combat, table, mid, kind='ally', subject=FOE, record_id='override-ally')
    assert document['record_id'] == 'override-ally'
    combat.change_relations(mid, change={'kind': 'ACTOR_RELATION', 'subject': OWNER, 'other': ALLY, 'relation': 'ENEMY'},
                            expected_state_version=reload(tmp_path, mid).state.state_version)
    with pytest.raises((ValueError, TabletopError), match='ally declaration must name an ally'):
        duty(combat, table, mid, kind='ally', subject=ALLY, record_id='flipped-ally')
