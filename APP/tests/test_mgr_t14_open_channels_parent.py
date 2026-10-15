"""Open Channels through freshly compiled characters and native table replay."""
import pytest
from tests.test_a2_foundations3 import owner_bundle, pool
from tests.worker2_support import OWNER, ALLY, fixture, reload

from combat.factory_compiler import compile_character
from tests.h1_support import sheet
from tests.test_a2_foundations3 import wall_on_support_ray
from tests.test_a2_foundations3 import add_action
from tests.worker2_support import FOE, act, candidate, settle, turn, sealed_native_attack

GUARD = 'foundation.origin_spirit_body_v0_2B.returning_source_guard'
WARD = 'tianxia.talent.ash.ash_ward'


def reduction_fight(tmp_path, *, stage='Refined', ally_x=12, walled=False,
                    ward=False, ask=True):
    doc = sheet([GUARD] + ([WARD] if ward else []), name='Wren', foundation={
        'foundation_id': 'origin_spirit_body_v0_2B', 'stage': stage,
        'resource': {'name': 'Spirit-Source Dew', 'resource_id': 'tianxia.resource.test',
                     'maximum': 1, 'current': 0 if ward else 1}})
    bundle = compile_character(doc, actor_id=OWNER, reaction_plan={'ask': ask})
    def delivery(bundles):
        sealed_native_attack(bundles[2], 'Native strike', damage_type='FORCE',
                             modifier=20, attack_bonus=100, range_ft=120)
    def arena(arena):
        arena['terrain_regions'] = [r for r in arena['terrain_regions']
                                    if r['region_id'] != 'pillar.centre']
        if walled:
            wall_on_support_ray(arena)
    return fixture(tmp_path, [], owner_bundle=bundle, bundle_transform=delivery,
                   seed='OPEN-CHANNELS-REDUCTION', named=True,
                   ally_position={'x': ally_x, 'y': 6},
                   foe_position={'x': ally_x, 'y': 8}, battlefield_transform=arena)


@pytest.mark.parametrize('stage,ally_x,walled,expected', [
    ('Refined', 12, False, True), ('Refined', 15, False, True),
    ('Refined', 16, False, False), ('Refined', 12, True, False),
    ('Awakened', 12, False, False), ('Awakened', 9, False, True)])
def test_open_channels_native_guard_range_payment_and_generation(tmp_path, stage, ally_x, walled, expected):
    combat, table, mid = reduction_fight(tmp_path, stage=stage, ally_x=ally_x, walled=walled)
    turn(table, mid, FOE)
    before = reload(tmp_path, mid)
    cid = candidate(combat, mid, 'Native strike', target=ALLY).candidate_id
    for _ in range(2):
        if expected:
            assert act(table, mid, cid, [])['status'] == 'REACTION_REQUIRED'
        else:
            table.state(mid)
        preview = reload(tmp_path, mid)
        assert preview.state.model_dump() == before.state.model_dump()
        assert len(preview.events) == len(before.events)
    prompts = settle(table, mid, cid, picks={'reaction:typed.' + GUARD: 'first'})
    engine = reload(tmp_path, mid)
    receipts = [e for e in engine.events if e.event_type == 'REACTION_RESOLVED'
                and e.source_definition_id == GUARD]
    assert bool(receipts) is expected
    assert engine.state.actors[OWNER].reaction_available is (not expected)
    assert engine.state.actors[OWNER].resources[pool('spirit')] == 1
    if expected:
        receipt = receipts[-1]
        assert receipt.actor_id == OWNER and receipt.payload['protects'] == ALLY
        assert receipt.payload['reduction'] > 0
        spend = [e for e in engine.events if e.event_type == 'RESOURCE_SPENT'
                 and e.actor_id == OWNER and e.source_definition_id == GUARD]
        assert len(spend) == 1
        # The newly generated point cannot fund another spend on this event.
        grants = [e for e in engine.events if e.event_type == 'RESOURCE_GAINED'
                  and e.actor_id == OWNER]
        assert grants and grants[-1].sequence > spend[0].sequence


