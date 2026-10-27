"""Review fixes for AUTO85 (2026-10-05), at the level the review said AUTO85's own table tests could not reach.

``tests/test_auto85_monkey_style.py`` now covers the printed scope, the exact-roll settlement, the improvised-weapon
attacks, Monkey Catches the Moon's geometry and Impossible Ape Reversal's count through the engine. This file drives the
two things that must be shown at the real table, through ``CombatService``/``TabletopService`` and a table commit: the
state these fixes store (a spent Monkey Link Finish, a half-cover condition and the half cover's expiry), and the
player-owned "choose" lists -- asked on an AI turn under manual control + Ask me, with the AI's own automatic answer.
It also drives the two questions the AUTO85r1 review said could not be read from the plug-in alone: which creature
Monkey Catches the Moon's improvised-weapon option names (the ally the shot missed, and the shot itself, both read off
the real recorded attack), and that Laughing Theft of Timing's printed scope is still there after a commit and a reload.
"""
import copy

import pytest

from combat.ext import monkey
from tests.r1i_service_support import OWNER, FOE, SECOND, fixture
from tests.test_r1i_round3 import reload

M = 'TAL_MONKEY_STYLE_'
BASES = [M + 'CAPERING_FOOTWORK', M + 'LAUGHING_STAFF_AND_BORROWED_WEAPON', M + 'MONKEY_GRIP', M + 'MONKEY_STYLE_TRAINING']
COVER = 'give the missed ally Half Cover until the start of your next turn'
# Impossible Ape Reversal's six printed results, as the owner reads them.
REVERSAL_RESULTS = (
    'the triggering attack misses, or the triggering grapple or restraint fails',
    'move up to half your Speed without provoking opportunity attacks',
    'the triggering creature falls Prone',
    'the triggering creature drops one held object',
    'make one melee or improvised-weapon attack against the triggering creature',
    'create a Monkey Link that lasts until the end of your next turn',
)
STAFF_KIT = {'starting_kit': {'items': [{'item_id': 'tianxia.mortal.weapon.gun', 'quantity': 1}]}}


def monkey_fixture(folder, talents, **kw):
    """A real table with a Monkey Style owner; the sphere's own base abilities are listed the way combat's compiler adds
    them, and the staff is in the starting kit so a printed staff Finish has a staff to finish with."""
    return fixture(folder, [*BASES, *talents], owner_kit=STAFF_KIT, **kw)


def _labels(prompt):
    return [str(option.get('label') or option.get('id')) for option in (prompt.get('choice') or {}).get('options') or []]


def drive(send, cid, *, use, pick=None, automatic=False, recipients=()):
    """Commit one table action, answering every question it raises: ``use`` names the abilities whose question is
    accepted (a printed Reaction is a player's decision), ``pick`` the printed result to prefer from a list -- or, when an
    action asks more than one list (a movement and then the printed list it opens), one such result per list, in the order
    they are asked. The number answered is the question's own printed minimum, so a list that prints "choose two" cannot be
    answered with one. ``automatic`` hands the question to the shipped AI controller instead (``table.auto_step``)."""
    answers, prompts, lists = [], [], 0
    for _ in range(20):
        result = send(cid, answers, auto=automatic)
        if result['status'] == 'COMMITTED':
            return prompts
        assert result['status'] == 'REACTION_REQUIRED', result
        prompt = result['reaction']
        prompts.append(prompt)
        answer = {**prompt['context'], 'selection': 'DECLINE'}
        choice = prompt.get('choice') or {}
        if recipients and prompt['context']['reaction_source_id'] == 'choice:needle.area_recipients':
            offered = {o['id'] for o in choice['options']}
            assert set(recipients) <= offered
            answer.update(selection='USE', option_ids=list(recipients))
            answers.append(answer)
            continue
        if choice.get('options'):
            want = max(int(choice.get('minimum') or 1), 1)
            labels = choice['options']
            wanted = (pick[lists] if lists < len(pick) else None) if isinstance(pick, (list, tuple)) else pick
            lists += 1
            preferred = [option['id'] for option in labels if wanted and wanted in str(option.get('label') or '')]
            answer.update(selection='USE', option_ids=[*preferred, *[o['id'] for o in labels if o['id'] not in preferred]][:want])
        elif prompt.get('reaction') in use:
            answer['selection'] = 'USE'
        answers.append(answer)
    raise AssertionError('too many prompts')


