"""Round 2 Yang through compiled characters, actual table decisions and cold reloads."""
import pytest
from combat.gate5_service import CombatService
from combat.typed_executor import bears_mark
from combat.ext.yang_recovery import ROUND
from tests.test_carry import KIT
from combat.ext import kindled_responses as family
from combat.ext.yang_recovery import AIM
from tests.worker2_support import ROOT, OWNER, ALLY, FOE, fixture, candidate, act


def settle(table, mid, cid, picks=None):
    answers, prompts = [], []
    for _ in range(20):
        result = act(table, mid, cid, answers)
        if result['status'] != 'REACTION_REQUIRED':
            assert result['status'] == 'COMMITTED', result
            return prompts
        p = result['reaction']; prompts.append(p)
        rid = p['context']['reaction_source_id']
        choice = (picks or {}).get(rid, 'first' if rid.startswith('choice:') else None)
        answer = {**p['context'], 'selection': 'USE' if choice is not None else 'DECLINE'}
        if choice is not None and p.get('choice'):
            answer['option_ids'] = ([p['choice']['options'][0]['id']] if choice == 'first'
                                    else choice if isinstance(choice, list) else [choice])
        answers.append(answer)
    raise AssertionError('Too many prompts')


def turn(table, mid, actor):
    for _ in range(12):
        if table.state(mid)['menu']['actor_id'] == actor:
            return
        settle(table, mid, table.state(mid)['menu']['end_turn'])
    raise AssertionError('No turn')


def reload(tmp_path, mid):
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.mechanical.replay()['status'] == 'PASS'
    return loaded.engine


@pytest.mark.parametrize('subject,accept', [(OWNER, True), (ALLY, True), (OWNER, False)])
def test_complete_aim_on_own_or_ally_attack(tmp_path, subject, accept):
    combat, table, mid = fixture(tmp_path, ['TAL_YANG_FURNACE_BACKLASH'], owner_kit={'starting_kit': KIT},
                                ally_kit={'starting_kit': KIT}, foe_position={'x': 3, 'y': 5})
    mark = candidate(combat, mid, 'Kindle the Rising', target=subject)
    settle(table, mid, mark.candidate_id)
    if subject == ALLY:
        turn(table, mid, ALLY)
    attack = candidate(combat, mid, 'Bi Shou (Dagger) attack', target=FOE)
    before = combat._load_session(mid).engine.state.model_dump(mode='json')
    preview = act(table, mid, attack.candidate_id)
    assert preview['status'] == 'REACTION_REQUIRED'
    assert preview['reaction']['context']['reaction_source_id'] == 'choice:needle.yang_aim_attack'
    assert combat._load_session(mid).engine.state.model_dump(mode='json') == before
    prompts = settle(table, mid, attack.candidate_id, {'choice:needle.yang_aim_attack': 'use' if accept else None})
    assert any(p['context']['reactor_id'] == OWNER for p in prompts)
    e = reload(tmp_path, mid)
    rolls = [r for r in e.events if r.event_type == 'CHECK_ROLLED' and r.source_definition_id.endswith('#complete_aim')]
    assert bool(rolls) == accept
    if accept:
        assert rolls[0].payload['expression'] == '1d6+0'
        assert e.state.actors[OWNER].turn_flags[ROUND] == e.state.round_number
        assert not bears_mark(e.state.actors[subject], OWNER, 'Kindled Mark')
    else:
        assert not any('Complete Aim' == r.payload.get('purpose') for r in rolls)


def test_complete_aim_reduces_one_forced_save(tmp_path):
    combat, table, mid = fixture(tmp_path, ['TAL_YANG_FURNACE_BACKLASH'],
                                ally_talents=['BEAUTY_BASE_CATCH_THE_EYE'])
    settle(table, mid, candidate(combat, mid, 'Kindle the Rising', target=ALLY).candidate_id)
    turn(table, mid, ALLY)
    e = combat._load_session(mid).engine
    cast = next(c for c in e.legal_candidates() if c.target_ids == (FOE,) and 'Catch the Eye' in e.action_catalog[c.source_definition_id].display_name)
    prompts = settle(table, mid, cast.candidate_id, {'choice:needle.yang_aim_save': FOE})
    assert any(p['context']['reaction_source_id'] == 'choice:needle.yang_aim_save' for p in prompts)
    e = reload(tmp_path, mid)
    assert not bears_mark(e.state.actors[ALLY], OWNER, 'Kindled Mark')
    aim = next(r for r in e.events if r.event_type == 'CHECK_ROLLED' and r.source_definition_id.endswith('#complete_aim'))
    saves = [r for r in e.events if r.event_type == 'SAVE_ROLLED' and r.actor_id == FOE]
    assert saves
    # The typed save hook folds a negative save bonus into the opposed DC.
    assert saves[-1].payload['dc'] == 16 + aim.payload['total']


@pytest.mark.parametrize('accept', [True, False])
def test_furnace_backlash_paid_save_has_only_failure_rider(tmp_path, accept):
    combat, table, mid = fixture(tmp_path, ['TAL_YANG_FURNACE_BACKLASH'], seed='H5-CHOICES', owner_dc=100,
                                owner_ac=1, foe_kit={'starting_kit': {'items': [KIT['items'][-1]]}}, foe_position={'x': 3, 'y': 5})
    settle(table, mid, candidate(combat, mid, 'Rising Thread', target=FOE).candidate_id)
    assert bears_mark(reload(tmp_path, mid).state.actors[FOE], OWNER, 'Overkindled Mark')
    turn(table, mid, FOE)
    picks = {'choice:needle.furnace_backlash': 'use' if accept else None,
             'reaction:typed.TAL_YANG_OVERKINDLED_RESPONSES#overheat_force': 'first'}
    prompts = settle(table, mid, candidate(combat, mid, 'Bi Shou (Dagger) attack', target=OWNER).candidate_id, picks)
    assert any(p['context']['reaction_source_id'] == 'choice:needle.furnace_backlash' for p in prompts)
    e = reload(tmp_path, mid)
    assert e.state.actors[OWNER].resources['resource:core.qi'] == 100 - accept
    denied = [c for c in e.state.actors[FOE].conditions.values() if 'reaction_denied' in c.condition_id]
    assert bool(denied) == accept
    if denied:
        assert denied[0].expires_on.startswith('START_OF_TURN_AT:')
        turn(table, mid, OWNER)
        assert any('reaction_denied' in c.condition_id for c in reload(tmp_path, mid).state.actors[FOE].conditions.values())
        turn(table, mid, FOE)
        assert not any('reaction_denied' in c.condition_id for c in reload(tmp_path, mid).state.actors[FOE].conditions.values())


