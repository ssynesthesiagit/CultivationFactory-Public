"""Guardian talents automated by AUTO115 (review fixes AUTO115r1f1): Stand Against the Calamity and Inescapable Challenge.

Rules text: the owner's Sphere Compendium, "Sphere of Guardian"
(TAL_GUARDIAN_STAND_AGAINST_THE_CALAMITY, TAL_GUARDIAN_INESCAPABLE_CHALLENGE).

Who has them: the Guardian (LEFT). ALLY stands on its team inside the Calamity aura; RIGHT is the enemy.
The regressions exercise combat/ext/guardian_calamity.py, the movement_attempt hook in
combat/ext/guardian.py, and the object defense seam in combat/ext/objects.deal;
unowned and outside-radius cases are controls for their default-inert behavior.

The forced-movement and movement tests below submit real table transactions and commit them, so what they check
is what the table enforces: position and movement budget after a commit and a reload, and the recorded save.
"""
import pytest

from tests.hunt15_support import fight, act, reload, turn, LEFT, RIGHT, ALLY
from tests.auto_worker1_support import settle
from tests.auto_worker1_support import fight as worker1_fight

CALAMITY = 'TAL_GUARDIAN_STAND_AGAINST_THE_CALAMITY'
PRACTICE = 'GUARDIAN_BASE_CHALLENGE_PRACTICE'
INESCAPABLE = 'TAL_GUARDIAN_INESCAPABLE_CHALLENGE'
STATE = 'condition:typed.state.stand_against_the_calamity'
LABEL = 'Stand Against the Calamity'
TEST_ACTION = 'Test setup'
HIT = 10
PB = 4

SAVE_THEN_HIT = [
    {'type': 'save', 'ability': 'con', 'dc': 'technique_save_dc', 'applies_to': 'self',
     'on_fail': [], 'on_success': []},
    {'type': 'damage', 'flat': HIT, 'damage_types': ['fire'], 'applies_to': 'self'},
]
PUSH = [{'type': 'forced_movement', 'distance_ft': 10, 'direction': 'away', 'applies_to': 'target'}]


def engine(table, mid):
    return table.combat._load_session(mid).engine


def armor_class(table, mid, actor_id):
    """The Armor Class the table shows, out of the tabletop projection."""
    for row in table.state(mid)['presentation']['actors']:
        if row['entity_id'] == actor_id:
            return next(d['value'] for d in row['defenses'] if d['defense_id'] == 'defense:armor_class')
    raise AssertionError(f'{actor_id} is not in the projection')


def hp(table, mid, actor_id):
    return engine(table, mid).state.actors[actor_id].current_hp


def standing(table, mid, actor_id=LEFT):
    """Whether this Guardian is currently standing against a calamity."""
    return any(condition.condition_id == STATE for condition in engine(table, mid).state.actors[actor_id].conditions.values())


@pytest.mark.parametrize('talents', [[PRACTICE, CALAMITY], [PRACTICE]], ids=['owned', 'unowned'])
def test_printed_aura_gives_allies_two_armor_class(tmp_path, talents):
    c, t, m = fight(tmp_path, left=talents, right=[], ally=[], effects=[])
    turn(t, m, LEFT)
    before = armor_class(t, m, ALLY)
    assert standing(t, m) is False
    labels = [g['label'] for g in t.state(m)['menu']['actions']]
    assert (LABEL in labels) is (talents == [PRACTICE, CALAMITY])
    if talents == [PRACTICE]:
        return  # without the talent the Guardian never plants the stance, so nothing follows
    settle(lambda a: act(t, m, LABEL, a))
    assert standing(t, m) is True, "the printed stance lasts a minute and holds Concentration"
    assert armor_class(t, m, ALLY) == before + 2, "allies inside gain +2 AC"


