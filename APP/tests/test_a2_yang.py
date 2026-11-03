"""Yang follow-up benefits through real table transactions and cold replay."""
import pytest

from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, turn, reload
from tests.test_carry import KIT
from tests.test_auto35_yang import _seal, _add_action, _native_save_action
SUNLIT = 'TAL_YANG_SUNLIT_OPENING'
SUNLIT_CONDITION = 'condition:typed.sunlit_opening'


def sunlit_picks(ally=ALLY, target=FOE):
    return {'choice:needle.yang_aim_attack': 'use',
            'choice:needle.yang_aim_save': FOE,
            'choice:needle.sunlit_opening': f'{ally}|{target}'}


def sunlit_conditions(engine, actor=ALLY):
    return [c for c in engine.state.actors[actor].conditions.values()
            if c.condition_id.startswith(SUNLIT_CONDITION + '.')]


@pytest.mark.parametrize('native', [False, True])
@pytest.mark.parametrize('hit', [False, True])
def test_sunlit_opening_settled_attack_and_consumption(tmp_path, native, hit):
    from tests.worker2_support import sealed_native_attack
    def prepare(bundles):
        bundles[2]['actor_template']['armor_class'] = 0 if hit else 1000
        for bundle in bundles[:2]:
            if native:
                sealed_native_attack(bundle, 'Opening shot', attack_bonus=100)
            _seal(bundle)
        _seal(bundles[2])
    combat, table, mid = fixture(tmp_path, [SUNLIT], seed='A2-YANG-OPEN',
                                owner_kit={'starting_kit': KIT}, ally_kit={'starting_kit': KIT},
                                foe_position={'x': 4, 'y': 5}, bundle_transform=prepare)
    settle(table, mid, candidate(combat, mid, 'Kindle the Rising', target=OWNER).candidate_id)
    name = 'Opening shot' if native else 'Bi Shou (Dagger) attack'
    prompts = settle(table, mid, candidate(combat, mid, name, target=FOE).candidate_id, sunlit_picks())
    engine = reload(tmp_path, mid)
    assert bool(sunlit_conditions(engine)) == hit
    assert any(p['context']['reaction_source_id'] == 'choice:needle.sunlit_opening' for p in prompts) == hit
    assert engine.state.actors[OWNER].resources['resource:core.qi'] == 100
    if hit:
        turn(table, mid, ALLY)
        settle(table, mid, candidate(combat, mid, name, target=FOE).candidate_id)
        engine = reload(tmp_path, mid)
        roll = [e for e in engine.events if e.event_type == 'ATTACK_ROLLED' and e.actor_id == ALLY][-1]
        assert roll.payload['mode'] == 'ADVANTAGE'
        assert not sunlit_conditions(engine)
        assert not any(m.source_definition_id == SUNLIT for m in engine.state.actors[ALLY].modifiers.values())


def test_sunlit_opening_decline_and_expiry(tmp_path):
    def prepare(bundles):
        bundles[2]['actor_template']['armor_class'] = 0
        _seal(bundles[2])
    combat, table, mid = fixture(tmp_path, [SUNLIT], owner_kit={'starting_kit': KIT},
                                foe_position={'x': 3, 'y': 5}, bundle_transform=prepare)
    settle(table, mid, candidate(combat, mid, 'Kindle the Rising', target=OWNER).candidate_id)
    picks = sunlit_picks(); picks['choice:needle.sunlit_opening'] = None
    settle(table, mid, candidate(combat, mid, 'Bi Shou (Dagger) attack', target=FOE).candidate_id, picks)
    assert not sunlit_conditions(reload(tmp_path, mid))
    turn(table, mid, ALLY); turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, 'Kindle the Rising', target=OWNER).candidate_id)
    settle(table, mid, candidate(combat, mid, 'Bi Shou (Dagger) attack', target=FOE).candidate_id, sunlit_picks())
    assert sunlit_conditions(reload(tmp_path, mid))
    turn(table, mid, ALLY); turn(table, mid, OWNER)
    engine = reload(tmp_path, mid)
    assert not sunlit_conditions(engine)
    assert not any(m.source_definition_id == SUNLIT for m in engine.state.actors[ALLY].modifiers.values())


