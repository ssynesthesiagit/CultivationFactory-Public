"""Whole Garden consumers through compiled ownership and accepted table actions."""
import pytest
from combat.factory_compiler import compile_character
from tests.h1_support import sheet
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, turn, reload
from tests.test_mgr_t14_garden_sum import GARDEN, GARDEN_NAME, FOUNDATION
from combat.ext.foundation_context import CONTEXT

DAMAGE = 'choice:needle.ash_garden.damage'


def native_garden(tmp_path, *, stage='Perfected', seed='ASH-GARDEN', hp=100, extra_foes=0, talents=(),
                  ally_talents=(), team_overrides=None, positions=None, extra_allies=0, wide=False,
                  bundle_transform=None):
    doc = sheet(['FIRE_TAL_FLAME_LASH', *talents], cl=5, foundation={
        'foundation_id': FOUNDATION, 'stage': stage,
        'resource': {'name': 'Funeral Ash', 'resource_id': 'tianxia.resource.funeral_ash',
                     'maximum': 1, 'current': 0}})
    doc['foundation'] = {'foundation_id': FOUNDATION, 'stage': stage,
        'resource': {'name': 'Funeral Ash', 'resource_id': 'tianxia.resource.funeral_ash',
                     'maximum': 1, 'current': 0}}
    doc['ability_scores_and_statistics']['technique_attack_bonus'] = 100
    bundle = compile_character(doc, actor_id=OWNER, reaction_plan={'ask': True})
    foe = sheet([], cl=5)
    foe['ability_scores_and_statistics']['hit_points']['maximum'] = hp
    arena = None
    if wide:
        from combat.gate5_service import CombatService
        from tests.h1_support import ROOT
        service = CombatService(ROOT, tmp_path)
        saved = service.tabletop_maps.save({'display_name':'Garden source control', 'width_squares':40,
            'height_squares':20, 'walls':[], 'terrain':[], 'starts':{'team1':[[3,6]],'team2':[[9,6]]}})
        arena = service.factory_arenas()['battlefield:map.'+saved['map_id']]
    return fixture(tmp_path, [], owner_bundle=bundle, foe_sheet=foe, seed=seed, extra_foes=extra_foes,
        ally_talents=ally_talents, team_overrides=team_overrides,
        extra_allies=extra_allies,
        bundle_transform=bundle_transform,
        battlefield=arena,
        positions=positions or {OWNER: {'x':3,'y':6}, ALLY: {'x':4,'y':6}, FOE: {'x':6,'y':6}})


def cast(combat, table, mid, name, *, choices=None, target=None):
    engine = reload(combat.userdata_root, mid)
    if engine.state.current_actor_id == OWNER and not engine.state.actors[OWNER].action_available:
        settle(table, mid, table.state(mid)['menu']['end_turn'], choices={CONTEXT:'unknown'})
    turn_unknown(table, mid, OWNER)
    target = target or (OWNER if name == GARDEN_NAME else FOE)
    return settle(table, mid, candidate(combat, mid, name, target=target).candidate_id,
        choices=choices or {CONTEXT: 'unknown'})


def turn_unknown(table, mid, actor):
    for _ in range(16):
        menu = table.state(mid)['menu']
        if menu['actor_id'] == actor:
            return
        settle(table, mid, menu['end_turn'], choices={CONTEXT:'unknown'})
    raise AssertionError('actor turn not reached')


def garden_packets(engine):
    return [e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED'
        and e.payload.get('display_source_id') == GARDEN]


def test_garden_is_not_a_limited_attack_modifier_before_activation(tmp_path):
    combat, table, mid = native_garden(tmp_path)
    engine = reload(tmp_path, mid)
    variants = [a for a in engine.action_catalog.values()
        if any(GARDEN in str(c) for c in a.costs) and a.display_name != GARDEN_NAME]
    assert not variants, [a.display_name for a in variants]
    assert not garden_packets(engine)
    assert not [a for a in engine.action_catalog.values()
        if any(e.get('type') == 'extra_damage' for e in (a.parameters.get('typed') or {}).get('effects', ()))
        and (a.parameters.get('typed') or {}).get('source') == GARDEN]