def test_ally_saves_with_advantage_and_loses_less_damage_inside_the_aura(tmp_path):
    c, t, m = fight(tmp_path, left=[PRACTICE, CALAMITY], right=[], ally=[], effects=SAVE_THEN_HIT)
    turn(t, m, LEFT)
    turn(t, m, RIGHT)
    turn(t, m, ALLY)
    plain = ally_takes_the_hit(t, m)
    turn(t, m, LEFT)
    settle(lambda a: act(t, m, LABEL, a))
    assert standing(t, m) is True
    turn(t, m, RIGHT)
    turn(t, m, ALLY)
    guarded = ally_takes_the_hit(t, m)
    assert guarded['lost'] == plain['lost'] - PB, \
        "allies inside reduce all damage taken by your Proficiency Bonus"
    assert guarded['mode'] == 'ADVANTAGE', "allies inside gain Advantage on saving throws"


def position(table, mid, actor_id):
    cell = table.combat._load_session(mid).engine.state.actors[actor_id].position
    return (cell.x, cell.y)


def steps_moved(table, mid, actor_id, before):
    after = position(table, mid, actor_id)
    return max(abs(after[0] - before[0]), abs(after[1] - before[1]))


def budget(table, mid, actor_id):
    return table.combat._load_session(mid).engine.state.actors[actor_id].movement_remaining_ft


def submit_move(table, mid, destination):
    """Submit a real table MOVE to ``destination`` (an (x, y) pair) and commit it, answering any reaction."""
    state = table.state(mid)
    menu = state['menu']
    move = next(row for row in menu['moves'] if (row['destination']['x'], row['destination']['y']) == destination)
    cid, did, version, after = move['candidate_id'], menu['decision_id'], menu['state_version'], state['last_sequence']
    result, _prompts = settle(lambda answers: table.act(mid, cid, did, version, after, answers))
    return result


def save_ability(save):
    """The ability a recorded save was for, as the fight recorded it ("SAVE:<source>:<ability>")."""
    return str(save.payload.get('reason') or '').rsplit(':', 1)[-1]


# -------------------------------------------------------------------------------- the enemy Strength save
def guarded_push(t, m, *, target=ALLY, aura=True, seed_label=''):
    """RIGHT shoves ``target`` away from itself with the aura up; returns how far it went and the save it recorded."""
    turn(t, m, LEFT)
    if aura:
        settle(lambda a: act(t, m, LABEL, a))
        assert standing(t, m) is True
    turn(t, m, RIGHT)
    before = position(t, m, target)
    first = len(reload(t.combat, m).events)
    settle(lambda a: act(t, m, TEST_ACTION, a, target_id=target))
    went = steps_moved(t, m, target, before)
    saves = [e for e in reload(t.combat, m).events[first:]
             if e.event_type == 'SAVE_ROLLED' and e.source_definition_id == CALAMITY]
    return {'went': went, 'save': saves[-1] if saves else None}


def enemy_pushes_the_ally(t, m, *, aura):
    """RIGHT shoves ALLY away from itself; returns how far ALLY actually travelled."""
    return guarded_push(t, m, target=ALLY, aura=aura)['went']


def test_enemy_forcibly_moving_an_ally_makes_the_attacker_strength_save(tmp_path):
    """The printed clause: "an enemy attempting to forcibly move one creature inside makes a Strength saving throw."

    Recorded separately for the two outcomes across seeds: the enemy rolls it (not the moved ally), and the
    distance follows the roll -- nothing at all on a failed save, half the printed distance on a held save.
    """
    plain = None
    outcomes = {}
    for seed in range(12):
        c, t, m = fight(tmp_path / f'seed{seed}', left=[PRACTICE, CALAMITY], right=[], ally=[], effects=PUSH,
                        target='HOSTILE_ENTITY', seed=f'AUTO115-R1-{seed}')
        if plain is None:
            plain = enemy_pushes_the_ally(t, m, aura=False)
            assert plain > 0, "without the stance the ordinary push moves the ally"
        got = guarded_push(t, m, target=ALLY, aura=True)
        save = got['save']
        assert save is not None, "the Guardian's clause makes the enemy roll a save"
        assert save.actor_id == RIGHT, "ctx.actor is the creature doing the moving, so the attacker makes the save"
        assert save_ability(save) == 'STR', "the printed save is a Strength saving throw"
        expected = 0 if not save.payload['success'] else plain // 2
        assert got['went'] == expected, \
            "Failed Save: the forced movement fails.  Successful Save: move the target only half the normal distance."
        outcomes[bool(save.payload['success'])] = got['went']
    assert set(outcomes) == {False, True}, f"both save branches must be exercised, saw {sorted(outcomes)}"
    assert outcomes[False] == 0, "a failed Strength save leaves the ally exactly where it stood"