def _to_turn(table, mid, actor):
    for _ in range(8):
        if table.state(mid)['menu']['actor_id'] == actor:
            return
        state = table.state(mid)['menu']
        table.act(mid, state['end_turn'], state['decision_id'], state['state_version'], 0, [])
    raise AssertionError(f'{actor} never came up')


def _certain_hit(bundles, actor_id, source_id, label, bonus=100):
    """A test-only delivery for the fixture: the ability under test is the owner's, not the way the hit arrives. The
    printed action is re-registered under a fixture id (its own id is replaced, so the catalogue stays consistent)."""
    from combat.canonical import canonical_sha256

    bundle = next(b for b in bundles if b['actor_id'] == actor_id)
    for index, action in enumerate(bundle['action_catalog']):
        if action['display_name'] != label:
            continue
        old = action['source_definition_id']
        action = copy.deepcopy(action)
        action.update(source_definition_id=source_id, display_name=f'Test {label}', attack_bonus=bonus)
        action['parameters']['typed']['numbers']['attack_bonus'] = bonus
        bundle['action_catalog'][index] = action
        bundle['actor_template']['action_ids'] = [source_id if a == old else a for a in bundle['actor_template']['action_ids']]
        bundle.pop('bundle_sha256', None)
        bundle['bundle_sha256'] = canonical_sha256(bundle)
        return
    raise AssertionError(f'no {label} to copy')


def _staff_hit(bundles):
    """The owner's staff in hand, striking certainly: the printed base Finish is spent inside that hit."""
    _certain_hit(bundles, OWNER, 'test:auto85f1.staff_hit', 'Gun (Staff) attack')


def _ranged_miss(bundles):
    """A test-only ranged strike for the opponent: the ability under test is Monkey Catches the Moon, which answers a
    ranged attack that missed an ally, so the delivery itself is a fixture (as tests/test_a11_creature_kinds.py does)."""
    from combat.canonical import canonical_sha256

    foe = next(b for b in bundles if b['actor_id'] == FOE)
    strike = copy.deepcopy(next(a for a in foe['action_catalog'] if a['display_name'] == 'Unarmed Strike'))
    strike.update(source_definition_id='test:auto85f1.ranged_miss', display_name='Test longbow shot at the ally',
                  attack_bonus=-100, range_ft=60, target_kind='ANY_CREATURE')
    strike['parameters']['typed'].update(range={'kind': 'feet', 'feet': 60}, long_range_ft=60, range_ft=60,
                                         effects=[{"type": "attack", "attack_kind": "ranged", "count": 1,
                                                   "on_hit": [], "on_miss": []}])
    strike['parameters']['typed']['numbers']['attack_bonus'] = -100
    foe['action_catalog'].append(strike)
    foe['actor_template']['action_ids'].append(strike['source_definition_id'])
    foe.pop('bundle_sha256', None)
    foe['bundle_sha256'] = canonical_sha256(foe)


def _foe_certain_strike(bundles):
    """The opponent's strike lands, so the owner's printed reaction to being hit is really answered."""
    _certain_hit(bundles, FOE, 'test:auto85f1.foe_hit', 'Unarmed Strike')


def test_moon_catches_half_cover_survives_a_table_commit_reload_and_ends_when_the_engine_says(tmp_path):
    """Monkey Catches the Moon, on the opponent's own turn: "Move up to 10 feet ... choose one: ... give the missed ally
    Half Cover until the start of your next turn". The owner is asked both questions (manual control + Ask me) even
    though the creature acting is the AI's, may answer the movement with zero feet, and the condition committed here is
    reloaded from disk and gone once the start of the owner's next turn arrives."""
    from tests.r1i_service_support import candidate

    combat, table, mid, send, _ = monkey_fixture(tmp_path, [M + 'MONKEY_CATCHES_THE_MOON'], bundle_transform=_ranged_miss,
        allies=(SECOND,), positions={OWNER: {"x": 6, "y": 7}, FOE: {"x": 8, "y": 5}, SECOND: {"x": 7, "y": 6}})
    _to_turn(table, mid, FOE)
    prompts = drive(send, candidate(table, mid, 'Test longbow shot at the ally', SECOND),
                    use=('Monkey Catches the Moon',), pick=COVER)
    step = [p for p in prompts if 'step up to 10 feet' in str(p.get('moment') or '')]
    listed = [p for p in prompts if any(COVER in label for label in _labels(p))]
    assert step, [(str(p.get('moment'))[:90], _labels(p)) for p in prompts]
    assert 'Stay where you are' in _labels(step[0]), _labels(step[0])   # "up to 10 feet" permits zero feet
    assert listed, [(_labels(p), str(p.get('moment'))[:90]) for p in prompts]
    assert listed[0]['choice']['minimum'] == 1 and listed[0]['choice']['maximum'] == 1, 'the printed list is "choose one"'
    assert 'Choose 1 of these 4 results' in listed[0]['moment'], listed[0]['moment']
    after = reload(tmp_path, mid)
    held = [c for c in after.state.actors[SECOND].conditions.values() if c.condition_id == 'condition:typed.monkey_half_cover']
    assert held, 'the printed Half Cover did not survive the table commit and reload'
    assert held[0].expires_on == f'START_OF_TURN_AT:{OWNER}:2', held[0].expires_on
    assert '+2 AC' in str(held[0].data.get('label')), held[0].data
    assert after._cover_bonus_actor_to_actor(after.state.actors[FOE], after.state.actors[SECOND]) == 2
    _to_turn(table, mid, OWNER)
    later = reload(tmp_path, mid)
    assert not [c for c in later.state.actors[SECOND].conditions.values() if c.condition_id == 'condition:typed.monkey_half_cover'], \
        "the half cover outlasted the start of the owner's next turn"


