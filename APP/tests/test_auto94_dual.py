"""AUTO94 actual weapon rolls, current grips, choices and repeat-save cleanup."""
import contextlib
import hashlib
import pytest
from combat.gate2_runtime_models import ActionDefinition
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.cw2_service_support import add_action, seal
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, turn, reload
from tests.h1_support import ROOT
from tests.test_auto_martial import DAGGER_PAIR_KIT
from combat.ext.martial_dual_wielding import DODGE_PAIR_FLAG, recorded_dodge_pairs

T = 'TAL_DUAL_WIELDING_'


def _dodges(actor):
    """The live Dodging instance ids, oldest first."""
    return sorted((iid for iid, c in actor.conditions.items() if c.condition_id == 'condition:core.dodge'),
                  key=lambda iid: actor.conditions[iid].applied_sequence)


@contextlib.contextmanager
def _no_dodge_record(legacy_integer=None):
    """Stop Focusing Defense's lifecycle subscriber writing for the commits inside this block.

    A saved fight carries every actor's turn_flags in each commit's recorded runtime control, so a
    fight saved before the record existed is exactly one in which this subscriber never ran. Only
    this plug-in's own registration is suspended, and only for the block.
    """
    from combat import ext
    from combat.ext import martial_dual_wielding as module

    subscriber = module.focusing_defense_dodge_lifecycle
    ext.subscribers('state_event')  # load the plug-in package before touching its registry
    suspended = []
    def old_record(engine, event, *args):
        if legacy_integer is not None and event.event_type == 'CONDITION_APPLIED':
            if event.payload.get('condition_id') == 'condition:core.dodge':
                for who in event.target_ids:
                    engine.state.actors[who].turn_flags[DODGE_PAIR_FLAG] = legacy_integer

    for point in ('state_event', 'event'):
        registry = ext._HOOKS.get(point, [])
        for index, function in enumerate(registry):
            if function is subscriber:
                suspended.append((registry, index))
                registry[index] = old_record
    assert suspended, 'the Dodge record subscriber is registered nowhere'
    try:
        yield
    finally:
        for registry, index in suspended:
            registry[index] = subscriber


def setup(bundles):
    for b, bonus in zip(bundles, [100, -100, 0]):
        b['actor_template']['initiative_bonus'] = bonus
        b['actor_template']['maximum_hp'] = 300
        seal(b)
    for r in bundles[2].get('typed_reactions', []):
        r['ask'] = False
    bundles[2]['actor_template']['armor_class'] = 0
    bundles[2]['actor_template']['saving_throws']['DEX'] = 100
    add_action(bundles[0], 'Prepare failed Dexterity', [{'type': 'condition', 'condition': 'auto94_save_failure',
        'applies_to': 'target', 'expires_on': 'UNTIL_REMOVED',
        'condition_data': {'rule': {'save_mode': {'DEX': 'AUTO_FAIL'}}}}])
    add_action(bundles[2], 'Improve Dexterity saves', [{'type': 'remove_condition',
        'condition': 'auto94_save_failure', 'applies_to': 'self'}], target='SELF')
    a = ActionDefinition(source_definition_id='action:test.cw2.dual.native', display_name='Native free attack',
        owner_id=FOE, economy='NONE', resolution_kind='ATTACK', target_kind='ANY_CREATURE', range_ft=120,
        attack_bonus=6, damage={'count': 1, 'sides': 4}, damage_type='BLUDGEONING')
    bundles[2]['action_catalog'].append(a.model_dump(mode='json'))
    bundles[2]['actor_template']['action_ids'].append(a.source_definition_id)
    seal(bundles[2])


def weapon(combat, mid, suffix='', base=0):
    e = combat._load_session(mid).engine
    basics = [a for a in e.action_catalog.values() if a.owner_id == OWNER and '.weapon.' in a.source_definition_id
              and a.display_name.endswith(' attack') and '#' not in a.source_definition_id]
    a = basics[base]
    return next(c for c in e.legal_candidates() if c.source_definition_id == a.source_definition_id + suffix
                and c.target_ids == (FOE,))


def two_nineteens():
    for n in range(10000):
        seed = 'AUTO94-CRIT-' + str(n)
        if all(int.from_bytes(hashlib.sha256(seed.encode() + b'\0' + c.to_bytes(16, 'big')).digest(), 'big') % 20 + 1 == 19
               for c in (3, 5)):
            return seed
    raise AssertionError('No deterministic seed')