@pytest.mark.parametrize('native', [False, True])
@pytest.mark.parametrize('failed', [False, True])
def test_sunlit_opening_final_save(tmp_path, native, failed):
    def prepare(bundles):
        if native:
            action = _native_save_action(OWNER, 'action:test.a2.yang_save', 'Opening save')
            bundles[0]['action_catalog'].append(action.model_dump(mode='json'))
            bundles[0]['actor_template']['action_ids'].append(action.source_definition_id)
        else:
            _add_action(bundles[0], 'Opening save', [{'type': 'save', 'ability': 'con', 'dc': 16,
                        'on_fail': [{'type': 'damage', 'flat': 1, 'damage_types': ['force']}], 'on_success': []}])
        bundles[2]['actor_template']['saving_throws'] = {'CON': -100 if failed else 100, 'WIS': -100 if failed else 100}
        _seal(bundles[0]); _seal(bundles[2])
    combat, table, mid = fixture(tmp_path, [SUNLIT], bundle_transform=prepare,
                                ally_kit={'starting_kit': KIT}, foe_position={'x': 4, 'y': 5})
    settle(table, mid, candidate(combat, mid, 'Kindle the Rising', target=OWNER).candidate_id)
    prompts = settle(table, mid, candidate(combat, mid, 'Opening save', target=FOE).candidate_id, sunlit_picks())
    engine = reload(tmp_path, mid)
    assert bool(sunlit_conditions(engine)) == failed
    assert any(p['context']['reaction_source_id'] == 'choice:needle.sunlit_opening' for p in prompts) == failed


@pytest.mark.parametrize('ai_turn', [False, True])
def test_sunlit_opening_manual_owner_on_ally_turn_and_auto_owner(tmp_path, ai_turn):
    from tests.worker2_support import sealed_native_attack
    def prepare(bundles):
        sealed_native_attack(bundles[1], 'Opening shot', attack_bonus=100)
        bundles[2]['actor_template']['armor_class'] = 0
        _seal(bundles[2])
    combat, table, mid = fixture(tmp_path, [SUNLIT], ally_kit={'starting_kit': KIT},
                                foe_position={'x': 4, 'y': 5}, bundle_transform=prepare)
    settle(table, mid, candidate(combat, mid, 'Kindle the Rising', target=ALLY).candidate_id)
    turn(table, mid, ALLY)
    if ai_turn:
        combat.set_controller_mode(mid, actor_id=ALLY, controller_mode='LOCAL_AUTO')
    cid = candidate(combat, mid, 'Opening shot', target=FOE).candidate_id
    if ai_turn:
        # Test the AI execution/Ask-me route, independent of its movement policy.
        # The public adapter validates this attack against the AI's legal context;
        # automatic reaction decisions still use the normal controller.
        from combat.gate4_adapters import ManualControllerAdapter
        real_controller = combat.controller
        selected = {'candidate_id': cid}
        combat.controller = ManualControllerAdapter(
            lambda context: (selected['candidate_id'], ()),
            reaction_chooser=lambda context: real_controller.choose_reaction(context).decision)
    prompts = settle(table, mid, cid, sunlit_picks(), auto=ai_turn)
    sunlit = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.sunlit_opening')
    assert sunlit['context']['reactor_id'] == OWNER
    assert sunlit_conditions(reload(tmp_path, mid))
    if ai_turn:
        # Initiative navigation below submits manual End Turn actions.
        combat.set_controller_mode(mid, actor_id=ALLY, controller_mode='MANUAL')
    turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, 'Kindle the Rising', target=ALLY).candidate_id)
    turn(table, mid, ALLY)
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    if ai_turn:
        combat.set_controller_mode(mid, actor_id=ALLY, controller_mode='LOCAL_AUTO')
    cid = candidate(combat, mid, 'Opening shot', target=FOE).candidate_id
    if ai_turn:
        selected['candidate_id'] = cid
    prompts = settle(table, mid, cid, auto=ai_turn)
    assert not prompts
    assert sum(e.event_type == 'MODIFIER_APPLIED' and e.source_definition_id == SUNLIT
               for e in reload(tmp_path, mid).events) == 2