def test_open_channels_never_expands_unrelated_ash_ward(tmp_path):
    combat, table, mid = reduction_fight(tmp_path, ward=True)
    turn(table, mid, FOE)
    prompts = settle(table, mid, candidate(combat, mid, 'Native strike', target=ALLY).candidate_id,
                     picks={'reaction:typed.' + WARD: 'first'})
    engine = reload(tmp_path, mid)
    assert not prompts
    assert engine.state.actors[OWNER].resources[pool('spirit')] == 0
    assert not any(e.event_type == 'REACTION_RESOLVED' and e.source_definition_id == WARD
                   for e in engine.events)


def test_open_channels_extension_is_for_supported_allies(tmp_path):
    def delivery(bundles):
        add_action(bundles[0], 'Outward grant', [{'type': 'temp_hp', 'flat': 7, 'applies_to': 'target'}],
                   target_kind='ANY_CREATURE')
    def arena(arena):
        arena['terrain_regions'] = [r for r in arena['terrain_regions'] if r['region_id'] != 'pillar.centre']
    combat, table, mid = fixture(tmp_path, [], owner_bundle=owner_bundle('spirit', 0, 'Refined'),
        bundle_transform=delivery, ally_position={'x': 12, 'y': 6},
        team_overrides={ALLY: 'team:opponents'}, battlefield_transform=arena)
    settle(table, mid, candidate(combat, mid, 'Outward grant', target=ALLY).candidate_id)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[ALLY].temporary_hp == 7
    assert engine.state.actors[OWNER].resources[pool('spirit')] == 0


def luck_support_fight(tmp_path, *, ally_x=12, stage='Refined', walled=False, seed='OPEN-LUCK-1', control=False, feed=False, automatic=False):
    talents = ['PROTECTION_BASE_AEGIS', 'PROTECTION_BASE_ARMORED_AEGIS',
               'PROTECTION_BASE_SUCCOR', 'tianxia.talent.protection.luck', GUARD]
    doc = sheet(talents, cl=15, name='Wren', foundation={
        'foundation_id': 'origin_spirit_body_v0_2B', 'stage': stage,
        'resource': {'name': 'Spirit-Source Dew', 'resource_id': 'tianxia.resource.test',
                     'maximum': 1, 'current': int(feed)}})
    plan = {'off': [GUARD]} if feed and automatic else {'ask': True}
    bundle = compile_character(doc, actor_id=OWNER, reaction_plan=plan)
    def delivery(bundles):
        sealed_native_attack(bundles[2], 'Native strike', damage_type='FORCE',
                             modifier=1, attack_bonus=100, range_ft=120)
    def arena(arena):
        arena['terrain_regions'] = [r for r in arena['terrain_regions']
                                    if r['region_id'] != 'pillar.centre']
        if walled:
            wall_on_support_ray(arena)
    combat, table, mid = fixture(tmp_path, [], owner_bundle=bundle, bundle_transform=delivery,
        ally_talents=['PROTECTION_BASE_AEGIS', 'PROTECTION_BASE_ARMORED_AEGIS'],
        seed=seed, named=True, ally_score=12, ally_position={'x': 4, 'y': 6},
        foe_position={'x': ally_x, 'y': 8}, battlefield_transform=arena,
        foe_sheet=sheet(['tianxia.talent.warleader.frightful_roar'], dc=15) if control else None)
    if not feed:
        settle(table, mid, candidate(combat, mid, 'Aegis: Armored Aegis (Persistent)', target=ALLY).candidate_id)
    turn(table, mid, ALLY)
    settle(table, mid, candidate(combat, mid, 'Aegis: Armored Aegis', target=ALLY).candidate_id)
    # The supporter never teleports a test target: movement is paid and journaled.
    waypoints = ([(8, 5)] if walled else [(9, 6)])
    if ally_x > 15:
        waypoints.append((15, 6))
    waypoints.append((ally_x, 6))
    for index, (x, y) in enumerate(waypoints):
        rows = [c for c in combat._load_session(mid).engine.legal_candidates()
                if c.destination is not None and c.destination.x == x and c.destination.y == y
                and c.source_definition_id == 'system:combat.movement']
        assert rows, [(c.source_definition_id, c.destination) for c in combat._load_session(mid).engine.legal_candidates() if c.destination]
        settle(table, mid, rows[0].candidate_id)
        if index < len(waypoints) - 1:
            turn(table, mid, OWNER)
            turn(table, mid, ALLY)
    turn(table, mid, FOE)
    assert reload(tmp_path, mid).state.actors[ALLY].concentration is not None
    return combat, table, mid


