"""Native acquired Cauldron progression -> table -> cold replay.

Every Essence in these scenarios originates from a real opposing technique.
No fabricated ownership, manually inserted Essence, live models or GUI calls.
"""
import json
from copy import deepcopy

import pytest

from app.core import FoundryError
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.ext import black_cauldron as C
from tests.h1_support import ROOT, sheet, script
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, reload, settle, turn

SOUND = 'tianxia.subpath.qi.sound_cultivator'


def fixed_dice(monkeypatch, values):
    """Targeted attack fixtures use the first die; turn transitions use the rest (public copy)."""
    from combat.gate4_engine import Gate4ControllerEngine
    from tests.h1_support import script
    current = Gate4ControllerEngine.execute_intent
    original = getattr(current, '_pt_original', current)
    def execute(engine, intent, *args, **kwargs):
        script(engine, values if intent.target_ids else values[1:])
        return original(engine, intent, *args, **kwargs)
    execute._pt_original = original
    monkeypatch.setattr(Gate4ControllerEngine, 'execute_intent', execute)


@pytest.fixture(autouse=True)
def isolated_transports(monkeypatch):
    from combat import embedding_rank, menu_rank
    def transport(url, body, timeout):
        count = len(json.loads(body)['input'])
        return json.dumps({'data': [{'index': i, 'embedding': [1] + [0] * (embedding_rank.DIMENSION - 1)}
                                    for i in range(count)]}).encode()
    monkeypatch.setattr(menu_rank, '_CLIENT', embedding_rank.EmbeddingClient(transport=transport))
    fixed_dice(monkeypatch, [19] + [4] * 150)


QI = 'tianxia.path.qi_cultivation'


def acquired_sheet(cl, parent=C.PARENT, name=None, features=()):
    """A character whose Path row carries the NS1R acquisition record the compiler consumes.

    Synthetic and public: the row has the same recorded provenance shape that NonSphereAuthority writes
    when a native Subpath is selected, so no private authority pack or evidence store is needed here.
    ``features`` are Path feature records the sheet owns (a Domain Armament, when a test needs one).
    """
    doc = sheet(list(features), cl=cl, name=name or ('Cauldron keeper' if parent == C.PARENT else 'Hostile musician'))
    path_features = (doc.get('path_and_subpath') or {}).get('path_feature_record_ids') or []
    doc['path_and_subpath'] = {
        'paths': [{'path_id': QI, 'attainment': cl, 'effective_cl': cl,
                   'subpath_or_tradition_id': parent,
                   'subpath_or_tradition_acquisition_provenance': {
                       'schema': 'TianxiaFactory.AcquisitionProvenance.v1', 'canonical_content_id': parent,
                       'content_type': 'Qi Cultivation Subpath', 'access_category': 'Open',
                       'source': 'post-creation-authority-selection', 'recorded': True}}],
        **({'path_feature_record_ids': list(path_features)} if path_features else {})}
    return doc


@pytest.fixture(scope='module')
def acquired():
    def acquire(cl, parent=C.PARENT):
        return acquired_sheet(cl, parent)
    return acquire


def scenario(tmp_path, acquired, cl=3, *, enemy_cl=3, effective_cl=None, unowned=False, positions=None, fire=False,
             features=()):
    doc = acquired(cl) if not features else acquired_sheet(cl, features=features)
    if fire:
        # A native starting Fire Sphere supplies its printed base technique;
        # the Cauldron progression itself always comes from NS1R acquisition.
        doc['spheres_and_talents'] = sheet(['FIRE_BASE_IGNITE'], cl=cl)['spheres_and_talents']
    if effective_cl is not None:
        doc['path_and_subpath']['paths'][0]['effective_cl'] = effective_cl
    if unowned:
        doc['path_and_subpath'] = {}
    bundle = compile_character(doc, actor_id=OWNER, reaction_plan={'ask': True})
    foe = acquired(enemy_cl, SOUND)
    return fixture(tmp_path, [], owner_bundle=bundle, foe_sheet=foe, cl=cl,
                   positions=positions, ask=True, seed='CAULDRON-NATIVE')


def cast(combat, table, mid, name, target=None, at=None, choices=None):
    selected = candidate(combat, mid, name, target=target, at=at)
    return settle(table, mid, selected.candidate_id, choices=choices or {})


def attack(combat, table, mid, *, swallow=True, shell='hp'):
    turn(table, mid, FOE)
    return cast(combat, table, mid, 'Instrument of Qi: Thunder', OWNER,
        choices={'choice:needle.black_cauldron_swallow': ['THUNDER'] if swallow else None,
                 'choice:needle.black_cauldron_shell': [shell]})


@pytest.mark.parametrize('cl,expected', [(3, 1), (6, 2), (10, 3), (14, 4), (18, 5)])
def test_native_progression_acquisition_compiles_only_attained_tiers(tmp_path, acquired, cl, expected):
    combat, table, mid = scenario(tmp_path, acquired, cl)
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[OWNER]
    assert sum(bool(C.owned(engine, actor, fid)) for fid in C.TIERS) == expected
    assert not C.store(actor)
    assert not any('Swallow' in c.display_name or 'Refine the Stolen' in c.display_name
                   for c in engine.legal_candidates()), 'triggered features must not become free resource buttons'