@pytest.mark.parametrize('owned', [True, False])
def test_critical_follow_up_native_packet_only_for_answering_weapon(tmp_path, owned):
    combat, table, mid = fixture(tmp_path, [T+'CRITICAL_FOLLOW_UP'] if owned else [],
        owner_kit=DAGGER_PAIR_KIT, foe_kit=DAGGER_PAIR_KIT, foe_position={'x': 3, 'y': 5}, seed=two_nineteens(), bundle_transform=setup)
    settle(table, mid, weapon(combat, mid).candidate_id)
    settle(table, mid, weapon(combat, mid, '#offhand', base=1).candidate_id)
    e = reload(tmp_path, mid)
    attacks = [v for v in e.events if v.event_type == 'ATTACK_ROLLED' and v.actor_id == OWNER]
    assert [v.payload['natural_result'] for v in attacks] == [19, 19]
    damage = [v for v in e.events if v.event_type == 'DAMAGE_ROLLED' and v.actor_id == OWNER]
    assert [v.payload['critical'] for v in damage] == [False, owned]
    assert len(damage[-1].payload['dice']) == (2 if owned else 1)
    assert len([v for v in e.events if v.event_type == 'DAMAGE_COMMITTED' and v.actor_id == OWNER]) == 2


@pytest.mark.parametrize('redraw', [False, True])
def test_focusing_defense_dodge_current_grips_and_expiry(tmp_path, redraw):
    combat, table, mid = fixture(tmp_path, [T+'FOCUSING_DEFENSE'], owner_kit=DAGGER_PAIR_KIT,
        foe_position={'x': 3, 'y': 5}, bundle_transform=setup)
    base_ac = reload(tmp_path, mid).state.actors[OWNER].armor_class
    settle(table, mid, candidate(combat, mid, 'Dodge').candidate_id)
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Native free attack', target=OWNER).candidate_id)
    e = reload(tmp_path, mid)
    assert [v for v in e.events if v.event_type == 'ATTACK_ROLLED'][-1].payload['target_ac'] == base_ac + 2
    turn(table, mid, OWNER)
    assert not any(c.condition_id == 'condition:core.dodge' for c in reload(tmp_path, mid).state.actors[OWNER].conditions.values())
    settle(table, mid, candidate(combat, mid, 'Dodge').candidate_id)
    settle(table, mid, candidate(combat, mid, 'Stow Bi Shou (Dagger) (frees 1 hand; no Action)').candidate_id)
    if redraw:
        settle(table, mid, candidate(combat, mid, 'Draw Bi Shou (Dagger) (uses 1 hand; no Action)').candidate_id)
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Native free attack', target=OWNER).candidate_id)
    assert [v for v in reload(tmp_path, mid).events if v.event_type == 'ATTACK_ROLLED'][-1].payload['target_ac'] == base_ac + (2 if redraw else 0)


def test_focusing_defense_needs_the_pair_held_when_dodge_was_taken(tmp_path):
    """"While Dodging WITH a readied Qualifying Pair": the pair must be in hand at the trigger.

    Stowing a weapon and Dodging, then drawing it, never met the printed trigger -- the old code
    granted +2 AC anyway because it only asked what the pair was doing when the attack landed.
    The eligibility recorded at the Dodge must survive a commit and a cold reload, so this reads
    the reloaded engine, not the in-memory one.
    """
    combat, table, mid = fixture(tmp_path, [T+'FOCUSING_DEFENSE'], owner_kit=DAGGER_PAIR_KIT,
        foe_position={'x': 3, 'y': 5}, bundle_transform=setup)
    base_ac = reload(tmp_path, mid).state.actors[OWNER].armor_class
    # One weapon stowed first: the Dodge is taken without a qualifying pair.
    settle(table, mid, candidate(combat, mid, 'Stow Bi Shou (Dagger) (frees 1 hand; no Action)').candidate_id)
    settle(table, mid, candidate(combat, mid, 'Dodge').candidate_id)
    # Drawing after the fact is not the trigger, and must not become one.
    settle(table, mid, candidate(combat, mid, 'Draw Bi Shou (Dagger) (uses 1 hand; no Action)').candidate_id)
    owner = reload(tmp_path, mid).state.actors[OWNER]
    assert any(c.condition_id == 'condition:core.dodge' for c in owner.conditions.values()), 'the Dodge is live'
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Native free attack', target=OWNER).candidate_id)
    assert [v for v in reload(tmp_path, mid).events if v.event_type == 'ATTACK_ROLLED'][-1].payload['target_ac'] == base_ac