@pytest.mark.parametrize('stage,ally_x,walled,automatic,expected', [
    ('Refined', 12, False, False, 1), ('Refined', 15, False, False, 1),
    ('Refined', 16, False, False, 0), ('Refined', 12, True, False, 0),
    ('Awakened', 12, False, False, 0), ('Refined', 12, False, True, 1)])
def test_open_channels_native_luck_maintenance_at_45_ft(tmp_path, stage, ally_x, walled, automatic, expected):
    combat, table, mid = luck_support_fight(tmp_path, stage=stage, ally_x=ally_x, walled=walled)
    if automatic:
        combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    cid = candidate(combat, mid, 'Native strike', target=ALLY).candidate_id
    before = reload(tmp_path, mid)
    if not automatic:
        for _ in range(2):
            assert act(table, mid, cid, [])['status'] == 'REACTION_REQUIRED'
            preview = reload(tmp_path, mid)
            assert preview.state.model_dump() == before.state.model_dump()
            assert len(preview.events) == len(before.events)
    prompts = settle(table, mid, cid, picks={'reaction:typed.tianxia.talent.protection.luck': 'first'})
    engine = reload(tmp_path, mid)
    rolls = [e.payload for e in engine.events if e.event_type == 'SAVE_ROLLED'
             and e.source_definition_id == 'system:combat.concentration']
    rewrites = [e.payload for e in engine.events if e.event_type == 'D20_REWRITTEN']
    assert rewrites, (prompts, rolls)
    assert engine.state.actors[ALLY].concentration is not None, (rewrites, rolls)
    assert engine.state.actors[OWNER].resources[pool('spirit')] == expected, (rewrites, rolls, prompts)
    assert bool(prompts) is (not automatic)


def test_open_channels_native_control_support(tmp_path):
    combat, table, mid = luck_support_fight(tmp_path, control=True, seed='OPEN-CONTROL-1')
    engine = reload(tmp_path, mid)
    names = sorted({engine.action_catalog[c.source_definition_id].display_name
                    for c in engine.legal_candidates() if c.source_definition_id in engine.action_catalog})
    name = next((n for n in names if 'Frightful Roar' in n), None)
    assert name, names
    prompts = settle(table, mid, candidate(combat, mid, name).candidate_id,
        picks={'reaction:typed.tianxia.talent.protection.luck': 'first'})
    engine = reload(tmp_path, mid)
    rewrites = [e for e in engine.events if e.event_type == 'D20_REWRITTEN']
    assert rewrites, [(e.source_definition_id, e.payload.get('natural_result'), e.payload.get('success'))
                      for e in engine.events if e.event_type == 'SAVE_ROLLED']
    assert not any(c.condition_id.endswith('.frightened') for c in engine.state.actors[ALLY].conditions.values())
    assert engine.state.actors[OWNER].resources[pool('spirit')] == 1, prompts


@pytest.mark.parametrize('stage,ally_x,walled,automatic,expected', [
    ('Refined', 12, False, False, True), ('Refined', 15, False, False, True),
    ('Refined', 16, False, False, False), ('Refined', 12, True, False, False),
    ('Awakened', 12, False, False, False), ('Refined', 12, False, True, True)])