@pytest.mark.parametrize('mode', ['unowned', 'suppressed'])
def test_wrong_owner_and_suppressed_default_inert(tmp_path, acquired, mode):
    combat, table, mid = scenario(tmp_path, acquired, 18, unowned=mode == 'unowned',
                                  effective_cl=2 if mode == 'suppressed' else None)
    prompts = attack(combat, table, mid)
    engine = reload(tmp_path, mid)
    assert not C.store(engine.state.actors[OWNER])
    assert not any(p['context']['reaction_source_id'].startswith('choice:needle.black_cauldron') for p in prompts)


def test_swallow_residue_native_damage_payment_essence_and_cold_replay(tmp_path, acquired):
    combat, table, mid = scenario(tmp_path, acquired)
    before = reload(tmp_path, mid).state.actors[OWNER].resources[C.QI]
    prompts = attack(combat, table, mid)
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[OWNER]
    assert [e['type'] for e in C.store(actor)] == ['THUNDER']
    assert actor.resources[C.QI] == before - 1
    assert not actor.reaction_available
    assert any('Swallow the Residue' in str(p) and 'Hostile musician' in str(p) for p in prompts)
    assert any(e.event_type == 'REACTION_RESOLVED' and e.source_definition_id == C.RESIDUE for e in engine.events)


def test_passing_swallow_preserves_qi_reaction_and_empty_pool(tmp_path, acquired):
    combat, table, mid = scenario(tmp_path, acquired)
    before = reload(tmp_path, mid).state.actors[OWNER].resources[C.QI]
    attack(combat, table, mid, swallow=False)
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[OWNER]
    assert not C.store(actor)
    assert actor.resources[C.QI] == before
    assert actor.reaction_available


def test_swallow_art_native_two_essence_shell_corruption_and_replay(tmp_path, acquired):
    combat, table, mid = scenario(tmp_path, acquired, 10)
    prompts = attack(combat, table, mid)
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[OWNER]
    assert [e['type'] for e in C.store(actor)] == ['THUNDER', 'THUNDER']
    assert actor.temporary_hp == 2 * int(C.numbers(engine, actor)['pb'])
    assert actor.resources[C.CORRUPTION] == 1
    assert any('Swallow the Art' in str(p) for p in prompts)


def test_native_field_creates_real_anchor_zone_paid_concentration_and_cold_reload(tmp_path, acquired):
    combat, table, mid = scenario(tmp_path, acquired, 18)
    original = reload(tmp_path, mid)
    before = original.state.actors[OWNER].resources[C.QI]
    field_action = next(a for a in original.action_catalog.values()
                        if a.owner_id == OWNER and a.display_name == 'Heaven-Devouring Cauldron')
    assert not any(pool == 'resource:uses.' + field_action.source_definition_id for pool, _ in field_action.costs)
    cast(combat, table, mid, 'Heaven-Devouring Cauldron', at=(9, 6),
         choices={'choice:needle.black_cauldron_field_type': ['FORCE']})
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[OWNER]
    field = C.fields(engine, actor)[0]
    anchor = engine.state.objects[field.trigger_profile['profile']['anchor']]
    assert anchor.owner_id == OWNER and anchor.maximum_hp == 90
    assert anchor.ac == C.numbers(engine, actor)['save_dc']
    assert anchor.component['width_cells'] == anchor.component['length_cells'] == 2
    assert actor.concentration and actor.concentration.zone_id == field.zone_id
    assert actor.resources[C.QI] == before - 8
    assert field.trigger_profile['height_ft'] == 40
    assert not any(c.display_name == 'Heaven-Devouring Cauldron' for c in engine.legal_candidates())


def test_native_field_turn_trigger_drain_cannot_recover_and_replay(tmp_path, acquired):
    combat, table, mid = scenario(tmp_path, acquired, 18)
    cast(combat, table, mid, 'Heaven-Devouring Cauldron', at=(9, 6),
         choices={'choice:needle.black_cauldron_field_type': ['FORCE']})
    before = reload(tmp_path, mid)
    hp, qi = before.state.actors[FOE].current_hp, before.state.actors[FOE].resources[C.QI]
    turn(table, mid, FOE)
    engine = reload(tmp_path, mid)
    foe = engine.state.actors[FOE]
    assert foe.current_hp < hp
    assert foe.resources[C.QI] == qi - 1
    assert C.condition(foe, 'condition:typed.black_cauldron_recovery')
    assert C.fields(engine, engine.state.actors[OWNER])[0].trigger_profile['profile']['consumed_cp'] == 1