@pytest.mark.parametrize('target', [ALLY, FOE])
def test_wounded_breath_scales_costs_and_records_per_creature_use(tmp_path, target):
    # Fixed preparation is a real table action; the healing rule itself is the
    # shipped Wounded Breath implementation, with its normal costs and dice.
    from combat.canonical import canonical_sha256
    def prepare(bundles):
        for b in bundles:
            if b['actor_id'] == OWNER:
                for a in b['action_catalog']:
                    if a['parameters'].get('typed', {}).get('source') == 'LIFE_BASE_MEND_THE_PULSE':
                        a['display_name'] = 'Prepare Wound'
                        a['target_kind'] = 'ANY_CREATURE'
                        a['range_ft'] = 60
                        a['parameters']['typed']['range_ft'] = 60
                        a['parameters']['typed']['effects'] = [{'type': 'damage', 'flat': 20,
                                                               'applies_to': 'target', 'damage_types': ['force']}]
            b.pop('bundle_sha256', None)
            b['bundle_sha256'] = canonical_sha256(b)
    combat, table, mid = fixture(tmp_path, ['TAL_YANG_KINDLE_THE_WOUNDED_BREATH', 'LIFE_BASE_MEND_THE_PULSE'],
                                cl=17, bundle_transform=prepare)
    settle(table, mid, candidate(combat, mid, 'Prepare Wound', target=target).candidate_id)
    before = reload(tmp_path, mid)
    assert before.state.actors[target].current_hp == 40
    qi = before.state.actors[OWNER].resources['resource:core.qi']
    settle(table, mid, candidate(combat, mid, 'Kindle the Wounded Breath', target=target).candidate_id)
    e = reload(tmp_path, mid)
    assert e.state.actors[OWNER].resources['resource:core.qi'] == qi - 2
    assert bears_mark(e.state.actors[target], OWNER, 'Kindled Mark')
    heal = next(r for r in e.events if r.event_type == 'DAMAGE_ROLLED' and 'WOUNDED_BREATH' in r.source_definition_id)
    assert heal.payload['expression'] == '3d8+2'
    assert e.state.actors[target].current_hp == min(60, 40 + heal.payload['total'])
    turn(table, mid, ALLY); turn(table, mid, OWNER)
    e = reload(tmp_path, mid)
    uses = [c for c in e.legal_candidates() if c.source_definition_id in e.action_catalog
            and 'Wounded Breath' in e.action_catalog[c.source_definition_id].display_name]
    assert not any(c.target_ids == (target,) for c in uses)
    assert any(c.target_ids == (OWNER,) for c in uses)
    # Pure query guard supplements the actual per-creature service case: 0 HP
    # cannot be healed even if a candidate came from an older catalog.
    from combat.ext.yang_recovery import wounded_breath_living_target
    from types import SimpleNamespace
    e.state.actors[ALLY].current_hp = 0
    action = next(a for a in e.action_catalog.values() if 'Wounded Breath' in a.display_name)
    assert wounded_breath_living_target(e, e.state.actors[OWNER], SimpleNamespace(target_ids=(ALLY,)), action) is False
    old_typed = {k: v for k, v in action.parameters['typed'].items() if k != 'auto35_wounded'}
    old_action = action.model_copy(update={'parameters': {**action.parameters, 'typed': old_typed}})
    assert wounded_breath_living_target(e, e.state.actors[OWNER], SimpleNamespace(target_ids=(ALLY,)), old_action) is None


@pytest.mark.parametrize('mode', ['Kindle Two Creatures', 'Rising Thread and Self Mark'])
def test_twofold_rising_both_modes_commit_marks_and_payment(tmp_path, mode):
    combat, table, mid = fixture(tmp_path, ['TAL_YANG_TWOFOLD_RISING'], seed='H5-CHOICES')
    e = combat._load_session(mid).engine
    rows = [c for c in e.legal_candidates() if c.source_definition_id in e.action_catalog
            and mode in e.action_catalog[c.source_definition_id].display_name
            and (mode.startswith('Kindle') or c.target_ids == (FOE,))]
    assert rows, mode
    prompts = settle(table, mid, rows[0].candidate_id, {'choice:needle.twofold_kindled': [OWNER, ALLY]})
    # The printed "2 CP" is the price of the Twofold Rising action, already paid by the time these marks
    # are placed. Choosing which two creatures to mark costs nothing more, so the prompt quotes that one
    # price -- not a second one to answer with (finding 4).
    if mode.startswith('Kindle'):
        menu = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.twofold_kindled')
        assert '2 Qi' in menu['moment'], menu
        assert 'costs nothing more' in menu['moment']
        assert 'to answer this choice' not in menu['moment']
    e = reload(tmp_path, mid)
    assert e.state.actors[OWNER].resources['resource:core.qi'] == 98
    assert bears_mark(e.state.actors[OWNER], OWNER, 'Kindled Mark')
    if mode.startswith('Kindle'):
        assert bears_mark(e.state.actors[ALLY], OWNER, 'Kindled Mark')
        assert not bears_mark(e.state.actors[FOE], OWNER, 'Kindled Mark')
    else:
        assert bears_mark(e.state.actors[FOE], OWNER, 'Overkindled Mark')
        assert any(p['context']['reaction_source_id'] == 'choice:needle.twofold_self' for p in prompts)