def test_open_channels_native_feed_maintenance_reach(tmp_path, stage, ally_x, walled, automatic, expected):
    from tests.test_mgr_t14_spirit_feed import FEED, REACTION, ACCEPT
    combat, table, mid = luck_support_fight(tmp_path, stage=stage, ally_x=ally_x,
                                           walled=walled, feed=True, automatic=automatic)
    if automatic:
        for actor in (OWNER, ALLY):
            combat.set_controller_mode(mid, actor_id=actor, controller_mode='LOCAL_AUTO')
    before = reload(tmp_path, mid)
    cid = candidate(combat, mid, 'Native strike', target=ALLY).candidate_id
    if expected and not automatic:
        for _ in range(2):
            assert act(table, mid, cid, [])['status'] == 'REACTION_REQUIRED'
            preview = reload(tmp_path, mid)
            assert preview.state.model_dump() == before.state.model_dump()
            assert len(preview.events) == len(before.events)
    prompts = settle(table, mid, cid, choices={REACTION: 'first', ACCEPT: 'accept'})
    engine = reload(tmp_path, mid)
    spends = [e for e in engine.events if e.event_type == 'RESOURCE_SPENT'
              and e.source_definition_id == FEED]
    assert bool(spends) is expected
    assert (engine.state.actors[ALLY].concentration is not None) is expected
    assert engine.state.actors[ALLY].temporary_hp == (4 if expected else 0)
    assert engine.state.actors[OWNER].resources[pool('spirit')] == 1
    assert engine.state.actors[OWNER].reaction_available is (not expected)
    if expected:
        assert len(spends) == 1
        grants = [e for e in engine.events if e.event_type == 'RESOURCE_GAINED' and e.actor_id == OWNER]
        assert len(grants) == 1 and grants[0].sequence > spends[0].sequence
        assert bool(prompts) is (not automatic)
        if automatic:
            for actor in (OWNER, ALLY):
                combat.set_controller_mode(mid, actor_id=actor, controller_mode='MANUAL')
        turn(table, mid, OWNER); turn(table, mid, ALLY)
        assert reload(tmp_path, mid).state.actors[OWNER].resources[pool('spirit')] == 0


def test_d20_reach_does_not_import_unrelated_generic_range_bonus(tmp_path, monkeypatch):
    from combat.ext import reaction_ranges
    from tests.test_mgr_t14_spirit_feed import FEED, REACTION, ACCEPT
    original = reaction_ranges.run_strict
    def generic_bonus(point, *args, **kwargs):
        if point == 'reaction_range_bonus' and args[2] == FEED:
            return [30]
        return original(point, *args, **kwargs)
    monkeypatch.setattr(reaction_ranges, 'run_strict', generic_bonus)
    combat, table, mid = luck_support_fight(tmp_path, stage='Awakened', feed=True)
    settle(table, mid, candidate(combat, mid, 'Native strike', target=ALLY).candidate_id,
        choices={REACTION: 'first', ACCEPT: 'accept'})
    engine = reload(tmp_path, mid)
    assert not any(e.event_type == 'RESOURCE_SPENT' and e.source_definition_id == FEED for e in engine.events)
    assert engine.state.actors[ALLY].concentration is None


def native_life_support_at_range(tmp_path, stage, ally_x):
    from tests.test_mgr_t14_spirit_vessel_value import VESSEL
    talents = [VESSEL, 'tianxia.talent.life.greater_invigorate',
               'tianxia.talent.life.pulse_array_treatment']
    doc = sheet(talents, cl=15, name='Wren', foundation={
        'foundation_id': 'origin_spirit_body_v0_2B', 'stage': stage,
        'resource': {'name': 'Spirit-Source Dew', 'resource_id': 'tianxia.resource.test',
                     'maximum': 1, 'current': 0}})
    bundle = compile_character(doc, actor_id=OWNER, reaction_plan={'ask': True})
    def arena(arena):
        arena['terrain_regions'] = [r for r in arena['terrain_regions']
                                    if r['region_id'] != 'pillar.centre']
    def delivery(bundles):
        sealed_native_attack(bundles[2], 'Native strike', damage_type='FORCE',
                             modifier=20, attack_bonus=100, range_ft=120)
    combat, table, mid = fixture(tmp_path, [], owner_bundle=bundle, named=True,
        seed='OPEN-VESSEL-RANGE', ally_position={'x': 4, 'y': 6},
        foe_position={'x': ally_x, 'y': 8}, battlefield_transform=arena, bundle_transform=delivery)
    settle(table, mid, candidate(combat, mid, 'Read the Pulse', target=ALLY).candidate_id)
    turn(table, mid, ALLY)
    waypoints = [9] + ([15] if ally_x > 15 else []) + [ally_x]
    for index, x in enumerate(waypoints):
        rows = [c for c in combat._load_session(mid).engine.legal_candidates()
                if c.destination is not None and (c.destination.x, c.destination.y) == (x, 6)
                and c.source_definition_id == 'system:combat.movement']
        assert rows
        settle(table, mid, rows[0].candidate_id)
        if index < len(waypoints) - 1:
            turn(table, mid, OWNER); turn(table, mid, ALLY)
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Native strike', target=ALLY).candidate_id)
    turn(table, mid, OWNER)
    return combat, table, mid