def test_a_spent_monkey_link_finish_is_recorded_as_a_string_and_survives_a_reload(tmp_path):
    """A base Finish ("Tap: Deal extra Bludgeoning damage equal to your Proficiency Bonus") is spent inside the staff hit
    it rides, and what the fight keeps is a string naming the creature: it must come back through a real commit + reload
    (checklist 7: nothing stored in fight state may be a float or an object)."""
    from tests.r1i_service_support import candidate

    combat, table, mid, send, _ = monkey_fixture(tmp_path, [M + 'LAUGHING_THEFT_OF_TIMING'], bundle_transform=_staff_hit)
    before = reload(tmp_path, mid).state.actors[FOE].current_hp
    # "you may create and spend one Monkey Link" while the caper is up, then a staff hit that spends it on a Finish.
    assert drive(send, candidate(table, mid, 'Capering Footwork', OWNER), use=()) is not None
    assert drive(send, candidate(table, mid, 'Monkey Link (climb, swing, prop: GM)', OWNER), use=()) is not None
    prompts = drive(send, candidate(table, mid, 'Test Gun (Staff) attack', FOE), use=(), pick='Tap Finish')
    assert [p for p in prompts if any('Tap Finish' in label for label in _labels(p))], \
        [(_labels(p), str(p.get('moment'))[:80]) for p in prompts]
    after = reload(tmp_path, mid)
    assert after.state.actors[FOE].current_hp < before, 'the staff hit never landed'
    recorded = {key: value for key, value in after.state.actors[OWNER].turn_flags.items() if key.startswith(monkey.FINISHED_ON)}
    assert recorded == {monkey.FINISHED_ON + FOE: f'{after.state.round_number}:{after.state.current_slot_index}'}, after.state.actors[OWNER].turn_flags


@pytest.mark.parametrize('automatic', [False, True])
def test_ape_reversal_asks_for_exactly_two_results_on_an_ai_turn(tmp_path, automatic):
    """Impossible Ape Reversal: "Failed Save: Choose two: ...". The creature that hit is the AI's, and the owner's own
    choice is still asked (manual control + Ask me): the question says how many results it wants, its own bounds refuse
    one, and exactly two of the six printed results run -- whether the player's answer or the shipped AI controller's is
    the one that decides."""
    from tests.r1i_service_support import candidate, force_ai_candidate

    combat, table, mid, send, _ = monkey_fixture(tmp_path, [M + 'IMPOSSIBLE_APE_REVERSAL'], owner_dc=50, foe_ac=14,
                                                bundle_transform=_foe_certain_strike)
    _to_turn(table, mid, FOE)
    hit = candidate(table, mid, 'Test Unarmed Strike', OWNER)
    if automatic:
        force_ai_candidate(combat, mid, FOE, hit)
    prompts = drive(send, hit, use=('Impossible Ape Reversal',), pick=None if automatic else 'falls Prone',
                    automatic=automatic)
    asked = [p for p in prompts if 'choose 2 of these 6 results' in str(p.get('moment') or '').lower()]
    assert asked, [(str(p.get('moment'))[:100], _labels(p)) for p in prompts]
    assert len(_labels(asked[0])) == 6, _labels(asked[0])
    assert asked[0]['choice']['minimum'] == 2 and asked[0]['choice']['maximum'] == 2, asked[0]['choice']
    after = reload(tmp_path, mid)
    logs = [str((event.payload or {}).get('log') or '') for event in after.events
            if event.event_type == 'PASSIVE_TRIGGERED' and str(event.source_definition_id).endswith('APE_REVERSAL')]
    chosen = [line for line in logs if line.removeprefix('Impossible Ape Reversal: ').rstrip('.') in REVERSAL_RESULTS]
    assert len(chosen) == 2, logs
    if not automatic:
        assert any('falls Prone' in line for line in chosen), chosen
        assert any(c.condition_id.endswith('.prone') for c in after.state.actors[FOE].conditions.values()), \
            'the printed Prone result was never chosen'