@pytest.mark.parametrize('mode', ['grasping', 'nourishing'])
def test_unfinished_bloom_start_only_modes_commit_reload(tmp_path, mode):
    from combat import zones
    from combat.typed_executor import bears_mark
    from combat.ext.yang_bloom import BLOOM, AREA_MARK
    combat, table, mid = fixture(tmp_path, [BLOOM], seed='A2-BLOOM')
    settle(table, mid, candidate(combat, mid, 'Unfinished Bloom', at=(5, 6)).candidate_id,
           {'choice:needle.unfinished_bloom': mode})
    engine = reload(tmp_path, mid)
    zone = next(z for z in engine.state.zones.values() if BLOOM.lower() in z.source_definition_id.lower())
    assert zone.trigger_profile['profile'][AREA_MARK] == 1
    assert engine.state.actors[OWNER].resources['resource:core.qi'] == 97
    assert engine.state.actors[OWNER].concentration.zone_id == zone.zone_id
    assert engine.state.actors[ALLY].temporary_hp == 0
    assert not bears_mark(engine.state.actors[FOE], OWNER, 'Overkindled Mark')
    difficult_foe = zones.difficult_cells(engine, engine.state.actors[FOE])
    difficult_ally = zones.difficult_cells(engine, engine.state.actors[ALLY])
    cell = (5, 6)
    assert (cell in difficult_foe) == (mode == 'grasping')
    assert cell not in difficult_ally
    turn(table, mid, ALLY)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[ALLY].temporary_hp == (4 if mode == 'nourishing' else 0)
    turn(table, mid, FOE)
    engine = reload(tmp_path, mid)
    assert bears_mark(engine.state.actors[FOE], OWNER, 'Overkindled Mark') == (mode == 'grasping')
    assert engine.state.actors[FOE].temporary_hp == 0
    turn(table, mid, OWNER)
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    engine = reload(tmp_path, mid)
    zone = engine.state.zones[zone.zone_id]
    assert zone.active, 'expiring the area mark must not end the concentrated Bloom'
    assert zone.trigger_profile['profile'][AREA_MARK] == 0


def test_bloom_area_mark_shares_creature_mark_limit(tmp_path):
    from combat.ext.yang_bloom import BLOOM, AREA_MARK
    from combat.typed_executor import bears_mark
    # Compile a genuine PB-2 owner rather than assuming CL changes the fixture's PB.
    combat, table, mid = fixture(tmp_path, [BLOOM, 'TAL_YANG_TWOFOLD_RISING'], owner_pb=2)
    settle(table, mid, candidate(combat, mid, 'Unfinished Bloom', at=(5, 6)).candidate_id,
           {'choice:needle.unfinished_bloom': 'nourishing'})
    turn(table, mid, ALLY); turn(table, mid, OWNER)
    engine = combat._load_session(mid).engine
    pair = next(c for c in engine.legal_candidates()
                if c.source_definition_id in engine.action_catalog
                and 'Kindle Two Creatures' in engine.action_catalog[c.source_definition_id].display_name)
    settle(table, mid, pair.candidate_id, {'choice:needle.twofold_kindled': [OWNER, ALLY]})
    engine = reload(tmp_path, mid)
    zone = next(z for z in engine.state.zones.values() if BLOOM.lower() in z.source_definition_id.lower())
    assert zone.trigger_profile['profile'][AREA_MARK] == 0, 'the oldest Rising Mark was on the area'
    assert zone.active
    assert bears_mark(engine.state.actors[ALLY], OWNER, 'Kindled Mark')
    assert bears_mark(engine.state.actors[OWNER], OWNER, 'Kindled Mark')


def test_sunlit_area_save_uses_any_final_failure_and_real_roster(tmp_path):
    """Aim may lower a successful save after somebody else already failed."""
    def prepare(bundles):
        _add_action(bundles[0], 'Opening wave', [{'type': 'save', 'ability': 'wis',
            'applies_to': 'creatures_in_area', 'dc': 16, 'on_fail': [], 'on_success': []}],
            target='CELL', area={'shape': 'sphere', 'size_ft': 15})
        bundles[1]['actor_template']['saving_throws'] = {'WIS': -100}
        bundles[2]['actor_template']['saving_throws'] = {'WIS': 100}
        for bundle in bundles:
            _seal(bundle)
    combat, table, mid = fixture(tmp_path, [SUNLIT], bundle_transform=prepare,
                                ally_kit={'starting_kit': KIT}, foe_position={'x': 4, 'y': 5})
    settle(table, mid, candidate(combat, mid, 'Kindle the Rising', target=OWNER).candidate_id)
    picks = sunlit_picks(ALLY, ALLY)
    prompts = settle(table, mid, candidate(combat, mid, 'Opening wave', at=(5, 6)).candidate_id, picks)
    engine = reload(tmp_path, mid)
    assert sunlit_conditions(engine), 'the triggering wave had a failed save even though Aim\'s chosen target saved'
    prompt = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.sunlit_opening')
    targets = {o['id'].split('|')[1] for o in prompt['choice']['options']}
    assert {ALLY, FOE} <= targets
    assert not any(e.source_definition_id == SUNLIT and e.event_type == 'RESOURCE_SPENT' for e in engine.events)
    turn(table, mid, ALLY)
    settle(table, mid, candidate(combat, mid, 'Bi Shou (Dagger) attack', target=FOE).candidate_id)
    engine = reload(tmp_path, mid)
    roll = [e for e in engine.events if e.event_type == 'ATTACK_ROLLED' and e.actor_id == ALLY][-1]
    assert roll.payload['mode'] == 'NORMAL'
    assert sunlit_conditions(engine), 'attacking another creature must preserve this target-specific benefit'