# --- Complete Aim reaches older (non-typed) catalogs: native attacks and saves ---------------------
import copy


def _seal(bundle):
    """Re-seal a fixture bundle after honest catalog edits; never patch engine code."""
    from combat.canonical import canonical_sha256
    bundle.pop('bundle_sha256', None)
    bundle['bundle_sha256'] = canonical_sha256(bundle)
    return bundle


def _add_action(bundle, name, effects, *, economy='ACTION', target='HOSTILE_ENTITY', save_dc=16, **typed):
    """Add a real typed fixture action to a compiled bundle before the match starts."""
    row = copy.deepcopy(next(a for a in bundle['action_catalog'] if a['resolution_kind'] == 'TYPED'))
    row.update(source_definition_id=f"action:test.auto35.{bundle['actor_id']}.{name}", display_name=name,
               economy=economy, target_kind=target, range_ft=60, costs=[])
    row['parameters'] = {'typed': {'effects': effects, 'numbers': {'cl': 15, 'pb': 4, 'save_dc': save_dc},
                                 'duration': {'kind': 'instant'}, 'riders': [], **typed}}
    bundle['action_catalog'].append(row)
    bundle['actor_template']['action_ids'].append(row['source_definition_id'])
    return row


def _invisible_setup(bundle, pinpoint):
    _add_action(bundle, 'Hide marked ally', [{'type': 'condition', 'condition': 'invisible',
        'applies_to': 'target', 'expires_on': 'UNTIL_REMOVED'}], target='ANY_CREATURE')
    if pinpoint:
        bundle['senses'] = {'rows': [{'sense': 'tremorsense', 'range_ft': 30, 'when': 'always'}]}
    _seal(bundle)


def test_aim_offers_only_the_actual_enemy_save_roster(tmp_path):
    """An area save's Aim choice lists the save's own roster, not every area recipient."""
    def prepare(bundles):
        _add_action(bundles[0], 'Enemy-only wave', [{'type': 'save', 'ability': 'wis',
            'applies_to': 'enemies_in_area', 'on_fail': [], 'on_success': []}], target='CELL',
            area={'shape': 'sphere', 'size_ft': 15})
    combat, table, mid = fixture(tmp_path, ['TAL_YANG_FURNACE_BACKLASH'], bundle_transform=prepare)
    settle(table, mid, candidate(combat, mid, 'Kindle the Rising', target=OWNER).candidate_id)
    prompts = settle(table, mid, candidate(combat, mid, 'Enemy-only wave', at=(5, 6)).candidate_id,
                     {'choice:needle.yang_aim_save': FOE})
    aim_prompt = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.yang_aim_save')
    assert [o['id'] for o in aim_prompt['choice']['options']] == [FOE]
    engine = reload(tmp_path, mid)
    saves = [e for e in engine.events if e.event_type == 'SAVE_ROLLED']
    assert [e.actor_id for e in saves] == [FOE]
    bonus = next(e for e in engine.events if e.event_type == 'CHECK_ROLLED' and e.source_definition_id.endswith('#complete_aim'))
    assert saves[0].payload['dc'] == 16 + bonus.payload['total']
    assert not bears_mark(engine.state.actors[OWNER], OWNER, 'Kindled Mark')


@pytest.mark.parametrize('pinpoint', [True, False])
def test_aim_perceives_an_unseen_marked_attacker(tmp_path, pinpoint):
    """Aim triggers on a marked ally the owner cannot see only when it can locate them."""
    from combat.target_knowledge import can_see, located
    combat, table, mid = fixture(tmp_path, ['TAL_YANG_FURNACE_BACKLASH'], ally_kit={'starting_kit': KIT},
        foe_position={'x': 3, 'y': 5}, bundle_transform=lambda b: _invisible_setup(b[0], pinpoint))
    settle(table, mid, candidate(combat, mid, 'Kindle the Rising', target=ALLY).candidate_id)
    settle(table, mid, candidate(combat, mid, 'Hide marked ally', target=ALLY).candidate_id)
    turn(table, mid, ALLY)
    e = reload(tmp_path, mid)
    assert not can_see(e, e.state.actors[OWNER], e.state.actors[ALLY])
    assert located(e, e.state.actors[OWNER], e.state.actors[ALLY]) == pinpoint
    prompts = settle(table, mid, candidate(combat, mid, 'Bi Shou (Dagger) attack', target=FOE).candidate_id)
    assert any(p['context']['reaction_source_id'] == 'choice:needle.yang_aim_attack' for p in prompts) == pinpoint
    assert bears_mark(reload(tmp_path, mid).state.actors[ALLY], OWNER, 'Kindled Mark') != pinpoint


@pytest.mark.parametrize('accept', [True, False])
def test_factory_mark_owner_answers_a_native_ally_attack(tmp_path, accept):
    """A native (non-typed) ally attack asks the mark owner and gains the Aim bonus on use."""
    from combat.gate2_runtime_models import ActionDefinition
    source = 'action:test.auto35.native_attack'
    def prepare(bundles):
        action = ActionDefinition(source_definition_id=source, display_name='Legacy sword attack', owner_id=ALLY,
            economy='ACTION', resolution_kind='ATTACK', target_kind='HOSTILE_ENTITY', reach_ft=5,
            attack_bonus=6, damage={'count': 1, 'sides': 4, 'modifier': 0}, damage_type='SLASHING')
        bundles[1]['action_catalog'].append(action.model_dump(mode='json'))
        bundles[1]['actor_template']['action_ids'].append(source)
        _seal(bundles[1])
    combat, table, mid = fixture(tmp_path, ['TAL_YANG_FURNACE_BACKLASH'],
        foe_position={'x': 3, 'y': 5}, bundle_transform=prepare)
    settle(table, mid, candidate(combat, mid, 'Kindle the Rising', target=ALLY).candidate_id)
    turn(table, mid, ALLY)
    prompts = settle(table, mid, candidate(combat, mid, 'Legacy sword attack', target=FOE).candidate_id,
                     {'choice:needle.yang_aim_attack': 'use' if accept else None})
    assert any(p['context']['reactor_id'] == OWNER and p['context']['reaction_source_id'] == 'choice:needle.yang_aim_attack'
               for p in prompts)
    e = reload(tmp_path, mid)
    attack = next(ev for ev in e.events if ev.event_type == 'ATTACK_ROLLED' and ev.source_definition_id == source)
    bonuses = [ev for ev in e.events if ev.event_type == 'CHECK_ROLLED' and ev.source_definition_id.endswith('#complete_aim')]
    assert attack.payload['modifier'] == 6 + (bonuses[0].payload['total'] if accept else 0)
    assert bears_mark(e.state.actors[ALLY], OWNER, 'Kindled Mark') != accept