def test_dodge_record_reaches_both_the_native_and_the_controller_engine():
    """Checklist 6: the strict state_event seam is documented as delivered by Gate2 and Gate4 alike."""
    from combat.factory_compiler import compile_character
    from combat.gate2_engine import Gate2Engine
    from combat.gate4_engine import Gate4ControllerEngine
    from tests.h1_support import ME, ROOT, sheet

    bundle = compile_character(sheet([T+'FOCUSING_DEFENSE'], kit=DAGGER_PAIR_KIT), actor_id=ME)
    rival = compile_character(sheet([]), actor_id='actor:factory.seam-rival')
    for engine_class in (Gate2Engine, Gate4ControllerEngine):
        engine = engine_class(ROOT, match_seed='AUTO94-SEAM', typed_bundles=(bundle, rival),
            roster_setup={'primary_actor_ids': [ME, rival['actor_id']],
                          'team_by_actor': {ME: 'team:a', rival['actor_id']: 'team:b'},
                          'starting_positions': {ME: {'x': 3, 'y': 6}, rival['actor_id']: {'x': 4, 'y': 6}}})
        actor = engine.state.actors[ME]
        engine._apply_condition(actor, 'condition:core.dodge', 'system:combat.dodge', ME,
                                expires_on='START_OF_SELF_NEXT_TURN')
        assert recorded_dodge_pairs(actor) == {_dodges(actor)[0]: True}, engine_class.__name__
        engine._remove_condition(actor, 'condition:core.dodge', 'system:combat.dodge')
        assert recorded_dodge_pairs(actor) == {}, f'{engine_class.__name__} kept the record'
        assert DODGE_PAIR_FLAG not in actor.turn_flags
    from combat import ext
    from combat.ext.martial_dual_wielding import focusing_defense_dodge_lifecycle
    assert ext.subscribers('state_event').count(focusing_defense_dodge_lifecycle) == 1
    assert focusing_defense_dodge_lifecycle not in ext.subscribers('event')


def test_focusing_defense_recorded_eligibility_survives_commit_and_reload(tmp_path):
    """Checklist 7: per-instance eligibility persists as a string containing integer answers."""
    combat, table, mid = fixture(tmp_path, [T+'FOCUSING_DEFENSE'], owner_kit=DAGGER_PAIR_KIT,
        foe_position={'x': 3, 'y': 5}, bundle_transform=setup)
    settle(table, mid, candidate(combat, mid, 'Dodge').candidate_id)
    owner = reload(tmp_path, mid).state.actors[OWNER]
    dodges = _dodges(owner)
    assert len(dodges) == 1, dodges
    assert recorded_dodge_pairs(owner) == {dodges[0]: True}
    assert DODGE_PAIR_FLAG in owner.turn_flags, 'the record is on the owner, not another actor'
    # The record does not outlive its own trigger: once the Dodge ends, so does the eligibility.
    turn(table, mid, FOE)
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    turn(table, mid, OWNER)
    owner = reload(tmp_path, mid).state.actors[OWNER]
    assert not _dodges(owner)
    assert recorded_dodge_pairs(owner) == {}
    assert DODGE_PAIR_FLAG not in owner.turn_flags