def test_native_field_anchor_movement_retains_profile_and_once_turn_limit(tmp_path, acquired):
    combat, table, mid = scenario(tmp_path, acquired, 18)
    cast(combat, table, mid, 'Heaven-Devouring Cauldron', at=(9, 6),
         choices={'choice:needle.black_cauldron_field_type': ['FORCE']})
    cast(combat, table, mid, 'Move Cauldron Anchor', choices={'choice:needle.black_cauldron_move_anchor': ['10,6,0']})
    engine = reload(tmp_path, mid)
    zone = C.fields(engine, engine.state.actors[OWNER])[0]
    obj = engine.state.objects[zone.trigger_profile['profile']['anchor']]
    assert (obj.position.x, obj.position.y, obj.position.z) == (10, 6, 0)
    assert zone.center == obj.position
    assert obj.current_hp == 90
    assert not any(c.display_name == 'Move Cauldron Anchor' for c in engine.legal_candidates())


def test_native_moving_field_over_creature_waits_for_its_actual_turn_start(tmp_path, acquired):
    combat, table, mid = scenario(tmp_path, acquired, 18)
    cast(combat, table, mid, 'Heaven-Devouring Cauldron', at=(13, 6),
         choices={'choice:needle.black_cauldron_field_type': ['FORCE']})
    before = reload(tmp_path, mid)
    assert not C.in_field(before, before.state.actors[OWNER], before.state.actors[FOE])
    hp = before.state.actors[FOE].current_hp
    qi = before.state.actors[FOE].resources[C.QI]
    cast(combat, table, mid, 'Move Cauldron Anchor', choices={'choice:needle.black_cauldron_move_anchor': ['10,6,0']})
    moved = reload(tmp_path, mid)
    assert C.in_field(moved, moved.state.actors[OWNER], moved.state.actors[FOE])
    assert moved.state.actors[FOE].current_hp == hp
    assert moved.state.actors[FOE].resources[C.QI] == qi
    turn(table, mid, FOE)
    after = reload(tmp_path, mid)
    assert after.state.actors[FOE].current_hp < hp
    assert after.state.actors[FOE].resources[C.QI] == qi - 1


def test_native_feed_does_not_farm_hostile_more_than_five_levels_lower(tmp_path, acquired):
    combat, table, mid = scenario(tmp_path, acquired, 18, enemy_cl=3)
    cast(combat, table, mid, 'Heaven-Devouring Cauldron', at=(9, 6),
         choices={'choice:needle.black_cauldron_field_type': ['FORCE']})
    turn(table, mid, FOE)
    prompts = cast(combat, table, mid, 'Instrument of Qi: Thunder', OWNER,
        choices={'choice:needle.black_cauldron_swallow': None,
                 'choice:needle.black_cauldron_feed': ['THUNDER']})
    engine = reload(tmp_path, mid)
    assert not C.store(engine.state.actors[OWNER])
    assert not any(p['context']['reaction_source_id'] == 'choice:needle.black_cauldron_feed' for p in prompts)


def test_native_spit_cannot_repeat_on_later_pulse_of_same_field_after_reload(tmp_path, acquired):
    combat, table, mid = scenario(tmp_path, acquired, 18)
    attack(combat, table, mid)
    assert len(C.store(reload(tmp_path, mid).state.actors[OWNER])) == 2
    turn(table, mid, OWNER)
    cast(combat, table, mid, 'Heaven-Devouring Cauldron', at=(9, 6),
         choices={'choice:needle.black_cauldron_field_type': ['FORCE']})
    turn(table, mid, FOE)
    after_first = reload(tmp_path, mid)
    assert len(C.store(after_first.state.actors[OWNER])) == 1
    zone = C.fields(after_first, after_first.state.actors[OWNER])[0]
    assert zone.trigger_profile['cauldron_spit_used'] == [OWNER]
    turn(table, mid, OWNER)
    turn(table, mid, FOE)
    after_second = reload(tmp_path, mid)
    assert len(C.store(after_second.state.actors[OWNER])) == 1