def _native_save_action(owner, source, name, *, dc=16):
    """A native (non-TYPED) save-or-damage action, exactly like a legacy character action."""
    from combat.gate2_runtime_models import ActionDefinition, DiceSpec, SaveDefinition
    return ActionDefinition(source_definition_id=source, display_name=name, owner_id=owner,
        economy='ACTION', resolution_kind='SAVE_DAMAGE', target_kind='HOSTILE_ENTITY', range_ft=60,
        damage=DiceSpec(count=1, sides=6, modifier=0), damage_type='FORCE', save=SaveDefinition(ability='WIS', dc=dc))




# ------------------------------------------------------------------ AUTO136r1f1: one mark, one response
FORCE = 'TAL_YANG_KINDLED_RESPONSES#complete_force'


def _aim_menu(prompts):
    return next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.yang_aim_attack')


def test_aim_menu_offers_the_whole_family_when_the_mark_could_buy_several_responses(tmp_path):
    """"You may use these responses when you spend a Kindled Mark" -- one mark, one use. The owner marks
    itself and attacks: Complete Aim (the attack roll) and Complete Force (the hit) are both armed, so the
    question has to carry both, and the default (nobody to answer) keeps the member that waits for the hit.

    Every button names its own printed ability, says what it does in this owner's numbers and says what
    it costs, so a player who knows only basic D&D can choose between them (checklist 13)."""
    combat, table, mid = fixture(tmp_path, ['TAL_YANG_FURNACE_BACKLASH'], owner_kit={'starting_kit': KIT},
                                foe_position={'x': 3, 'y': 5})
    settle(table, mid, candidate(combat, mid, 'Kindle the Rising', target=OWNER).candidate_id)
    prompts = settle(table, mid, candidate(combat, mid, 'Bi Shou (Dagger) attack', target=FOE).candidate_id)
    menu = _aim_menu(prompts)
    ids = [o['id'] for o in menu['choice']['options']]
    assert 'use' in ids and FORCE in ids, ids
    assert menu['choice']['allow_decline']
    assert all('#' not in o['label'] and 'TAL_' not in o['label'] for o in menu['choice']['options'])
    labels = {o['id']: o['label'] for o in menu['choice']['options']}
    assert 'Complete Aim' in labels['use'] and 'Complete Force' in labels[FORCE]
    assert '1d6' in labels['use'] and 'attack roll' in labels['use']
    # Complete Force: 1d6 at CL 0, 3d6 from CL 11, plus this owner's Key Ability modifier.
    assert '3d6' in labels[FORCE] and 'Key Ability modifier' in labels[FORCE]
    assert all('Kindled Mark' in text for text in labels.values()), 'both say what the mark costs'
    assert 'Reaction' not in labels[FORCE], 'Complete Force is a free trigger, so it costs no Reaction'
    e = reload(tmp_path, mid)
    aimed = [r for r in e.events if r.event_type == 'CHECK_ROLLED' and r.source_definition_id.endswith('#complete_aim')]
    forced = [r for r in e.events if r.event_type == 'REACTION_RESOLVED' and r.source_definition_id == FORCE]
    assert bool(aimed) != bool(forced), 'the default answer spends the mark exactly once'


def test_the_unanswered_family_question_defaults_to_the_after_the_hit_response(tmp_path):
    """With nobody to answer (no choice transport at all) the family keeps the member that waits for the
    confirmed outcome -- the behaviour it had before any plug-in arbitrated, and the safe default twice
    over: a mark spent on it is not lost when the attack misses."""
    combat, table, mid = fixture(tmp_path, ['TAL_YANG_FURNACE_BACKLASH'], owner_kit={'starting_kit': KIT},
                                foe_position={'x': 3, 'y': 5})
    settle(table, mid, candidate(combat, mid, 'Kindle the Rising', target=OWNER).candidate_id)
    e = reload(tmp_path, mid)
    owner, marked, foe = e.state.actors[OWNER], e.state.actors[OWNER], e.state.actors[FOE]
    saved, e._gate4_reaction_cache = e._gate4_reaction_cache, None
    try:
        picked = family.choose(e, None, owner, marked, 'test', subjects=[foe],
                               mine=('use', 'Add 1d6'), choice_id='choice:needle.yang_aim_attack',
                               checkpoint='NEEDLE:test', feature_id=AIM, name='Complete Aim')
    finally:
        e._gate4_reaction_cache = saved
    assert picked == FORCE
    assert [r['feature_id'] for r in family.competing(e, owner, exclude=AIM, actor=marked, subjects=[foe])] == [FORCE]