@pytest.mark.parametrize('legacy_integer', [None, 0, 1])
def test_focusing_defense_saved_before_the_record_keeps_its_increase(tmp_path, legacy_integer):
    """A fight saved before eligibility was recorded must not silently lose the +2 AC.

    The save is written with the record suppressed, so it holds exactly what pre-record code wrote:
    an active Dodge taken with the pair readied and no eligibility answer anywhere in the journal.
    A NEW service and a NEW table then load it, and the printed increase must still be there,
    because that is the rule the fight was played under.
    """
    combat, table, mid = fixture(tmp_path, [T+'FOCUSING_DEFENSE'], owner_kit=DAGGER_PAIR_KIT,
        foe_position={'x': 3, 'y': 5}, bundle_transform=setup)
    base_ac = reload(tmp_path, mid).state.actors[OWNER].armor_class
    if legacy_integer == 0:
        settle(table, mid, candidate(combat, mid, 'Stow Bi Shou (Dagger) (frees 1 hand; no Action)').candidate_id)
    with _no_dodge_record(legacy_integer):
        settle(table, mid, candidate(combat, mid, 'Dodge').candidate_id)
    if legacy_integer == 0:
        settle(table, mid, candidate(combat, mid, 'Draw Bi Shou (Dagger) (uses 1 hand; no Action)').candidate_id)
    assert _dodges(reload(tmp_path, mid).state.actors[OWNER]), 'the Dodge is saved as active'
    assert recorded_dodge_pairs(reload(tmp_path, mid).state.actors[OWNER]) == {}, 'with no record'
    fresh_combat = CombatService(ROOT, tmp_path)
    fresh_table = TabletopService(fresh_combat, tmp_path)
    saved = fresh_combat._load_session(mid)
    assert saved.mechanical.replay()['status'] == 'PASS'
    owner = saved.engine.state.actors[OWNER]
    assert _dodges(owner), 'the Dodge is still active in the reloaded save'
    assert recorded_dodge_pairs(owner) == {}, 'and the save predates the record'
    assert owner.turn_flags.get(DODGE_PAIR_FLAG) == legacy_integer
    turn(fresh_table, mid, FOE)
    settle(fresh_table, mid, candidate(fresh_combat, mid, 'Native free attack', target=OWNER).candidate_id)
    attack = [v for v in reload(tmp_path, mid).events
              if v.event_type == 'ATTACK_ROLLED' and v.actor_id == FOE][-1]
    assert attack.payload['target_ac'] == base_ac + (0 if legacy_integer == 0 else 2)
    # The next Dodge taken in that save is judged by the current rule, not the old one.
    turn(fresh_table, mid, OWNER)
    settle(fresh_table, mid, candidate(fresh_combat, mid, 'Stow Bi Shou (Dagger) (frees 1 hand; no Action)').candidate_id)
    turn(fresh_table, mid, FOE)
    settle(fresh_table, mid, fresh_table.state(mid)['menu']['end_turn'])
    turn(fresh_table, mid, OWNER)
    settle(fresh_table, mid, candidate(fresh_combat, mid, 'Dodge').candidate_id)
    owner = reload(tmp_path, mid).state.actors[OWNER]
    assert recorded_dodge_pairs(owner) == {iid: False for iid in _dodges(owner)}, \
        'a Dodge taken without the pair is judged ineligible from now on'
    settle(fresh_table, mid, candidate(fresh_combat, mid, 'Draw Bi Shou (Dagger) (uses 1 hand; no Action)').candidate_id)
    turn(fresh_table, mid, FOE)
    settle(fresh_table, mid, candidate(fresh_combat, mid, 'Native free attack', target=OWNER).candidate_id)
    attack = [v for v in reload(tmp_path, mid).events
              if v.event_type == 'ATTACK_ROLLED' and v.actor_id == FOE][-1]
    assert attack.payload['target_ac'] == base_ac, 'drawing a weapon after Dodging is not the trigger'


@pytest.mark.parametrize('own_eligible,granted_eligible,legacy', [
    (True, False, False), (False, True, False), (True, True, False), (True, False, True)])