def test_acquire_journey_combat_essence_resume_wait_scene_backlash_and_cold_reload(tmp_path, acquired):
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    bundles = [compile_character(acquired(3), actor_id=OWNER, reaction_plan={'ask': True}),
               compile_character(acquired(3, SOUND), actor_id=FOE, reaction_plan={'ask': True})]
    arena = combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena']
    journey = combat.journeys.create(bundles, arena,
        {OWNER: {'x': 3, 'y': 6}, FOE: {'x': 6, 'y': 6}}, {OWNER: 18000, FOE: 18000})
    jid = journey['journey_id']
    started = combat.journey_start_combat(jid, journey['revision'],
        {OWNER: 'team:keeper', FOE: 'team:hostile'}, maximum_rounds=1)
    mid = started['match_id']
    attack(combat, table, mid)
    for _ in range(6):
        if reload(tmp_path, mid).state.terminal_result is not None:
            break
        settle(table, mid, table.state(mid)['menu']['end_turn'])
    assert reload(tmp_path, mid).state.terminal_result is not None
    saved = combat.journey_state(jid)
    resumed = combat.journey_resume(jid, saved['revision'])
    from combat.ext.black_cauldron_journey import state
    source = state(combat.journeys.load(jid), OWNER)
    assert any(json.loads(c)['condition_id'] == C.STORE for c in source['conditions'])
    hp = resumed['actors'][OWNER]['encounter_snapshot']['current_hp']
    waited = combat.journey_act(jid, resumed['revision'], OWNER, 'wait', {'seconds': 60})
    assert waited['actors'][OWNER]['encounter_snapshot']['current_hp'] == hp, 'waiting does not end a scene'
    ended = combat.journey_end_scene(jid, waited['revision'], 'The hostile confrontation is resolved.')
    cold = CombatService(ROOT, tmp_path).journey_state(jid)
    assert cold == ended
    after = cold['actors'][OWNER]['encounter_snapshot']['current_hp']
    assert 1 <= hp - after <= 6
    stored = cold['actors'][OWNER]['source_states'][C.PARENT]['conditions']
    assert not next(json.loads(c)['data']['essences'] for c in stored if json.loads(c)['condition_id'] == C.STORE)
    consequence = next(e for e in cold['events'] if e['kind'] == 'SOURCE_CONSEQUENCE_RESOLVED')
    damage = [e for e in consequence['events'] if e['event_type'] == 'DAMAGE_COMMITTED' and OWNER in e['target_ids']]
    assert len(damage) == 1 and damage[0]['payload']['reduced_to'] == damage[0]['payload']['rolled_or_pending_damage']


def test_scene_resolution_guard_has_no_turn_start_or_prefight_benefits(tmp_path, acquired):
    from combat.journey_resolution import resolve
    combat = CombatService(ROOT, tmp_path)
    bundles = [compile_character(acquired(3), actor_id=OWNER)]
    journey = combat.journeys.create(bundles,
        combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'],
        {OWNER: {'x': 3, 'y': 6}}, {OWNER: 18000})
    session = combat.journeys.load(journey['journey_id'])
    before = deepcopy(session.state['actors'][OWNER]['resources'])
    engine = resolve(session, C.RESIDUE, lambda engine: None)
    assert not any(e.event_type in ('TURN_STARTED', 'ROUND_STARTED') for e in engine.events)
    assert all(a.turns_started == 0 for a in engine.state.actors.values())
    assert session.state['actors'][OWNER]['resources'] == before


@pytest.mark.parametrize('refine,remaining', [(False, 1), (True, 0)])
def test_native_spit_or_refine_spends_only_acquired_interception_essence_and_replays(tmp_path, acquired, refine, remaining):
    combat, table, mid = scenario(tmp_path, acquired, 14, fire=True)
    attack(combat, table, mid)
    assert len(C.store(reload(tmp_path, mid).state.actors[OWNER])) == 2
    turn(table, mid, OWNER)
    engine = reload(tmp_path, mid)
    options = [c for c in engine.legal_candidates() if c.target_ids == (FOE,)
               and (engine.action_catalog[c.source_definition_id].parameters.get('typed') or {}).get('source') == 'FIRE_BASE_IGNITE']
    assert options
    prompts = settle(table, mid, options[0].candidate_id, choices={
        'choice:needle.black_cauldron_refine': ['0', '1'] if refine else None,
        'choice:needle.black_cauldron_refinements': ['shell'],
        'choice:needle.black_cauldron_spit': None if refine else ['THUNDER']})
    after = reload(tmp_path, mid)
    assert len(C.store(after.state.actors[OWNER])) == remaining
    expected = C.REFINE if refine else C.RESIDUE
    packets = [e for e in after.events if e.event_type == 'DAMAGE_COMMITTED'
               and e.actor_id == OWNER and FOE in e.target_ids and e.payload.get('display_source_id') == expected]
    assert len(packets) == (2 if refine else 1)
    if refine:
        assert after.state.actors[OWNER].temporary_hp >= 2 * C.numbers(after, after.state.actors[OWNER])['pb']
    assert any(('Refine the Stolen Principle' if refine else 'Spit the Principle') in str(p) for p in prompts)


LAUGHING_TRIP = 'TAL_MONKEY_STYLE_LAUGHING_TRIP'