@pytest.mark.parametrize('pick', ['use', FORCE, None])
@pytest.mark.parametrize('ask', [False, True])
def test_aim_and_complete_force_are_the_players_choice_for_one_mark(tmp_path, pick, ask):
    """Choosing Aim spends the mark on the attack roll and leaves nothing for the hit; choosing Complete
    Force leaves the attack roll alone; answering "Not now" spends nothing at all. Either way exactly one
    response runs and at most one mark is spent."""
    combat, table, mid = fixture(tmp_path, ['TAL_YANG_FURNACE_BACKLASH'], ask=ask, owner_kit={'starting_kit': KIT},
                                foe_position={'x': 3, 'y': 5})
    settle(table, mid, candidate(combat, mid, 'Kindle the Rising', target=OWNER).candidate_id)
    prompts = settle(table, mid, candidate(combat, mid, 'Bi Shou (Dagger) attack', target=FOE).candidate_id,
                     {'choice:needle.yang_aim_attack': pick})
    assert any(p['context']['reaction_source_id'] == 'choice:needle.yang_aim_attack' for p in prompts)
    assert not any(p['context']['reaction_source_id'] == 'reaction:typed.' + FORCE for p in prompts), \
        'the family menu already supplies consent, including Ask me'
    e = reload(tmp_path, mid)
    aimed = [r for r in e.events if r.event_type == 'CHECK_ROLLED' and r.source_definition_id.endswith('#complete_aim')]
    forced = [r for r in e.events if r.event_type == 'REACTION_RESOLVED' and r.source_definition_id == FORCE]
    assert bool(aimed) is (pick == 'use')
    assert bool(forced) is (pick == FORCE)
    assert not (aimed and forced), 'one mark cannot pay for two responses'
    if pick is None:
        # "Not now" on a menu that asked which response should spend the mark is a decline of the whole
        # family for this attack: nothing runs, the mark is still there and the shared round is unspent.
        assert bears_mark(e.state.actors[OWNER], OWNER, 'Kindled Mark')
        assert e.state.actors[OWNER].turn_flags.get(ROUND) != e.state.round_number
    else:
        assert not bears_mark(e.state.actors[OWNER], OWNER, 'Kindled Mark')
        assert e.state.actors[OWNER].turn_flags[ROUND] == e.state.round_number, 'the shared round slot is claimed'


def _twin_daggers(bundle):
    """One real Action that swings twice at the same creature (the shape Extra Attack has), so the
    family's once-per-round limit is exercised by two genuine attack rolls in one resolution."""
    lead = next(a for a in bundle['action_catalog']
                if a['display_name'].startswith('Bi Shou') and not a['parameters'].get('typed', {}).get('option_of'))
    row = copy.deepcopy(lead)
    strike = copy.deepcopy(row['parameters']['typed']['effects'][0])
    typed = copy.deepcopy(row['parameters']['typed'])
    for key in ('option_of', 'option_label', 'pair_role'):
        typed.pop(key, None)
    row.update(source_definition_id='action:test.auto35.twin_daggers', display_name='Twin Daggers',
               economy='ACTION', target_kind='HOSTILE_ENTITY')
    row['parameters'] = {'typed': {**typed, 'effects': [strike, strike]}}
    bundle['action_catalog'].append(row)
    bundle['actor_template']['action_ids'].append(row['source_definition_id'])
    _seal(bundle)