def test_focusing_defense_ending_one_dodge_keeps_another_ones_increase(
        tmp_path, own_eligible, granted_eligible, legacy):
    """Overlapping Dodges are separate printed states, so each keeps its own recorded answer.

    A Jester ally grants a second Dodge that expires before the owner's own Dodge. Each may be
    eligible independently. Ending either an eligible or ineligible grant must preserve the
    remaining instance's own answer, including an instance inherited from a pre-record save.
    """
    ally_reaction = 'reaction:typed.test:ally_takes_the_dodge'

    def build(bundles):
        setup(bundles)
        # The ally acts first, so its next turn -- which ends the granted Dodge -- comes before the
        # owner's next turn start, which ends the owner's own Dodge.
        bundles[0]['actor_template']['initiative_bonus'] = 0
        bundles[1]['actor_template']['initiative_bonus'] = 100
        bundles[2]['actor_template']['initiative_bonus'] = -100
        # The shipped Jester ultimatum, sealed onto the ally as a reaction to a technique that
        # targets it: "resolve it and allow one ally ... to take the Dodge action".
        bundles[1]['typed_reactions'].append({'feature_id': 'test:ally_takes_the_dodge',
            'name': 'Let an ally take the Dodge action', 'block': 'generic', 'kind': 'technique_targets',
            'range_ft': 60, 'ask': True, 'costs': [], 'effects': [
                {'type': 'jester_ultimatum', 'ally_dodge': True, 'applies_to': 'target',
                 'flustered_row': {'type': 'condition', 'condition': 'flustered', 'applies_to': 'target',
                                   'duration': 'until_end_of_next_turn'},
                 'evidence': 'The creature chooses one: abandon the triggering technique, resolve it and '
                             'become Flustered until the end of your next turn, or resolve it and allow one '
                             'ally to take the Dodge action.'}]})
        for bundle in bundles:
            seal(bundle)
        add_action(bundles[0], 'Own technique', [{'type': 'save', 'ability': 'dex', 'dc': 10,
            'applies_to': 'target', 'on_fail': [], 'on_success': []}])
        attack = ActionDefinition(source_definition_id='action:test.cw2.dual.ally_native',
            display_name='Ally free attack', owner_id=ALLY, economy='NONE', resolution_kind='ATTACK',
            target_kind='ANY_CREATURE', range_ft=120, attack_bonus=6,
            damage={'count': 1, 'sides': 4}, damage_type='BLUDGEONING')
        bundles[1]['action_catalog'].append(attack.model_dump(mode='json'))
        bundles[1]['actor_template']['action_ids'].append(attack.source_definition_id)
        seal(bundles[1])

    combat, table, mid = fixture(tmp_path, [T+'FOCUSING_DEFENSE'], owner_kit=DAGGER_PAIR_KIT,
        foe_position={'x': 3, 'y': 5}, bundle_transform=build)
    base_ac = reload(tmp_path, mid).state.actors[OWNER].armor_class
    turn(table, mid, OWNER)
    if not own_eligible:
        settle(table, mid, candidate(combat, mid, 'Stow Bi Shou (Dagger) (frees 1 hand; no Action)').candidate_id)
    with _no_dodge_record() if legacy else contextlib.nullcontext():
        settle(table, mid, candidate(combat, mid, 'Dodge').candidate_id)
    owner = reload(tmp_path, mid).state.actors[OWNER]
    own_dodge = _dodges(owner)
    assert len(own_dodge) == 1
    assert recorded_dodge_pairs(owner) == ({} if legacy else {own_dodge[0]: own_eligible})
    if own_eligible != granted_eligible:
        name = ('Draw Bi Shou (Dagger) (uses 1 hand; no Action)' if granted_eligible
                else 'Stow Bi Shou (Dagger) (frees 1 hand; no Action)')
        settle(table, mid, candidate(combat, mid, name).candidate_id)
    prompts = settle(table, mid, candidate(combat, mid, 'Own technique', target=ALLY).candidate_id,
                     {ally_reaction: 'use', 'choice:needle.jester_ultimatum': 'ally'})
    assert [p['context']['reaction_source_id'] for p in prompts] == [ally_reaction,
        'choice:needle.jester_ultimatum'], 'the ally grants the Dodge through its own printed choice'
    owner = reload(tmp_path, mid).state.actors[OWNER]
    granted = [iid for iid in _dodges(owner) if iid != own_dodge[0]]
    assert granted, 'the granted Dodge is a second, separate instance'
    assert recorded_dodge_pairs(owner) == {own_dodge[0]: own_eligible, granted[0]: granted_eligible}
    # Drawing the weapon again during the same Dodge restores the printed increase.
    if not granted_eligible:
        settle(table, mid, candidate(combat, mid, 'Draw Bi Shou (Dagger) (uses 1 hand; no Action)').candidate_id)
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Native free attack', target=OWNER).candidate_id)
    attack = [v for v in reload(tmp_path, mid).events
              if v.event_type == 'ATTACK_ROLLED' and v.actor_id == FOE][-1]
    assert attack.payload['target_ac'] == base_ac + 2
    # The ally's turn begins, which expires the granted instance only.
    turn(table, mid, ALLY)
    owner = reload(tmp_path, mid).state.actors[OWNER]
    assert _dodges(owner) == own_dodge, 'only the granted instance ended'
    assert recorded_dodge_pairs(owner) == {own_dodge[0]: own_eligible}
    settle(table, mid, candidate(combat, mid, 'Ally free attack', target=OWNER).candidate_id)
    attack = [v for v in reload(tmp_path, mid).events
              if v.event_type == 'ATTACK_ROLLED' and v.actor_id == ALLY][-1]
    assert attack.payload['target_ac'] == base_ac + (2 if own_eligible else 0)
    # And when the surviving Dodge ends, nothing is left behind.
    turn(table, mid, OWNER)
    owner = reload(tmp_path, mid).state.actors[OWNER]
    assert not _dodges(owner) and recorded_dodge_pairs(owner) == {}
    assert DODGE_PAIR_FLAG not in owner.turn_flags