MOON_ATTACK = ('make one improvised-weapon attack against a creature within 20 feet using the projectile or a nearby object')


def test_the_moons_improvised_attack_names_the_missed_ally_and_the_attack_that_missed(tmp_path):
    """"make one improvised-weapon attack against a creature within 20 feet using the projectile or a nearby object" --
    when two enemies are in that range the owner is asked which one, and the question a player reads must name what the
    reaction answered: the ally the ranged attack actually missed and that attack, not the nearest enemy on the map."""
    from tests.r1i_service_support import THIRD, candidate

    combat, table, mid, send, _ = monkey_fixture(tmp_path, [M + 'MONKEY_CATCHES_THE_MOON'], bundle_transform=_ranged_miss,
        allies=(SECOND,), extra_foe=True,
        positions={OWNER: {"x": 6, "y": 7}, FOE: {"x": 3, "y": 6}, SECOND: {"x": 7, "y": 6}, THIRD: {"x": 5, "y": 9}})
    _to_turn(table, mid, FOE)
    prompts = drive(send, candidate(table, mid, 'Test longbow shot at the ally', SECOND),
                    use=('Monkey Catches the Moon',), pick=['Stay where you are', MOON_ATTACK])
    asked = [prompt for prompt in prompts if 'within 20 feet' in str(prompt.get('moment') or '')]
    assert asked, [(str(p.get('moment'))[:100], _labels(p)) for p in prompts]
    read = str(asked[0]['moment'])
    assert 'Second' in read, f'the question did not name the missed ally: {read}'
    assert 'Test longbow shot at the ally' in read, f'the question did not name the attack that missed: {read}'
    assert len(_labels(asked[0])) == 2, _labels(asked[0])


def test_the_theft_scope_survives_a_table_commit_and_reload_only_within_the_same_turn(tmp_path):
    """Laughing Theft of Timing's printed scope, "a creature you affected with a Monkey Style Trick, Finish, or feint this
    turn", is recorded on the fighter who did it. This covers the first of those three -- a Monkey Link Finish spent against
    that creature, which rides an ordinary weapon's own events -- so it checks that this record comes back off disk through a
    real commit and reload, answers for the creature that was affected and for no other during that turn, and refuses
    its attack once the next creature's turn starts. (The other two are covered elsewhere: a printed Trick's own hit by
    the printed-scope test in tests/test_auto85_monkey_style.py, and a saving throw this fighter forced, below.)"""
    from tests.r1i_service_support import candidate

    combat, table, mid, send, _ = monkey_fixture(tmp_path, [M + 'LAUGHING_THEFT_OF_TIMING'],
                                                bundle_transform=lambda bundles: (_staff_hit(bundles), _foe_certain_strike(bundles)))
    drive(send, candidate(table, mid, 'Capering Footwork', OWNER), use=())
    drive(send, candidate(table, mid, 'Monkey Link (climb, swing, prop: GM)', OWNER), use=())
    drive(send, candidate(table, mid, 'Test Gun (Staff) attack', FOE), use=(), pick='Tap Finish')
    after = reload(tmp_path, mid)
    recorded = {key: value for key, value in after.state.actors[OWNER].turn_flags.items() if key.startswith(monkey.FINISHED_ON)}
    assert recorded == {monkey.FINISHED_ON + FOE: f'{after.state.round_number}:{after.state.current_slot_index}'}, after.state.actors[OWNER].turn_flags
    row = {'feature_id': M + 'LAUGHING_THEFT_OF_TIMING'}
    assert monkey.theft_subject(after, after.state.actors[OWNER], after.state.actors[FOE], row) is None, \
        'the printed scope did not survive the table commit and reload'
    assert monkey.theft_subject(after, after.state.actors[OWNER], after.state.actors[SECOND], row) is False, \
        'a creature the fighter never affected is inside the printed scope'
    _to_turn(table, mid, FOE)
    drive(send, candidate(table, mid, 'Test Unarmed Strike', OWNER), use=('Laughing Theft of Timing',))
    reloaded = reload(tmp_path, mid)
    answered = [event for event in reloaded.events if event.event_type == 'REACTION_RESOLVED'
                and str(event.source_definition_id).endswith('LAUGHING_THEFT_OF_TIMING')]
    assert not answered, 'a Finish from a previous creature turn still opened Theft after reload'