@pytest.mark.parametrize('damage_type', ['fire','necrotic','poison','slashing'])
def test_active_garden_adds_exact_pb_of_chosen_type_to_wounded_aligned_hit(tmp_path, damage_type):
    combat, table, mid = native_garden(tmp_path, seed='ASH-GARDEN-fire')
    cast(combat, table, mid, 'Flame Lash')
    cast(combat, table, mid, GARDEN_NAME)
    before = reload(tmp_path, mid)
    assert 0 < before.state.actors[FOE].current_hp < before.state.actors[FOE].maximum_hp
    first = before.state.event_sequence
    prompts = cast(combat, table, mid, 'Flame Lash', choices={
        CONTEXT: 'real', CONTEXT+'.detail': 'battlefield', DAMAGE: damage_type})
    engine = reload(tmp_path, mid)
    packets = [e for e in garden_packets(engine) if e.sequence > first]
    assert len(packets) == 1, [(e.event_type,e.payload) for e in engine.events if e.sequence > first]
    assert packets[0].payload['damage_type'].lower() == damage_type
    assert packets[0].payload['rolled_or_pending_damage'] == engine.state.actors[OWNER].proficiency_bonus
    assert any(p['context']['reaction_source_id'] == DAMAGE for p in prompts)
    uses = [k for k in engine.state.actors[OWNER].resources if k.startswith('resource:uses.') and GARDEN in k]
    assert len(uses) == 1 and engine.state.actors[OWNER].resources[uses[0]] == 0


def test_garden_wounded_gate_uses_hit_time_not_damage_created_wound(tmp_path):
    combat, table, mid = native_garden(tmp_path)
    cast(combat, table, mid, GARDEN_NAME)
    prompts = cast(combat, table, mid, 'Flame Lash', choices={CONTEXT:'real', CONTEXT+'.detail':'battlefield'})
    engine = reload(tmp_path, mid)
    assert engine.state.actors[FOE].current_hp < engine.state.actors[FOE].maximum_hp
    assert not garden_packets(engine)
    assert not any(p['context']['reaction_source_id'] == DAMAGE for p in prompts)


@pytest.mark.parametrize('circumstances', ['staged','harmless','voluntary','training','helpless','unknown'])
def test_garden_alignment_does_not_apply_generation_only_exclusions(tmp_path, circumstances):
    combat, table, mid = native_garden(tmp_path, seed='ASH-GARDEN-'+circumstances)
    cast(combat, table, mid, 'Flame Lash')
    cast(combat, table, mid, GARDEN_NAME)
    cast(combat, table, mid, 'Flame Lash', choices={CONTEXT:circumstances, CONTEXT+'.detail':'battlefield'})
    # Printed Meridian/Garden alignment has no generation-only exclusions.
    # A separately established residue fact still qualifies for hit damage.
    assert garden_packets(reload(tmp_path, mid))


def test_unowned_stage_never_receives_garden_activation_or_hit_consumer(tmp_path):
    combat, table, mid = native_garden(tmp_path, stage='Awakened')
    engine = reload(tmp_path, mid)
    assert not any(a.display_name == GARDEN_NAME for a in engine.action_catalog.values())
    assert not any(r.get('block') == 'ash_garden' for r in engine.typed_passive_rows.get(OWNER, ()))


@pytest.mark.parametrize('consent,expected', [('generate',1),(None,0)])
def test_genuine_zero_hp_inside_garden_is_optional_and_settled(tmp_path, consent, expected):
    combat, table, mid = native_garden(tmp_path, hp=1, extra_foes=1, seed='GARDEN-ZERO-'+str(consent))
    cast(combat, table, mid, GARDEN_NAME)
    prompts = cast(combat, table, mid, 'Flame Lash', choices={CONTEXT:'real', CONTEXT+'.detail':'defeat',
        'choice:needle.ash_garden.generate':consent})
    engine = reload(tmp_path, mid)
    assert engine.state.actors[FOE].current_hp == 0
    assert engine.state.actors[OWNER].resources['resource:foundation.funeral_ash'] == expected
    assert any(p['context']['reaction_source_id'] == 'choice:needle.ash_garden.generate' for p in prompts)
    if expected:
        gain = next(e for e in engine.events if e.event_type == 'RESOURCE_GAINED'
                    and e.payload.get('resource_id') == 'resource:foundation.funeral_ash')
        drops = [e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED'
                 and FOE in e.target_ids and e.payload.get('remaining_hp') == 0]
        assert drops and all(e.sequence < gain.sequence for e in drops)
        holder = engine.state.actors[OWNER]
        assert holder.resource_maximums['resource:foundation.funeral_ash'] == 1
        clock = holder.turn_flags['pressure_round_clock']['resource:foundation.funeral_ash']
        assert clock['round'] == engine.state.round_number and clock['count'] == 1
        settle(table, mid, table.state(mid)['menu']['end_turn'], choices={CONTEXT:'unknown'})
        turn(table, mid, OWNER)
        assert reload(tmp_path, mid).state.actors[OWNER].resources['resource:foundation.funeral_ash'] == 1
        settle(table, mid, table.state(mid)['menu']['end_turn'], choices={CONTEXT:'unknown'})
        assert reload(tmp_path, mid).state.actors[OWNER].resources['resource:foundation.funeral_ash'] == 0