@pytest.mark.parametrize('pick', ['use', FORCE, None])
def test_aim_keeps_the_shared_round_limit_across_both_answers(tmp_path, pick):
    """Two real attacks in one Action, one round: whichever answer ran claims the shared once-per-round
    slot, so the second swing is never asked and never spends the mark again. A decline leaves the slot
    free, so the second swing is asked again -- and can still be declined, still for free."""
    combat, table, mid = fixture(tmp_path, ['TAL_YANG_FURNACE_BACKLASH'], owner_kit={'starting_kit': KIT},
                                foe_position={'x': 3, 'y': 5}, bundle_transform=lambda b: _twin_daggers(b[0]))
    settle(table, mid, candidate(combat, mid, 'Kindle the Rising', target=OWNER).candidate_id)
    prompts = settle(table, mid, candidate(combat, mid, 'Twin Daggers', target=FOE).candidate_id,
                     {'choice:needle.yang_aim_attack': pick})
    e = reload(tmp_path, mid)
    assert len([r for r in e.events if r.event_type == 'ATTACK_ROLLED'
                and r.source_definition_id == 'action:test.auto35.twin_daggers']) == 2, 'both swings resolved'
    aimed = [r for r in e.events if r.event_type == 'CHECK_ROLLED' and r.source_definition_id.endswith('#complete_aim')]
    forced = [r for r in e.events if r.event_type == 'REACTION_RESOLVED' and r.source_definition_id == FORCE]
    assert len(aimed) + len(forced) == (0 if pick is None else 1), 'at most one response per mark'
    assert len([p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.yang_aim_attack']) == \
        (2 if pick is None else 1), 'the second swing is asked again only while the round is unspent'
    assert bears_mark(e.state.actors[OWNER], OWNER, 'Kindled Mark') is (pick is None)
    assert (e.state.actors[OWNER].turn_flags.get(ROUND) == e.state.round_number) is (pick is not None)


def test_native_save_aim_never_treats_the_acting_creature_as_the_caster(tmp_path):
    """"the marked subject ... forces one or more creatures to make a saving throw": the mark belongs to
    the creature FORCING the save. A native effect (a zone, an aura) can force a save while a different
    creature is acting, so the forcing creature is the d20 frame's own ``source_actor_id`` and never the
    current intent's actor.

    Here the OWNER is marked and is the creature acting, while the frame names a different creature as
    the source. Taking the acting creature as the caster is what let a marked creature spend its own
    mark to lower its own throw; the mark is not spent here."""
    from types import SimpleNamespace
    from combat.gate2_runtime_models import DiceSpec
    from combat.ext.yang_recovery import complete_aim_native_attack
    combat, table, mid = fixture(tmp_path, ['TAL_YANG_FURNACE_BACKLASH'], foe_position={'x': 3, 'y': 5})
    settle(table, mid, candidate(combat, mid, 'Kindle the Rising', target=OWNER).candidate_id)
    e = reload(tmp_path, mid)
    foe = e.state.actors[FOE]
    source = 'action:test.auto35.foreign_effect'
    e.action_catalog[source] = SimpleNamespace(resolution_kind='EFFECT', display_name='Blackwater', owner_id=FOE)
    e._active_intent = SimpleNamespace(actor_id=OWNER)  # the marked creature is acting; it is not the caster

    def ask_for(frame_source):
        e._d20_scopes = ()
        with e.d20_scope({'kind': 'save', 'actor_id': foe.entity_id, 'target_id': foe.entity_id,
                          'ability': 'CON', 'dc': 15, 'source_id': source, 'source_actor_id': frame_source}):
            roll = e.roller.roll(DiceSpec(count=1, sides=20), actor_id=foe.entity_id, reason=f'SAVE:{source}:CON')
        return complete_aim_native_attack(e, roll, e._active_intent)

    # The frame names a creature that bears no Kindled Mark: inert, rather than crediting the actor.
    assert ask_for(FOE) is None
    # No forcing creature in the frame at all: inert too, rather than treating the roller as the caster.
    assert ask_for(None) is None
    # Either way the marked OWNER's own Kindled Mark is untouched -- checked in memory, because these
    # frames were rolled on the loaded engine and nothing was committed for a reload to find.
    assert bears_mark(e.state.actors[OWNER], OWNER, 'Kindled Mark')
    assert not [r for r in e.rolls if str(r.reason).startswith('COMPLETE_AIM')], 'no die was rolled'
    assert e.state.actors[OWNER].turn_flags.get(ROUND) != e.state.round_number
    assert bears_mark(reload(tmp_path, mid).state.actors[OWNER], OWNER, 'Kindled Mark')


@pytest.mark.parametrize('accept', [True, False])
def test_complete_aim_reduces_a_native_save_and_spends_the_mark(tmp_path, accept):
    """Complete Aim answers a save forced by an older (non-typed) action, not only typed techniques.
    The printed die is *subtracted*: this asserts the negative contribution itself, not just that the
    rewritten roll happens to equal the stored one."""
    source = 'action:test.auto35.native_save'
    def prepare(bundles):
        bundles[0]['action_catalog'].append(
            _native_save_action(OWNER, source, 'Resonant Note').model_dump(mode='json'))
        bundles[0]['actor_template']['action_ids'].append(source)
        _seal(bundles[0])
    combat, table, mid = fixture(tmp_path, ['TAL_YANG_FURNACE_BACKLASH'],
        foe_position={'x': 3, 'y': 5}, bundle_transform=prepare)
    settle(table, mid, candidate(combat, mid, 'Kindle the Rising', target=OWNER).candidate_id)
    turn(table, mid, OWNER)
    prompts = settle(table, mid, candidate(combat, mid, 'Resonant Note', target=FOE).candidate_id,
                     {'choice:needle.yang_aim_save': FOE} if accept else {'choice:needle.yang_aim_save': None})
    assert any(p['context']['reaction_source_id'] == 'choice:needle.yang_aim_save' for p in prompts)
    e = reload(tmp_path, mid)
    save = next(r for r in e.events if r.event_type == 'SAVE_ROLLED' and r.source_definition_id == source)
    rolls = [r for r in e.events if r.event_type == 'CHECK_ROLLED' and r.source_definition_id.endswith('#complete_aim')]
    assert bool(rolls) == accept
    if accept:
        die = rolls[0].payload['total']
        assert 1 <= die <= 6, 'the printed 1d4, becoming 1d6 at CL 11'
        rewritten = [r for r in e.events if r.event_type == 'D20_REWRITTEN' and r.source_definition_id.endswith('#complete_aim')]
        assert rewritten, 'the Aim bonus must be attributed on the native save'
        payload = rewritten[0].payload
        # The mechanical contribution, asserted against the roll it rewrote: a bonus of any other
        # sign or size would still make "rewritten == stored save" true, so check the numbers.
        assert payload['bonus'] == -die
        original, result = payload['original'], payload['result']
        assert result['modifier'] == original['modifier'] - die
        assert result['total'] == original['total'] - die
        assert original['total'] == original['natural_result'] + original['modifier']
        assert save.payload['total'] == result['total']
    assert bears_mark(e.state.actors[OWNER], OWNER, 'Kindled Mark') != accept


def test_aim_arbitration_answers_itself_on_an_ai_turn(tmp_path):
    """Checklist item 9: the owner who has to decide is an AI, not the marked creature.

    Complete Aim may only be picked by a marked subject's owner, and the owner is on automatic control
    here while the marked ally swings. The attack therefore has to commit with no question reaching the
    table, and the AI's answer still spends exactly one response for the one mark."""
    combat, table, mid = fixture(tmp_path, ['TAL_YANG_FURNACE_BACKLASH'],
                                ally_kit={'starting_kit': KIT}, foe_position={'x': 5, 'y': 6})
    settle(table, mid, candidate(combat, mid, 'Kindle the Rising', target=ALLY).candidate_id)
    turn(table, mid, ALLY)
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    attack = candidate(combat, mid, 'Bi Shou (Dagger) attack', target=FOE)
    result = act(table, mid, attack.candidate_id)
    assert result['status'] == 'COMMITTED', result  # an AI owner decided on its own
    e = reload(tmp_path, mid)
    aimed = [r for r in e.events if r.event_type == 'CHECK_ROLLED' and r.source_definition_id.endswith('#complete_aim')]
    assert len(aimed) == 1, 'the AI owner spent the one Kindled Mark on exactly one response'
    assert not bears_mark(e.state.actors[ALLY], OWNER, 'Kindled Mark')
    assert e.state.actors[OWNER].turn_flags[ROUND] == e.state.round_number
    assert all(ev.actor_id == OWNER for ev in aimed), 'the die belongs to the mark owner'


# ------------------------------------------------------------------ AUTO136r2f1: the choice is enforced


def _two_marks(tmp_path, **kwargs):
    """Two Kindled Marks placed by the OWNER, one on each of its own creatures (Twofold Rising's printed
    "Kindle Two Creatures" mode), which is the only way the owner and an ally both bear its mark."""
    combat, table, mid = fixture(tmp_path, ['TAL_YANG_TWOFOLD_RISING', 'TAL_YANG_FURNACE_BACKLASH'],
                                seed='H5-CHOICES', **kwargs)
    mode = next(c for c in combat._load_session(mid).engine.legal_candidates()
                if c.source_definition_id in combat._load_session(mid).engine.action_catalog
                and 'Kindle Two Creatures' in combat._load_session(mid).engine.action_catalog[c.source_definition_id].display_name)
    settle(table, mid, mode.candidate_id, {'choice:needle.twofold_kindled': [OWNER, ALLY]})
    return combat, table, mid


@pytest.mark.parametrize('auto_owner', [False, True])
def test_a_marked_ally_swing_is_never_offered_the_owners_own_hit_response(tmp_path, auto_owner):
    """Complete Force answers "the marked subject deals damage" -- its owner's OWN hit. When the owner
    and an ally both bear its marks and the ALLY is the one swinging, that row cannot answer at all, so
    offering it (or defaulting to it) would take Complete Aim away and give the player nothing instead.

    The eligibility filter therefore judges each rival against the creature actually attacking and the
    creature actually attacked, through the engine's own readers, not against the row kind alone.
    """
    combat, table, mid = _two_marks(tmp_path, ally_kit={'starting_kit': KIT}, foe_position={'x': 5, 'y': 6})
    e = reload(tmp_path, mid)
    assert bears_mark(e.state.actors[OWNER], OWNER, 'Kindled Mark')
    assert bears_mark(e.state.actors[ALLY], OWNER, 'Kindled Mark')
    turn(table, mid, ALLY)
    attack = candidate(combat, mid, 'Bi Shou (Dagger) attack', target=FOE)
    if auto_owner:
        combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
        assert act(table, mid, attack.candidate_id)['status'] == 'COMMITTED'
        prompts = []
    else:
        prompts = settle(table, mid, attack.candidate_id)
        menu = _aim_menu(prompts)
        ids = [o['id'] for o in menu['choice']['options']]
        assert ids == ['use'], f'only the owner\'s own swing can answer its own hit response, got {ids}'
    e = reload(tmp_path, mid)
    forced = [r for r in e.events if r.event_type == 'REACTION_RESOLVED' and r.source_definition_id == FORCE]
    aimed = [r for r in e.events if r.event_type == 'CHECK_ROLLED' and r.source_definition_id.endswith('#complete_aim')]
    assert not forced, 'the owner\'s own-hit response never answers an ally\'s swing'
    assert len(aimed) == 1, 'and the default answer is the one the ally\'s swing can actually use'
    assert not bears_mark(e.state.actors[ALLY], OWNER, 'Kindled Mark')
    assert bears_mark(e.state.actors[OWNER], OWNER, 'Kindled Mark')


def test_a_marked_creature_lowers_a_save_it_forces_on_another_creature(tmp_path):
    """"the marked subject ... forces one or more creatures to make a saving throw": the caster is the
    marked creature and the roller is somebody else, so the mark is the caster's owner's to spend. A real
    table commit and a cold reload, not a hand-built d20 frame."""
    source = 'action:test.auto35.native_save'

    def prepare(bundles):
        bundles[1]['action_catalog'].append(_native_save_action(ALLY, source, 'Resonant Chime').model_dump(mode='json'))
        bundles[1]['actor_template']['action_ids'].append(source)
        _seal(bundles[1])

    combat, table, mid = fixture(tmp_path, ['TAL_YANG_FURNACE_BACKLASH'], ally_kit={'starting_kit': KIT},
                                foe_position={'x': 3, 'y': 5}, bundle_transform=prepare)
    settle(table, mid, candidate(combat, mid, 'Kindle the Rising', target=ALLY).candidate_id)
    turn(table, mid, ALLY)
    prompts = settle(table, mid, candidate(combat, mid, 'Resonant Chime', target=FOE).candidate_id,
                     {'choice:needle.yang_aim_save': FOE})
    assert any(p['context']['reaction_source_id'] == 'choice:needle.yang_aim_save' for p in prompts)
    e = reload(tmp_path, mid)
    die = next(r for r in e.events if r.event_type == 'CHECK_ROLLED' and r.source_definition_id.endswith('#complete_aim'))
    assert die.actor_id == OWNER, 'the die belongs to the marked creature\'s owner, which is not the roller'
    rewritten = next(r for r in e.events if r.event_type == 'D20_REWRITTEN' and r.source_definition_id.endswith('#complete_aim'))
    assert rewritten.payload['bonus'] == -die.payload['total']
    save = next(r for r in e.events if r.event_type == 'SAVE_ROLLED' and r.actor_id == FOE)
    assert save.payload['total'] == rewritten.payload['result']['total']
    assert not bears_mark(e.state.actors[ALLY], OWNER, 'Kindled Mark')
    assert e.state.actors[OWNER].turn_flags[ROUND] == e.state.round_number


def test_the_forcing_creature_and_not_the_acting_creature_owns_the_off_turn_native_save(tmp_path):
    """A foe enters a marked owner's stock native zone on its own turn, then cold-replays it.

    Compile Yang ownership on Bai's native actor id, retaining its stock zone
    action without replacing or patching the native catalog.
    """
    from combat.factory_compiler import compile_character
    from combat.tabletop_service import TabletopService
    from combat.gate2_runtime_content import BAI
    from tests.h1_support import sheet
    source = 'action:bai_meizhen.blackwater_serpent_court'
    ids = [BAI, ALLY, FOE]
    bundles = []
    for i, aid in enumerate(ids):
        talents = ['TAL_YANG_TWOFOLD_RISING', 'TAL_YANG_FURNACE_BACKLASH'] if i == 0 else []
        bundle = compile_character(sheet(talents, cl=15), actor_id=aid, reaction_plan={'ask': True})
        bundle['actor_template'].update(initiative_bonus=100 - 100 * i, maximum_hp=1000)
        if aid == BAI:
            bundle['actor_template']['action_ids'].append(source)
            bundle['actor_template']['resources'].append(
                {'resource_id': 'resource:bai_meizhen.qi', 'initial': 100, 'maximum': 100})
        if aid == FOE:
            bundle['actor_template']['saving_throws'] = {'CON': 100}
        bundles.append(_seal(bundle))
    combat = CombatService(ROOT, tmp_path)
    session = combat.persistence.create_match(match_seed='AUTO136-OFF-TURN', typed_bundles=bundles,
        roster_setup={'primary_actor_ids': ids,
                      'team_by_actor': {BAI: 'team:a', ALLY: 'team:a', FOE: 'team:b'},
                      'starting_positions': {BAI: {'x': 3, 'y': 6}, ALLY: {'x': 4, 'y': 6}, FOE: {'x': 6, 'y': 6}}})
    table, mid = TabletopService(combat, tmp_path), session.match_id
    turn(table, mid, BAI)
    e = combat._load_session(mid).engine
    mode = next(c for c in e.legal_candidates() if c.source_definition_id in e.action_catalog
                and 'Kindle Two Creatures' in e.action_catalog[c.source_definition_id].display_name)
    settle(table, mid, mode.candidate_id, {'choice:needle.twofold_kindled': [BAI, ALLY]})
    e = combat._load_session(mid).engine
    zone = next(c for c in e.legal_candidates() if c.source_definition_id == source
                and c.destination and (c.destination.x, c.destination.y) == (11, 6))
    settle(table, mid, zone.candidate_id)
    turn(table, mid, FOE)
    e = combat._load_session(mid).engine
    move = next(c for c in e.legal_candidates() if c.kind == 'MOVE' and c.destination
                and (c.destination.x, c.destination.y) == (7, 6))
    prompts = settle(table, mid, move.candidate_id, {'choice:needle.yang_aim_save': FOE})
    assert any(p['context']['reaction_source_id'] == 'choice:needle.yang_aim_save' for p in prompts)
    e = reload(tmp_path, mid)
    die = next(r for r in e.events if r.event_type == 'CHECK_ROLLED' and r.source_definition_id.endswith('#complete_aim'))
    assert die.actor_id == BAI, 'the mark owner answers on the moving foe\'s turn'
    rewritten = next(r for r in e.events if r.event_type == 'D20_REWRITTEN' and r.source_definition_id.endswith('#complete_aim'))
    assert rewritten.payload['bonus'] == -die.payload['total']
    save = next(r for r in e.events if r.event_type == 'SAVE_ROLLED' and r.source_definition_id == source)
    assert save.payload['total'] == rewritten.payload['result']['total']
    assert e.state.current_actor_id == FOE
    assert not bears_mark(e.state.actors[BAI], BAI, 'Kindled Mark')
    assert bears_mark(e.state.actors[ALLY], BAI, 'Kindled Mark')
    assert e.state.actors[BAI].turn_flags[ROUND] == e.state.round_number


@pytest.mark.parametrize('first', ['USE', 'DECLINE'])
def test_paid_occurrences_have_independent_answers_and_cold_replay(tmp_path, first):
    talent = 'TAL_YANG_FORCE_COMPLETION'
    def prepare(bundles):
        paid = {'type': 'paid_option', 'talent': talent, 'name': 'Force Completion',
                'ways': [[{'resource_id': 'resource:core.qi', 'amount': 2}]],
                'effects': [{'type': 'damage', 'flat': 3, 'damage_types': ['force'], 'applies_to': 'target'}]}
        _add_action(bundles[0], 'Two paid occurrences', [paid, copy.deepcopy(paid)])
        _seal(bundles[0])
    combat, table, mid = fixture(tmp_path, [talent], bundle_transform=prepare)
    cid = candidate(combat, mid, 'Two paid occurrences', target=FOE).candidate_id
    before = reload(tmp_path, mid).state.model_dump(mode='json')
    answers, keys = [], []
    for selection in (first, 'DECLINE' if first == 'USE' else 'USE'):
        result = act(table, mid, cid, answers)
        assert result['status'] == 'REACTION_REQUIRED'
        prompt = result['reaction']
        assert prompt['context']['reaction_source_id'] == 'choice:paid_option.' + talent
        keys.append(prompt['context']['checkpoint'])
        assert reload(tmp_path, mid).state.model_dump(mode='json') == before
        answers.append({**prompt['context'], 'selection': selection,
                        'option_ids': ['0'] if selection == 'USE' else []})
    assert keys[0] != keys[1], 'separate occurrences must not reuse an answer'
    assert act(table, mid, cid, answers)['status'] == 'COMMITTED'
    e = reload(tmp_path, mid)
    assert e.state.actors[OWNER].resources['resource:core.qi'] == 98
    assert e.state.actors[FOE].current_hp == before['actors'][FOE]['current_hp'] - 3


def test_selected_force_on_a_miss_keeps_the_mark_and_round_allowance(tmp_path):
    def prepare(bundles):
        bundles[2]['actor_template']['armor_class'] = 1000
        _seal(bundles[2])
    combat, table, mid = fixture(tmp_path, ['TAL_YANG_FURNACE_BACKLASH'], owner_kit={'starting_kit': KIT},
                                foe_position={'x': 3, 'y': 5}, bundle_transform=prepare)
    settle(table, mid, candidate(combat, mid, 'Kindle the Rising', target=OWNER).candidate_id)
    settle(table, mid, candidate(combat, mid, 'Bi Shou (Dagger) attack', target=FOE).candidate_id,
           {'choice:needle.yang_aim_attack': FORCE})
    e = reload(tmp_path, mid)
    assert any(ev.event_type == 'ATTACK_ROLLED' and not ev.payload['provisional_hit'] for ev in e.events)
    assert not any(ev.event_type == 'REACTION_RESOLVED' and ev.source_definition_id == FORCE for ev in e.events)
    assert bears_mark(e.state.actors[OWNER], OWNER, 'Kindled Mark')
    assert e.state.actors[OWNER].turn_flags.get(ROUND) != e.state.round_number