def weapon_scenario(tmp_path, acquired, cl=14, attacks=1, seed='CAULDRON-WEAPON', foe_resistance=None):
    """A Cauldron keeper whose damaging Qi feature is a weapon-delivered technique.

    Laughing Trip costs the Path pool and its own printed delivery is a weapon
    attack, so the compiler hands it the carried staff (typed ``weapon``). The
    foe owns a real Sound technique, so every Essence still comes from a hostile
    Qi effect. ``attacks`` > 1 reproduces the Extra Attack shape (more than one
    strike in the same activation) through the native attack loop.
    """
    from combat.canonical import canonical_sha256
    doc = acquired(cl)
    doc['spheres_and_talents'] = sheet([LAUGHING_TRIP], cl=cl)['spheres_and_talents']
    doc['equipment'] = [{'starting_kit': {'items': [{'item_id': 'tianxia.mortal.weapon.gun', 'quantity': 1}]}}]
    bundle = compile_character(doc, actor_id=OWNER, reaction_plan={'ask': True})
    assert any(row.get('display_name') == 'Laughing Trip'
               and ((row.get('parameters') or {}).get('typed') or {}).get('weapon')
               for row in bundle['action_catalog']), 'the staff must be the technique delivery'
    if attacks != 1:
        for row in bundle['action_catalog']:
            typed = (row.get('parameters') or {}).get('typed') or {}
            if row.get('display_name') == 'Laughing Trip' and typed.get('weapon'):
                for effect in typed.get('effects') or []:
                    if effect.get('type') == 'attack':
                        effect['count'] = attacks
        bundle.pop('bundle_sha256', None)
        bundle['bundle_sha256'] = canonical_sha256(bundle)
    def transform(bundles):
        if not foe_resistance:
            return
        from combat.canonical import canonical_sha256
        bundles[2].setdefault('typed_passives', []).append({
            'feature_id': 'test.resistance', 'block': 'defense', 'kind': 'resistance',
            'resource_id': '', 'damage_types': [foe_resistance], 'amount': 0, 'mundane_only': False,
            'attacks_only': False, 'martial_focus': False, 'requires_condition': None,
            'immune_below_cl': 0, 'attack_kinds': [], 'melee_only': False, 'once_per_round': False,
            'ac_base': 0, 'ac_ability': 'DEX', 'abilities': [], 'against': []})
        bundles[2].pop('bundle_sha256', None)
        bundles[2]['bundle_sha256'] = canonical_sha256(bundles[2])

    return fixture(tmp_path, [], owner_bundle=bundle, foe_sheet=acquired(3, SOUND), cl=cl,
                   positions={OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 5, 'y': 7}, FOE: {'x': 4, 'y': 6}},
                   ask=True, seed=seed, bundle_transform=transform)


WEAPON_REFINEMENT = {'choice:needle.black_cauldron_refine': ['0', '1'],
                     'choice:needle.black_cauldron_refinements': ['weapon'],
                     'choice:needle.black_cauldron_weapon_rider': ['THUNDER'],
                     'choice:needle.black_cauldron_refine_delivery': ['weapon']}


def swallow_round(combat, table, mid):
    """A hostile Sound technique reaches the keeper; the Residue reaction takes 1 Thunder Essence."""
    turn(table, mid, FOE)
    return cast(combat, table, mid, 'Instrument of Qi: Thunder', OWNER,
                choices={'choice:needle.black_cauldron_swallow': ['THUNDER'],
                         'choice:needle.black_cauldron_shell': ['hp']})


def weapon_refine(tmp_path, combat, table, mid):
    """Gather two hostile Thunder Essences (once per round), then refine a staff hit."""
    swallow_round(combat, table, mid)
    assert len(C.store(reload(tmp_path, mid).state.actors[OWNER])) == 1
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    swallow_round(combat, table, mid)
    assert len(C.store(reload(tmp_path, mid).state.actors[OWNER])) == 2
    turn(table, mid, OWNER)
    return settle(table, mid, candidate(combat, mid, 'Laughing Trip', target=FOE).candidate_id,
                  choices=WEAPON_REFINEMENT)


def refinement_packets(engine):
    return [e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED' and e.actor_id == OWNER
            and FOE in e.target_ids and e.payload.get('display_source_id') == C.REFINE]


def weapon_rider_packets(engine):
    """The rider is the only refinement packet delivered as its own typed packet.

    The per-Essence refinement damage rides the weapon packet (component
    ``weapon``); Weapon Refinement lands after the hit as an ``extra_damage``
    packet, which the engine stamps component ``technique``.
    """
    return [e for e in refinement_packets(engine)
            if (e.payload.get('damage_origin') or {}).get('component') == 'technique']


def test_weapon_refinement_offers_the_spent_principle_and_adds_one_d8_on_the_first_hit(tmp_path, acquired):
    """Lead ruling 2026-10-21: one spent Essence = 1d8 of its type on the first weapon hit."""
    combat, table, mid = weapon_scenario(tmp_path, acquired)
    prompts = weapon_refine(tmp_path, combat, table, mid)
    engine = reload(tmp_path, mid)
    assert any(p['context']['reaction_source_id'] == 'choice:needle.black_cauldron_weapon_rider'
               for p in prompts)
    assert any(p['context']['reaction_source_id'] == 'choice:needle.black_cauldron_refine_delivery'
               for p in prompts)
    # Two spent Essence add 1d8 each to the one weapon damage roll, then the rider
    # adds one more 1d8 of the chosen spent type after the first confirmed hit.
    assert len(refinement_packets(engine)) == 3
    riders = weapon_rider_packets(engine)
    assert len(riders) == 1
    assert str(riders[0].payload.get('damage_type')).upper() == 'THUNDER'
    assert int(riders[0].payload['rolled_or_pending_damage']) == 4
    assert not C.store(engine.state.actors[OWNER])