def test_ordinary_stabilization_does_not_manufacture_a_cautery_fact(tmp_path):
    striker = 'actor:factory.worker2-ally3'
    combat, table, mid = native_garden(tmp_path, hp=3, extra_allies=1, seed='GARDEN-TREATMENT',
        ally_talents=('LIFE_BASE_BORROWED_BREATH',), team_overrides={ALLY:'team:opponents'},
        positions={OWNER:{'x':3,'y':6}, ALLY:{'x':7,'y':6}, FOE:{'x':6,'y':6}, striker:{'x':5,'y':5}})
    cast(combat, table, mid, GARDEN_NAME)
    for _ in range(3):
        turn_unknown(table, mid, striker)
        settle(table, mid, candidate(combat, mid, 'Unarmed Strike', target=FOE).candidate_id,
            choices={CONTEXT:'unknown'})
        engine = reload(tmp_path, mid)
        if engine.state.actors[FOE].current_hp == 0:
            break
        settle(table, mid, table.state(mid)['menu']['end_turn'], choices={CONTEXT:'unknown'})
    engine = reload(tmp_path, mid)
    assert engine.state.actors[FOE].current_hp == 0 and engine.state.actors[FOE].life_state == 'DYING'
    turn_unknown(table, mid, ALLY)
    engine = reload(tmp_path, mid)
    settle(table, mid, candidate(combat, mid, 'Borrowed Breath', target=FOE).candidate_id,
        choices={CONTEXT:'real', CONTEXT+'.detail':'cautery',
        'choice:needle.ash_garden.generate':'generate'})
    engine = reload(tmp_path, mid)
    assert engine.state.actors[FOE].life_state == 'STABLE'
    assert engine.state.actors[OWNER].resources['resource:foundation.funeral_ash'] == 0
    assert any(e.event_type == 'LIFE_STATE_CHANGED' and e.actor_id == FOE
               and e.payload.get('life_state') == 'STABLE' for e in engine.events)


def test_garden_is_inert_on_a_native_untyped_engine():
    from combat.gate2_engine import Gate2Engine
    from tests.h1_support import ROOT
    from combat.ext.ash_garden import owned
    engine = Gate2Engine(ROOT, match_seed='GARDEN-UNTYPED')
    assert not any(owned(engine, actor) for actor in engine.state.actors.values())


def test_friendly_damage_cannot_farm_a_hostile_garden_subject(tmp_path):
    def inclusive_fixture_blast(bundles):
        # Garden needs an actual friendly-damage receipt. Default unscoped
        # harmful areas target enemies; use the sealed explicit policy that
        # execution recomputes after reload, not just the geometry's roster.
        for action in bundles[1]['action_catalog']:
            typed = action.get('parameters', {}).get('typed', {})
            if typed.get('source') == 'FIRE_TAL_FIREBALL_ART':
                typed['area'] = {**typed['area'], 'explicit_harmful_recipients': 'other_creatures'}

    combat, table, mid = native_garden(tmp_path, hp=1, wide=True, ally_talents=('FIRE_TAL_FIREBALL_ART',),
        team_overrides={ALLY:'team:opponents'}, positions={OWNER:{'x':3,'y':6},
        ALLY:{'x':8,'y':7}, FOE:{'x':9,'y':6}}, bundle_transform=inclusive_fixture_blast)
    cast(combat, table, mid, GARDEN_NAME)
    turn_unknown(table, mid, ALLY)
    before = reload(tmp_path, mid)
    from combat.area_recipients import scoped_area
    blast = next(a for a in before.action_catalog.values()
                 if a.owner_id == ALLY and a.display_name == 'Fireball Art')
    typed = blast.parameters['typed']
    area = scoped_area(typed['area'], typed['effects'], typed=typed)
    assert area['harmful_recipient_override'] == 'all', 'Fixture must permit friendly payloads after reload'
    prompts = settle(table, mid, candidate(combat, mid, 'Fireball Art', at=(9,6)).candidate_id,
        choices={CONTEXT:'real', 'choice:needle.ash_garden.generate':'generate'})
    engine = reload(tmp_path, mid)
    assert engine.state.actors[FOE].current_hp == 0, 'Fixture must actually defeat the friendly subject'
    from combat.relations import relation, ALLY as FRIENDLY
    assert relation(engine, engine.state.actors[ALLY], engine.state.actors[FOE]) == FRIENDLY
    assert any(e.event_type == 'DAMAGE_COMMITTED' and e.actor_id == ALLY and e.target_ids == (FOE,)
               and e.payload['hp_before'] > 0 and e.payload['remaining_hp'] == 0 for e in engine.events)
    assert engine.state.actors[OWNER].resources['resource:foundation.funeral_ash'] == 0
    assert not any(p['context']['reaction_source_id'] == 'choice:needle.ash_garden.generate' for p in prompts)