def test_the_standing_guardian_itself_is_covered_by_its_own_clause(tmp_path):
    """"one creature inside" is any creature in the aura -- the Guardian is not excluded from its own stance."""
    c, t, m = fight(tmp_path, left=[PRACTICE, CALAMITY], right=[], ally=[], effects=PUSH, target='HOSTILE_ENTITY')
    plain = guarded_push(t, m, target=LEFT, aura=False)['went']
    assert plain > 0, "without the stance the ordinary push moves the Guardian"
    got = guarded_push(t, m, target=LEFT, aura=True)
    assert got['save'] is not None and got['save'].actor_id == RIGHT
    assert got['went'] == (0 if not got['save'].payload['success'] else plain // 2), \
        "an enemy pushing the stance's own owner still faces the Strength save"


def test_a_friendly_creature_is_never_stopped_by_the_calamity_clause(tmp_path):
    """The clause bites only an enemy of the aura's owner; ALLY shoving RIGHT is not an enemy move."""
    c, t, m = fight(tmp_path, left=[PRACTICE, CALAMITY], right=[], ally=[], effects=PUSH, target='HOSTILE_ENTITY')
    turn(t, m, LEFT)
    settle(lambda a: act(t, m, LABEL, a))
    turn(t, m, RIGHT)
    turn(t, m, ALLY)
    before = position(t, m, RIGHT)
    first = len(reload(t.combat, m).events)
    settle(lambda a: act(t, m, TEST_ACTION, a, target_id=RIGHT))
    assert steps_moved(t, m, RIGHT, before) > 0, "an ally's own shove is ordinary movement"
    assert not [e for e in reload(t.combat, m).events[first:]
                if e.event_type == 'SAVE_ROLLED' and e.source_definition_id == CALAMITY], \
        "no Strength save for a creature on the aura owner's own team"


def test_an_ally_outside_the_thirty_foot_aura_gets_nothing(tmp_path):
    """The printed radius is 30 feet; an ally standing further out keeps no benefit."""
    far = {ALLY: {'x': 19, 'y': 10}, LEFT: {'x': 3, 'y': 6}, RIGHT: {'x': 4, 'y': 6}}
    c, t, m = fight(tmp_path, left=[PRACTICE, CALAMITY], right=[], ally=[], effects=[], positions=far)
    turn(t, m, LEFT)
    before = armor_class(t, m, ALLY)
    settle(lambda a: act(t, m, LABEL, a))
    assert standing(t, m) is True
    assert armor_class(t, m, ALLY) == before, "allies inside gain +2 AC -- an ally outside the 30 foot aura does not"


def test_willing_movement_ends_the_stance_and_its_benefits(tmp_path):
    """"ends early if you become Incapacitated or willingly move"."""
    c, t, m = fight(tmp_path, left=[PRACTICE, CALAMITY], right=[], ally=[], effects=[], positions={
        LEFT: {'x': 3, 'y': 6}, RIGHT: {'x': 4, 'y': 6}, ALLY: {'x': 3, 'y': 5}})
    turn(t, m, LEFT)
    settle(lambda a: act(t, m, LABEL, a))
    assert standing(t, m) is True
    guarded = armor_class(t, m, ALLY)
    turn(t, m, RIGHT)
    turn(t, m, LEFT)
    target = next(((row['destination']['x'], row['destination']['y']) for row in t.state(m)['menu']['moves']), None)
    assert target is not None, "the Guardian has somewhere to walk"
    before = position(t, m, LEFT)
    submit_move(t, m, target)
    assert steps_moved(t, m, LEFT, before) > 0, "the Guardian walked"
    assert standing(t, m) is False, "willingly moving ends the stance"
    assert armor_class(t, m, ALLY) == guarded - 2, "the ally loses the +2 AC the stance was granting"


def test_the_aura_survives_a_commit_and_a_fresh_service_reload(tmp_path):
    """The stance is stored state, so it still protects after the fight is closed, reloaded and re-read."""
    c, t, m = fight(tmp_path, left=[PRACTICE, CALAMITY], right=[], ally=[], effects=SAVE_THEN_HIT)
    turn(t, m, LEFT)
    settle(lambda a: act(t, m, LABEL, a))
    before = armor_class(t, m, ALLY)
    fresh = reload(c, m)
    assert any(row.condition_id == STATE for row in fresh.state.actors[LEFT].conditions.values()), \
        "the stance is still there after the fight is reloaded from disk"
    assert armor_class(t, m, ALLY) == before, "the reloaded aura still grants the ally its +2 AC"


# -------------------------------------------------------------------------------- structures inside the aura
CRATE = {"id": 1, "x": 3, "y": 5, "material": "wood", "size": "medium", "kind": "barricade"}
SMASH = [{'type': 'object_damage', 'flat': 10, 'damage_types': ['fire']}]
CRATE_ID = 'object:map.1'


def crate_arena(at, kind='barricade'):
    def edit(arena):
        arena['map_objects'] = [{**CRATE, 'x': at[0], 'y': at[1], 'kind': kind}]
    return edit


def burn_the_crate(c, t, m, *, aura):
    """RIGHT burns the crate and the hit points it really lost is read back off a reloaded fight."""
    if aura:
        settle(lambda a: act(t, m, LABEL, a))
    turn(t, m, RIGHT)
    before = c._load_session(m).engine.state.objects[CRATE_ID].current_hp
    settle(lambda a: act(t, m, 'Cause', a, target_id=CRATE_ID))
    return before - reload(c, m).state.objects[CRATE_ID].current_hp


def test_a_structure_inside_the_aura_resists_all_damage(tmp_path):
    """"structures and Formation Anchors inside gain Resistance to all damage".

    A real map object on a real object record, damaged through the ordinary object path, committed and reloaded.
    """
    c, t, m = worker1_fight(tmp_path, [PRACTICE, CALAMITY], cause=SMASH, cause_target='OBJECT',
                            cause_name='Cause', arena_edit=crate_arena((3, 5)))
    assert CRATE_ID in c._load_session(m).engine.state.objects, "the map's crate is a real object in this fight"
    from combat.object_rules import has_tag
    assert has_tag(reload(c, m).state.objects[CRATE_ID], 'structure')
    plain = burn_the_crate(c, t, m, aura=False)
    assert plain == 10, "without the stance the crate takes the printed 10 damage"
    other, table, mid = worker1_fight(tmp_path / 'guarded', [PRACTICE, CALAMITY], cause=SMASH,
                                      cause_target='OBJECT', cause_name='Cause', arena_edit=crate_arena((3, 5)))
    assert burn_the_crate(other, table, mid, aura=True) == 5, \
        "structures inside gain Resistance to all damage: 10 fire damage becomes 5"


def test_a_structure_outside_the_aura_takes_its_full_damage(tmp_path):
    # 35 feet from the Guardian (outside the printed 30 foot aura), 30 feet from the attacker (inside its range).
    c, t, m = worker1_fight(tmp_path, [PRACTICE, CALAMITY], cause=SMASH, cause_target='OBJECT',
                            cause_name='Cause', arena_edit=crate_arena((10, 5)))
    assert burn_the_crate(c, t, m, aura=True) == 10, \
        "a structure beyond the 30 foot aura is not protected"


# -------------------------------------------------------------------------------- Inescapable Challenge
CHALLENGE_POOL = [
    {'type': 'guardian_challenge', 'applies_to': 'target'},
    {'type': 'save', 'ability': 'str', 'dc': 'technique_save_dc', 'applies_to': 'self', 'on_fail': [], 'on_success': []},
]


@pytest.mark.parametrize('talents', [[PRACTICE, INESCAPABLE], [PRACTICE]], ids=['owned', 'unowned'])
def test_challenged_creature_walking_away_makes_a_wisdom_save(tmp_path, talents):
    """Inescapable Challenge: "willingly attempts to move farther away from you, it makes a Wisdom saving throw.
    Failed Save: Its attempted movement ends before carrying it farther away."

    This submits a real table move to the far side of the map, commits it and reloads, so the assertion is on the
    stored position and movement budget the fight really ends up with -- not on a unit call of the plug-in.
    """
    c, t, m = worker1_fight(tmp_path, talents, right_talents=['tianxia.talent.poison.miasma_form'],
                            prepare=CHALLENGE_POOL, right_score=1, prepare_target='HOSTILE_ENTITY')
    settle(lambda a: act(t, m, 'Prepare', a, target_id=RIGHT))
    fresh = reload(c, m)
    assert any(cnd.condition_id == 'condition:typed.challenged' for cnd in fresh.state.actors[RIGHT].conditions.values())
    turn(t, m, RIGHT)
    home = position(t, m, RIGHT)
    left_home = position(t, m, LEFT)
    away = max(((row['destination']['x'], row['destination']['y']) for row in t.state(m)['menu']['moves']),
               key=lambda cell: abs(cell[0] - left_home[0]) + abs(cell[1] - left_home[1]))
    assert abs(away[0] - left_home[0]) + abs(away[1] - left_home[1]) > abs(home[0] - left_home[0]) + abs(home[1] - left_home[1]), \
        "the test needs a real step that carries the challenged creature farther away"
    spent = budget(t, m, RIGHT)
    result = submit_move(t, m, away)
    assert result['status'] == 'COMMITTED'
    stored = reload(c, m).state.actors[RIGHT]
    if talents == [PRACTICE, INESCAPABLE]:
        assert (stored.position.x, stored.position.y) == home, \
            "Failed Save: its attempted movement ends before carrying it farther away"
        assert stored.movement_remaining_ft == spent, "a movement that never happened spends no movement"
    else:
        assert (stored.position.x, stored.position.y) == away, \
            "without Inescapable Challenge the challenged creature simply walks away"


# -------------------------------------------------------------------------------- Moon's Pull meets the stance
@pytest.mark.parametrize('aura,dc,selection,ai,expected,prompt_count', [
    (False, 30, '15', False, 3, 1),
    (False, 30, '5', False, 1, 1),
    (False, 30, None, False, 0, 1),
    (True, 1, '15', False, 1, 1),
    (True, 1, '5', False, 1, 1),
    (True, 1, None, False, 0, 1),
    (True, 30, '15', False, 0, 0),
    (True, 1, '15', True, 1, 0),
    (True, 30, '15', True, 0, 0),
])
def test_mandatory_cap_and_real_pull_choice(tmp_path, aura, dc, selection, ai, expected, prompt_count):
    """Real manual/Ask-me and AI transactions, including commit and fresh reload."""
    from combat.ext.abyssal_depths import MOON, PULL
    from tests.hunt15_support import action_sender
    def edit(bundle):
        if bundle['actor_template']['entity_id'] != RIGHT:
            return
        for action in bundle['action_catalog']:
            if action['display_name'] == 'Cause':
                action['parameters']['typed']['source'] = MOON
    c, t, m = worker1_fight(
        tmp_path, [PRACTICE, CALAMITY], left_save_dc=dc, right_score=1,
        cause=[{'type': 'forced_movement', 'distance_ft': 15, 'direction': 'toward',
                'applies_to': 'target', 'choose_distance': True}],
        positions={LEFT: {'x': 3, 'y': 6}, RIGHT: {'x': 7, 'y': 6}},
        bundle_edit=edit)
    if aura:
        settle(lambda answers: act(t, m, LABEL, answers))
    turn(t, m, RIGHT)
    home = position(t, m, LEFT)
    start = len(reload(c, m).events)
    send = action_sender(c, t, m, 'Cause', ai=ai, target_id=LEFT)
    def pick(prompt):
        assert prompt['context']['reaction_source_id'] == PULL
        return [selection] if selection is not None else []
    result, prompts = settle(send, pick)
    assert result['status'] == 'COMMITTED'
    assert len(prompts) == prompt_count
    assert steps_moved(t, m, LEFT, home) == expected
    fresh = reload(c, m)
    saves = [event for event in fresh.events[start:]
             if event.event_type == 'SAVE_ROLLED' and event.source_definition_id == CALAMITY]
    assert len(saves) == int(aura)
    if aura:
        assert saves[0].actor_id == RIGHT
        assert saves[0].payload['success'] == (dc == 1)


@pytest.mark.parametrize('kind,expected', [('custom', 10), ('formation_anchor', 5)])
def test_only_classified_structures_and_explicit_anchors_resist(tmp_path, kind, expected):
    from combat.object_rules import has_tag
    c, t, m = worker1_fight(tmp_path, [PRACTICE, CALAMITY], cause=SMASH,
                            cause_target='OBJECT', arena_edit=crate_arena((3, 5), kind))
    assert not has_tag(reload(c, m).state.objects[CRATE_ID], 'structure')
    assert burn_the_crate(c, t, m, aura=True) == expected


@pytest.mark.parametrize('pusher,target,expected_saves', [
    (ALLY, RIGHT, 1), (RIGHT, ALLY, 2),
])
@pytest.mark.parametrize('reverse_ids', [False, True])
def test_overlapping_friendly_and_hostile_auras(tmp_path, pusher, target, expected_saves, reverse_ids):
    """Every hostile aura answers; a friendly aura cannot hide it by sorting first."""
    import tests.hunt15_support as support
    # Patch fixture ids only, before any fight exists; never patch engine/core behavior.
    from unittest.mock import patch
    # Sorted ids normally put ALLY first and RIGHT last. Reverse the entire
    # holder order so the hostile aura is first in the second friendly-shove case.
    ids = {LEFT: LEFT, RIGHT: ALLY, ALLY: RIGHT} if reverse_ids else {LEFT: LEFT, RIGHT: RIGHT, ALLY: ALLY}
    with patch.multiple(support, LEFT=ids[LEFT], RIGHT=ids[RIGHT], ALLY=ids[ALLY]):
        c, t, m = support.fight(tmp_path, left=[PRACTICE, CALAMITY],
                                right=[PRACTICE, CALAMITY], ally=[PRACTICE, CALAMITY],
                                effects=PUSH, target='HOSTILE_ENTITY')
    for actor in (ids[LEFT], ids[RIGHT], ids[ALLY]):
        turn(t, m, actor)
        settle(lambda answers: act(t, m, LABEL, answers))
    # The last Guardian spent its Action planting the stance. Start a fresh turn
    # before asking it to shove, rather than testing an unavailable menu action.
    turn(t, m, ids[LEFT])
    turn(t, m, ids[pusher])
    home = position(t, m, ids[target])
    start = len(reload(c, m).events)
    settle(lambda answers: act(t, m, TEST_ACTION, answers, target_id=ids[target]))
    saves = [event for event in reload(c, m).events[start:]
             if event.event_type == 'SAVE_ROLLED' and event.source_definition_id == CALAMITY]
    assert len(saves) == expected_saves
    assert all(event.actor_id == ids[pusher] for event in saves)
    assert steps_moved(t, m, ids[target], home) == (1 if all(e.payload['success'] for e in saves) else 0)


def ally_takes_the_hit(t, m):
    """ALLY acts with the printed self-hit; returns the HP it lost and the save mode it rolled."""
    before_hp = hp(t, m, ALLY)
    before = len(reload(t.combat, m).events)
    settle(lambda a: act(t, m, TEST_ACTION, a))
    events = reload(t.combat, m).events[before:]
    modes = [e.payload.get('mode') for e in events
             if e.event_type == 'SAVE_ROLLED' and e.actor_id == ALLY]
    return {'lost': before_hp - hp(t, m, ALLY), 'mode': modes[-1] if modes else None}