def test_weapon_refinement_critical_hit_rolls_two_d8(tmp_path, acquired, monkeypatch):
    combat, table, mid = weapon_scenario(tmp_path, acquired)
    fixed_dice(monkeypatch, [20] + [4] * 150)
    weapon_refine(tmp_path, combat, table, mid)
    engine = reload(tmp_path, mid)
    rolled = [e for e in engine.events if e.event_type == 'ATTACK_ROLLED' and e.actor_id == OWNER]
    assert [e.payload['natural_result'] for e in rolled] == [20]
    riders = weapon_rider_packets(engine)
    assert len(riders) == 1
    assert int(riders[0].payload['rolled_or_pending_damage']) == 8


def test_weapon_refinement_second_hit_of_one_activation_adds_nothing(tmp_path, acquired):
    combat, table, mid = weapon_scenario(tmp_path, acquired, attacks=2)
    weapon_refine(tmp_path, combat, table, mid)
    engine = reload(tmp_path, mid)
    assert len([e for e in engine.events if e.event_type == 'ATTACK_ROLLED' and e.actor_id == OWNER]) == 2
    # Two per-Essence packets on the one chosen roll plus the single rider; a
    # second weapon hit in the same activation must not add another rider.
    assert len(refinement_packets(engine)) == 3
    assert len(weapon_rider_packets(engine)) == 1


def devour_disclosures(engine):
    return [e for e in engine.events if e.event_type == 'PASSIVE_TRIGGERED'
            and (e.payload.get('devoured_resistance') or {}).get('form')]


def test_refine_discloses_the_form_of_the_resistance_that_reduced_its_extra_damage(tmp_path, acquired):
    """CL14 "Devour the Resistance": learn the category of that Resistance, never its full source."""
    combat, table, mid = weapon_scenario(tmp_path, acquired, foe_resistance='THUNDER')
    weapon_refine(tmp_path, combat, table, mid)
    engine = reload(tmp_path, mid)
    told = devour_disclosures(engine)
    assert len(told) == 1, 'one disclosure per creature and principle, not one per added packet'
    assert told[0].actor_id == OWNER and FOE in told[0].target_ids
    assert told[0].payload['devoured_resistance'] == {'damage_type': 'THUNDER', 'form': 'natural'}
    assert 'natural toughness' in told[0].payload['log']
    assert 'test.resistance' not in told[0].payload['log'], 'the full source is not revealed'
    # The printed wording also tells the player what it was about: the added
    # damage, this creature, and the ability that added it.
    assert 'Refine the Stolen Principle' in told[0].payload['log']
    assert 'Hostile musician' in told[0].payload['log']


def test_refine_says_nothing_when_no_resistance_reduced_the_extra_damage(tmp_path, acquired):
    """Absent Resistance the keeper is told nothing, so the disclosure is not a blanket log line."""
    combat, table, mid = weapon_scenario(tmp_path, acquired)
    weapon_refine(tmp_path, combat, table, mid)
    engine = reload(tmp_path, mid)
    assert len(refinement_packets(engine)) == 3
    assert not devour_disclosures(engine)


def digest_scenario(tmp_path, acquired, *, effect_near):
    """A hostile Sound technique whose lasting effect is on a bearer.

    Printed CL6: "A qualifying hostile Qi-powered effect within 60 feet ends".
    The effect's own place decides, so the bearer is either 10 feet from the
    keeper while its user stands 70 feet away, or the reverse.
    """
    positions = ({OWNER: {'x': 3, 'y': 12}, ALLY: {'x': 5, 'y': 12}, FOE: {'x': 17, 'y': 12}}
                 if effect_near else
                 {OWNER: {'x': 3, 'y': 12}, ALLY: {'x': 17, 'y': 12}, FOE: {'x': 5, 'y': 12}})
    return scenario(tmp_path, acquired, 6, enemy_cl=6, positions=positions)


def expire_hostile_effect(tmp_path, combat, table, mid):
    """The hostile note's lasting penalty ends at its user's next turn start."""
    turn(table, mid, FOE)
    cast(combat, table, mid, 'Instrument of Qi: Thunder', ALLY)
    assert not C.store(reload(tmp_path, mid).state.actors[OWNER]), 'the keeper was not the effect recipient'
    turn(table, mid, OWNER)
    turn(table, mid, FOE)
    return reload(tmp_path, mid)


@pytest.mark.parametrize('effect_near,expected', [(True, ['THUNDER']), (False, [])])
def test_digest_broken_art_measures_the_ended_effect_not_its_user(tmp_path, acquired, monkeypatch,
                                                                  effect_near, expected):
    fixed_dice(monkeypatch, [1] + [4] * 150)  # the ally fails its save, so the note leaves a lasting effect
    combat, table, mid = digest_scenario(tmp_path, acquired, effect_near=effect_near)
    engine = expire_hostile_effect(tmp_path, combat, table, mid)
    assert [e['type'] for e in C.store(engine.state.actors[OWNER])] == expected