def test_garden_applies_to_each_real_hit_without_spending_activation_uses_again(tmp_path):
    combat, table, mid = native_garden(tmp_path, talents=('FIRE_TAL_SCORCHING_RAY_ART',))
    cast(combat, table, mid, 'Flame Lash')
    cast(combat, table, mid, GARDEN_NAME)
    first = reload(tmp_path, mid).state.event_sequence
    cast(combat, table, mid, 'Scorching Ray Art', choices={CONTEXT:'real', CONTEXT+'.detail':'battlefield', DAMAGE:'poison'})
    engine = reload(tmp_path, mid)
    hits = [e for e in engine.events if e.sequence > first
            and e.payload.get('fact_kind') == 'ash_garden_confirmed_hit']
    packets = [e for e in garden_packets(engine) if e.sequence > first]
    assert len(hits) >= 2 and len(packets) == len(hits)
    assert all(e.payload['rolled_or_pending_damage'] == engine.state.actors[OWNER].proficiency_bonus for e in packets)


def test_garden_does_not_reach_wounded_enemy_outside_moving_field(tmp_path):
    combat, table, mid = native_garden(tmp_path, talents=('FIRE_TAL_SCORCHING_RAY_ART',))
    cast(combat, table, mid, 'Flame Lash')
    cast(combat, table, mid, GARDEN_NAME)
    for x in (2,1):
        menu = table.state(mid)['menu']
        move = next(m for m in menu['moves'] if m['destination'] == {'x':x,'y':6})
        settle(table, mid, move['candidate_id'], choices={CONTEXT:'unknown'})
    cast(combat, table, mid, 'Scorching Ray Art', choices={CONTEXT:'real', CONTEXT+'.detail':'battlefield'})
    assert not garden_packets(reload(tmp_path, mid))


def test_preview_and_decline_do_not_grant_damage_or_generation(tmp_path):
    from tests.test_r9i_karma_persistence import act
    combat, table, mid = native_garden(tmp_path)
    cast(combat, table, mid, 'Flame Lash')
    cast(combat, table, mid, GARDEN_NAME)
    settle(table, mid, table.state(mid)['menu']['end_turn'], choices={CONTEXT:'unknown'})
    turn_unknown(table, mid, OWNER)
    row = candidate(combat, mid, 'Flame Lash', target=FOE)
    before = reload(tmp_path, mid).state.model_dump(mode='json')
    for _ in range(2):
        result = act(table, mid, row.candidate_id, [])
        assert result['status'] == 'REACTION_REQUIRED'
        assert reload(tmp_path, mid).state.model_dump(mode='json') == before
    settle(table, mid, row.candidate_id, choices={CONTEXT:None})
    engine = reload(tmp_path, mid)
    assert not garden_packets(engine)
    assert engine.state.actors[OWNER].resources['resource:foundation.funeral_ash'] == 0


def test_public_unknown_method_answer_does_not_infer_alignment_from_damage(tmp_path):
    combat, table, mid = native_garden(tmp_path, talents=('AIR_BASE_WIND_LASH',))
    cast(combat, table, mid, 'Flame Lash')
    cast(combat, table, mid, GARDEN_NAME)
    prompts = cast(combat, table, mid, 'Wind Lash: Cut', choices={CONTEXT:'real', CONTEXT+'.detail':'battlefield'})
    assert not any(p['context']['reaction_source_id'] == DAMAGE for p in prompts)
    assert not garden_packets(reload(tmp_path, mid))