@pytest.mark.parametrize('owned', [True, False])
def test_focusing_defense_is_inert_without_the_talent(tmp_path, owned):
    """Checklist 3: nothing is recorded for a character that does not own the talent."""
    combat, table, mid = fixture(tmp_path, [T+'FOCUSING_DEFENSE'] if owned else [], owner_kit=DAGGER_PAIR_KIT,
        foe_position={'x': 3, 'y': 5}, bundle_transform=setup)
    settle(table, mid, candidate(combat, mid, 'Dodge').candidate_id)
    recorded = DODGE_PAIR_FLAG in reload(tmp_path, mid).state.actors[OWNER].turn_flags
    assert recorded == owned
    base_ac = reload(tmp_path, mid).state.actors[OWNER].armor_class
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Native free attack', target=OWNER).candidate_id)
    assert [v for v in reload(tmp_path, mid).events if v.event_type == 'ATTACK_ROLLED'][-1].payload['target_ac'] \
        == base_ac + (2 if owned else 0)


@pytest.mark.parametrize('choice', ['dw_dancing_display', 'dw_dizzying_combination', None])
def test_pair_selection_decline_and_precise_dancing_reaction_scope(tmp_path, choice):
    combat, table, mid = fixture(tmp_path, [T+'DANCING_DISPLAY', T+'DIZZYING_COMBINATION'],
        owner_kit=DAGGER_PAIR_KIT, foe_kit=DAGGER_PAIR_KIT, foe_position={'x': 3, 'y': 5}, seed=two_nineteens(), bundle_transform=setup)
    settle(table, mid, candidate(combat, mid, 'Prepare failed Dexterity', target=FOE).candidate_id)
    settle(table, mid, weapon(combat, mid).candidate_id)
    prompts = settle(table, mid, weapon(combat, mid, '#offhand', base=1).candidate_id,
        {'choice:needle.dual_pair': choice})
    p = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.dual_pair')
    assert p['context']['reactor_id'] == OWNER and len(p['choice']['options']) == 2
    e = reload(tmp_path, mid); foe = e.state.actors[FOE]
    assert foe.reaction_available
    assert not any(c.condition_id == 'condition:typed.reaction_denied' for c in foe.conditions.values())
    oa = [c for c in foe.conditions.values() if c.condition_id == 'condition:typed.no_opportunity_attacks']
    assert bool(oa) == (choice == 'dw_dancing_display')
    if oa:
        from combat.typed_reactions import wants_opportunity_attack
        assert not wants_opportunity_attack(e, foe, e.state.actors[OWNER])
        assert wants_opportunity_attack(e, foe, e.state.actors[ALLY])
    slow = any(c.condition_id == 'condition:typed.dizzying_combination' for c in foe.conditions.values())
    assert slow == (choice == 'dw_dizzying_combination')
    if slow:
        assert e._effective_speed(foe) == 15
        held = next(c for c in foe.conditions.values() if c.condition_id == 'condition:typed.dizzying_combination')
        assert held.expires_on.startswith('START_OF_SLOT_AT:') and held.data['repeat_save']['dc'] == 16
        turn(table, mid, FOE)
        settle(table, mid, table.state(mid)['menu']['end_turn'])
        e = reload(tmp_path, mid)
        assert any(c.condition_id == 'condition:typed.dizzying_combination' for c in e.state.actors[FOE].conditions.values())
        turn(table, mid, OWNER)
        # The previous one-round approximation would be gone here.
        assert reload(tmp_path, mid)._effective_speed(reload(tmp_path, mid).state.actors[FOE]) == 15
        turn(table, mid, FOE)
        settle(table, mid, candidate(combat, mid, 'Improve Dexterity saves').candidate_id)
        settle(table, mid, table.state(mid)['menu']['end_turn'])
        e = reload(tmp_path, mid)
        assert not any(c.condition_id == 'condition:typed.dizzying_combination' for c in e.state.actors[FOE].conditions.values())
        assert e._effective_speed(e.state.actors[FOE]) == 30
    else:
        settle(table, mid, table.state(mid)['menu']['end_turn'])
        assert not any(c.condition_id == 'condition:typed.no_opportunity_attacks'
            for c in reload(tmp_path, mid).state.actors[FOE].conditions.values())