def hostile_fire_scenario(tmp_path, acquired, cl=10, mixed=False, features=()):
    """A hostile Fire cultivator whose ranged Qi attack is the keeper's trigger.

    ``mixed`` adds one Cold damage leaf and a Cold-carried rider to the same
    hit, so the swallowed Fire packet is one type of a two-type activation.
    """
    owner_doc = acquired(cl) if not features else acquired_sheet(cl, features=features)
    bundle = compile_character(owner_doc, actor_id=OWNER, reaction_plan={'ask': True})
    foe = sheet(['FIRE_BASE_IGNITE'], cl=cl)

    def transform(bundles):
        if not mixed:
            return
        from combat.canonical import canonical_sha256
        target = next(row for row in bundles[2]['action_catalog']
                      if row.get('display_name') == 'Ignite: Push Target')
        hit = target['parameters']['typed']['effects'][0]['on_hit']
        hit.append({'type': 'damage', 'applies_to': 'target',
                    'dice': {'count': 1, 'sides': 6}, 'damage_types': ['cold'],
                    'evidence': 'A cold snap rides the same hit.'})
        hit.append({'type': 'condition', 'condition': 'frostbite', 'applies_to': 'target',
                    'damage_types': ['cold'],
                    'evidence': 'Hit: the Cold damage leaves the target Frostbitten.'})
        # Unmarked damage types: the row's own wording is the only statement of
        # which packet carries it, and it names the OTHER type of this activation.
        hit.append({'type': 'condition', 'condition': 'numbed', 'applies_to': 'target',
                    'evidence': 'Hit: the Cold damage leaves the target Numbed.'})
        bundles[2].pop('bundle_sha256', None)
        bundles[2]['bundle_sha256'] = canonical_sha256(bundles[2])

    return fixture(tmp_path, [], owner_bundle=bundle, foe_sheet=foe, cl=cl,
                   positions={OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 4, 'y': 6}, FOE: {'x': 7, 'y': 6}},
                   ask=True, seed='CAULDRON-RIDER', bundle_transform=transform)


def test_swallow_art_full_reduction_removes_the_rider_carried_by_that_type(tmp_path, acquired):
    """CL10: at a full reduction, damage-dependent riders carried by that type fail."""
    combat, table, mid = hostile_fire_scenario(tmp_path, acquired)
    hp = reload(tmp_path, mid).state.actors[OWNER].current_hp
    turn(table, mid, FOE)
    prompts = cast(combat, table, mid, 'Ignite: Push Target', OWNER,
                   choices={'choice:needle.black_cauldron_swallow': ['FIRE'],
                            'choice:needle.black_cauldron_shell': ['hp']})
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    assert any('Swallow the Art' in str(p) for p in prompts)
    assert [e['type'] for e in C.store(owner)] == ['FIRE', 'FIRE']
    assert owner.current_hp == hp, 'the whole Fire packet was swallowed'
    assert not C.condition(owner, 'condition:typed.burning'), 'Burn is carried solely by the swallowed Fire damage'
    assert owner.temporary_hp == 2 * int(C.numbers(engine, owner)['pb'])


def test_swallow_art_mixed_types_keep_the_other_type_and_its_own_rider(tmp_path, acquired):
    """CL10: "damage-dependent riders carried solely by that type" fail, not the other type's damage."""
    combat, table, mid = hostile_fire_scenario(tmp_path, acquired, mixed=True)
    hp = reload(tmp_path, mid).state.actors[OWNER].current_hp
    turn(table, mid, FOE)
    cast(combat, table, mid, 'Ignite: Push Target', OWNER,
         choices={'choice:needle.black_cauldron_swallow': ('FIRE', None),
                  'choice:needle.black_cauldron_shell': ['save']})
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    assert [e['type'] for e in C.store(owner)] == ['FIRE', 'FIRE']
    assert owner.current_hp == hp - 4, 'the Cold packet still resolves against the keeper'
    assert not C.condition(owner, 'condition:typed.burning'), 'Burn rides the swallowed Fire damage'
    assert C.condition(owner, 'condition:typed.frostbite'), 'the Cold rider is independent of the Fire packet'
    assert C.condition(owner, 'condition:typed.numbed'), \
        'a rider that names the other type in its own wording is not carried by the swallowed one'


def test_digest_measures_a_moved_zone_at_its_ending_position(tmp_path, acquired):
    """CL6: "A qualifying hostile Qi-powered effect within 60 feet ends". A trailing area is
    created 65 feet away and walks into range before it ends, so only its final centre qualifies."""
    combat, table, mid = trailing_aura_scenario(tmp_path, acquired, near=False)
    engine = expire_trailing_aura(tmp_path, combat, table, mid)
    assert [e['type'] for e in C.store(engine.state.actors[OWNER])] == ['THUNDER']


def test_digest_does_not_award_a_zone_that_walked_out_of_range(tmp_path, acquired):
    """The same area created 35 feet away and walked past 60 feet before it ends awards nothing."""
    combat, table, mid = trailing_aura_scenario(tmp_path, acquired, near=True)
    engine = expire_trailing_aura(tmp_path, combat, table, mid)
    assert not C.store(engine.state.actors[OWNER])