@pytest.mark.parametrize('stage,ally_x,expected_bonus', [('Refined', 12, 4),
    ('Refined', 15, 4), ('Refined', 16, 0), ('Awakened', 12, 0)])
def test_open_channels_native_vessel_uses_same_context_range(tmp_path, stage, ally_x, expected_bonus):
    from tests.test_mgr_t14_spirit_vessel_value import CHOICE, ROUND
    combat, table, mid = native_life_support_at_range(tmp_path, stage, ally_x)
    engine = reload(tmp_path, mid)
    sources = [(c, engine.action_catalog[c.source_definition_id]) for c in engine.legal_candidates()
               if c.source_definition_id in engine.action_catalog]
    candidates = [(c, a) for c, a in sources if a.parameters.get('typed', {}).get('source') == 'LIFE_BASE_BORROWED_BREATH'
                  and 'Pulse Array' in a.display_name and c.target_ids == (ALLY,)]
    assert candidates, sorted({a.display_name for c, a in sources})
    candidate_row, action = candidates[0]
    assert action.range_ft == 120  # source reach stays native; Foundation stops at 60
    before_qi = engine.state.actors[OWNER].resources['resource:core.qi']
    prompts = settle(table, mid, candidate_row.candidate_id, picks={CHOICE: 'increase'})
    engine = reload(tmp_path, mid)
    receipts = [e for e in engine.events if e.payload.get('receipt_kind') == 'origin_spirit_support_value']
    assert bool(receipts) is bool(expected_bonus), prompts
    if expected_bonus:
        assert receipts[-1].target_ids == (ALLY,)
        assert receipts[-1].payload['bonus'] == expected_bonus
        assert type(engine.state.actors[OWNER].turn_flags[ROUND]) is int
    else:
        assert ROUND not in engine.state.actors[OWNER].turn_flags
    assert engine.state.actors[OWNER].resources['resource:core.qi'] == before_qi - sum(
        cost for resource, cost in action.costs if resource == 'resource:core.qi')
    assert engine.state.actors[OWNER].resources[pool('spirit')] == int(bool(expected_bonus))


@pytest.mark.parametrize('ally_x,expected', [(12, 1), (16, 0)])
def test_native_healing_uses_the_same_generation_context(tmp_path, ally_x, expected):
    combat, table, mid = native_life_support_at_range(tmp_path, 'Refined', ally_x)
    before = reload(tmp_path, mid)
    candidates = [c for c in before.legal_candidates()
        if c.source_definition_id in before.action_catalog
        and before.action_catalog[c.source_definition_id].parameters.get('typed', {}).get('source') == 'LIFE_BASE_MEND_THE_PULSE'
        and 'Pulse Array' in before.action_catalog[c.source_definition_id].display_name
        and c.target_ids == (ALLY,)]
    assert candidates
    action = before.action_catalog[candidates[0].source_definition_id]
    assert action.range_ft == 120
    settle(table, mid, candidates[0].candidate_id)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[ALLY].current_hp > before.state.actors[ALLY].current_hp
    receipts = [e for e in engine.events if e.event_type == 'HEALING_APPLIED'
        and e.actor_id == OWNER and e.source_definition_id == action.source_definition_id]
    assert receipts and receipts[-1].target_ids == (ALLY,)
    assert engine.state.actors[OWNER].resources[pool('spirit')] == expected


@pytest.mark.parametrize('stage,expected', [('Awakened', 60), ('Refined', 60), ('Perfected', 60)])
def test_open_channels_maximum_hp_native_reload(tmp_path, stage, expected):
    bundle = owner_bundle('spirit', 0, stage)
    assert bundle['actor_template']['maximum_hp'] == expected
    combat, table, mid = fixture(tmp_path, [], owner_bundle=bundle)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].maximum_hp == expected
    assert engine.state.actors[OWNER].current_hp == expected
    assert engine.state.actors[ALLY].maximum_hp == 60
    assert engine.state.actors[OWNER].resources[pool('spirit')] == 0