def test_a_forced_save_is_recorded_on_the_fighter_that_forced_it_and_ends_with_its_turn(tmp_path):
    """"a creature you affected with a Monkey Style Trick, Finish, or feint this turn" -- the second of those three: a
    saving throw this fighter forced. It is the only part of the scope a SAVE_ROLLED event cannot answer on its own (the
    event names the creature that rolled and the ability that asked, never the fighter that used it), so the fight records
    the fighter here. Heaven-Uprooting Staff forces that save outright ("Creatures of your choice inside a 30-foot-radius
    sphere centered on that point make Dexterity saving throws"), so nothing has to land a strike first. This drives it
    through the real service with two Monkey Style fighters in the fight: only the one who forced the saves comes back off
    disk holding the record, the other is still outside the printed scope, and the record is a plain round/slot string
    a reload can carry (checklist 7). It is ineligible at the very next creature turn, then removed at the owner's turn;
    it cannot grant Theft beyond the printed "this turn" window."""
    from tests.r1i_service_support import candidate

    combat, table, mid, send, _ = monkey_fixture(tmp_path, [M + 'LAUGHING_THEFT_OF_TIMING', M + 'HEAVEN_UPROOTING_STAFF'],
                                                second_talents=[M + 'LAUGHING_THEFT_OF_TIMING'])
    drive(send, candidate(table, mid, 'Capering Footwork', OWNER), use=())
    drive(send, candidate(table, mid, 'Heaven-Uprooting Staff'), use=(), recipients=(FOE, SECOND))
    after = reload(tmp_path, mid)
    saved = {event.actor_id for event in after.events if event.event_type == 'SAVE_ROLLED'}
    assert {FOE, SECOND} <= saved, f'the printed staff forced no saving throws to attribute: {sorted(saved)}'
    recorded = {key: value for key, value in after.state.actors[OWNER].turn_flags.items()
                if key.startswith(monkey.AFFECTED_ON)}
    stamp = f'{after.state.round_number}:{after.state.current_slot_index}'
    assert recorded == {monkey.AFFECTED_ON + FOE: stamp, monkey.AFFECTED_ON + SECOND: stamp}, \
        after.state.actors[OWNER].turn_flags
    assert all(type(value) is str for value in recorded.values()), recorded
    assert [key for fighter in after.state.actors.values() for key in fighter.turn_flags
            if key.startswith(monkey.AFFECTED_ON) and fighter is not after.state.actors[OWNER]] == [], \
        'a forced save was recorded on a fighter that forced nothing'
    row = {'feature_id': M + 'LAUGHING_THEFT_OF_TIMING'}
    assert monkey.theft_subject(after, after.state.actors[OWNER], after.state.actors[FOE], row) is None, \
        'the fighter that forced the save is outside its own printed scope after a commit and a reload'
    assert monkey.theft_subject(after, after.state.actors[SECOND], after.state.actors[OWNER], row) is False, \
        "another Monkey Style fighter's forced save opened this fighter's reaction"
    _to_turn(table, mid, FOE)      # "this turn" ends at the very next creature's turn
    next_turn = reload(tmp_path, mid)
    assert monkey.theft_subject(next_turn, next_turn.state.actors[OWNER], next_turn.state.actors[FOE], row) is False
    _to_turn(table, mid, OWNER)    # a full round later, on the owner's own next turn
    later = reload(tmp_path, mid)
    assert [key for key in later.state.actors[OWNER].turn_flags if key.startswith(monkey.AFFECTED_ON)] == [], \
        'the recorded forced save outlived the printed "this turn"'
    assert monkey.theft_subject(later, later.state.actors[OWNER], later.state.actors[FOE], row) is False, \
        'a saving throw forced last turn still opens the reaction'