def trailing_aura_scenario(tmp_path, acquired, *, near):
    """A hostile Sound cultivator's aura that rides its creator beside the keeper."""
    bundle = compile_character(acquired(6), actor_id=OWNER, reaction_plan={'ask': True})
    start = {'x': 10, 'y': 12} if near else {'x': 16, 'y': 12}

    def transform(bundles):
        from combat.canonical import canonical_sha256
        foe = bundles[2]
        foe['actor_template']['action_ids'].append('action:test.digest.trail')
        foe['action_catalog'].append({
            'source_definition_id': 'action:test.digest.trail', 'display_name': 'Trailing Thunder Aura',
            'owner_id': FOE, 'economy': 'ACTION', 'resolution_kind': 'TYPED', 'target_kind': 'ANY_CREATURE',
            'range_ft': 120, 'costs': [['resource:core.qi', 1]],
            'parameters': {'typed': {
                'source': 'tianxia.subpath.qi.sound_cultivator.feature.instrument_of_qi',
                'numbers': {'cl': 6, 'save_dc': 10, 'pb': 2, 'key_mod': 0},
                'duration': {'kind': 'instant', 'concentration': False},
                'effects': [{'type': 'damage', 'applies_to': 'target', 'flat': 1, 'damage_types': ['thunder']}],
                'zone_spec': {'name': 'Trailing Thunder Aura', 'shape': 'sphere', 'size_ft': 10,
                    'centered_on_self': True, 'follows_owner': True,
                    'duration': {'kind': 'until_start_of_next_turn', 'concentration': False},
                    'source_profile': {'mechanic_id': 'tianxia.subpath.qi.sound_cultivator.feature.instrument_of_qi',
                                       'source_cl': 6}}}}})
        foe.pop('bundle_sha256', None)
        foe['bundle_sha256'] = canonical_sha256(foe)

    places = {OWNER: {'x': 3, 'y': 12}, ALLY: {'x': 4, 'y': 12}, FOE: start}
    return fixture(tmp_path, [], owner_bundle=bundle, foe_sheet=acquired(6, SOUND), cl=6,
                   positions=places, ask=True, seed='CAULDRON-TRAIL',
                   bundle_transform=transform)


def _trailing_zone(engine):
    return next(z for z in engine.state.zones.values()
                if z.trigger_profile.get('name') == 'Trailing Thunder Aura')


def expire_trailing_aura(tmp_path, combat, table, mid):
    """The hostile aura follows its user 30 feet, then ends at that user's next turn start."""
    turn(table, mid, FOE)
    cast(combat, table, mid, 'Trailing Thunder Aura', OWNER,
         choices={'choice:needle.black_cauldron_swallow': None})
    engine = reload(tmp_path, mid)
    walk = {'x': 10, 'y': 12} if _trailing_zone(engine).center.x >= 14 else {'x': 16, 'y': 12}
    settle(table, mid, _move_candidate(combat, mid, walk))
    moved = reload(tmp_path, mid)
    zone = _trailing_zone(moved)
    assert (zone.center.x, zone.center.y) == (walk['x'], walk['y']), 'the area rides its creator'
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    turn(table, mid, FOE)  # its next turn start ends the one-round aura
    return reload(tmp_path, mid)


def _move_candidate(combat, mid, cell):
    engine = combat._load_session(mid).engine
    return next(c.candidate_id for c in engine.legal_candidates()
                if c.display_name.startswith('Move') and c.destination
                and (c.destination.x, c.destination.y) == (cell['x'], cell['y']))


def test_cauldron_shell_armament_destinations_are_labelled(tmp_path, acquired):
    """Checklist 13: a destination choice names the square it moves the Armament to."""
    from combat.ext import qi_path
    combat, table, mid = hostile_fire_scenario(tmp_path, acquired, cl=10,
        features=['tianxia.path.qi_cultivation.feature.domain_armament'])
    cast(combat, table, mid, 'Domain Armament: Manifest', at=(2, 6))
    turn(table, mid, FOE)
    prompts = cast(combat, table, mid, 'Ignite: Push Target', OWNER,
        choices={'choice:needle.black_cauldron_swallow': ['FIRE'],
                 'choice:needle.black_cauldron_shell': ['armament'],
                 'choice:needle.black_cauldron_armament': ['0']})
    prompt = next(p for p in prompts
                  if p['context']['reaction_source_id'] == 'choice:needle.black_cauldron_armament')
    options = prompt['choice']['options']
    assert options
    assert all('square' in option['label'] and 'feet high' in option['label'] for option in options)
    assert all(option['label'] != option['id'] for option in options)
    label = next(option['label'] for option in options if option['id'] == '0')
    x, y = (int(part) for part in label.split('square ')[1].split(',')[:2])
    engine = reload(tmp_path, mid)
    assert qi_path.armament_point(engine.state.actors[OWNER]) == (x, y), \
        'the chosen index moves the Armament to the square its label named'
