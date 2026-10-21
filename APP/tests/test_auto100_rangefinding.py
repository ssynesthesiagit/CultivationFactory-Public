"""Rangefinding Breath measures the target and sets up an Aimed Line at the table.

Printed rule (rules_text.json TAL_SNIPER_RANGEFINDING_BREATH): "As a Bonus Action, choose one creature
or object you can perceive within your weapon's long range. Until the end of your next turn, you know
whether the target is within normal range, long range, or beyond the weapon's range. If the target
remains within range and does not gain Total Cover, your next ranged attack against it gains an Aimed
Line. If you also hold Martial Focus, you learn whether the target benefits from Half Cover,
Three-Quarters Cover, or Total Cover against your current position."

Every range here is the chosen weapon's own compiled normal/long range in feet (the Dan Gong pellet bow
is 30/120, the Gong Jian bow 150/600), and the engine measures distance in feet, so a boundary is a cell
count times five. The tests below pin those boundaries, the printed window "until the end of your next
turn", the promise's range/cover conditions and the "next *ranged* attack against it" clause.
"""
import json

import pytest

from combat.factory_compiler import TYPED_AUTHORITY
from tests.auto_worker1_support import (LEFT, OTHER, RIGHT, act, action_sender, fight, reload, resolve,
                                        triple_fight, turn)

BREATH = 'TAL_SNIPER_RANGEFINDING_BREATH'
TRAIN = 'TAL_SNIPER_SNIPER_TRAINING'
AIMED = 'condition:typed.aimed_line'
MEASURED = 'condition:typed.rangefinding_breath'
FOCUS = 'resource:core.martial_focus'
CHOICE = 'choice:needle.rangefinding_breath'
WEAPON = 'choice:needle.rangefinding_weapon'
BOW = {'items': [{'item_id': 'tianxia.mortal.weapon.gong_jian',
                  'name': 'Gong Jian (Bow and Arrow)', 'quantity': 1}]}
SLING = {'items': [{'item_id': 'tianxia.mortal.weapon.dan_gong',
                    'name': 'Dan Gong (Pellet Bow / Sling Bow)', 'quantity': 1}]}
BOW_ATTACK = 'Gong Jian (Bow and Arrow) attack'
SLING_ATTACK = 'Dan Gong (Pellet Bow / Sling Bow) attack'


def held(e, kind, who=LEFT):
    return [c for c in e.state.actors[who].conditions.values() if c.condition_id == kind]


def aimed(e, who=LEFT):
    """The printed conditional shot: 'your next ranged attack against it counts as an Aimed Line'."""
    return held(e, AIMED, who)


def knows(e, who=LEFT):
    """The printed knowledge: 'until the end of your next turn, you know ...', which outlives the shot."""
    return held(e, MEASURED, who)


def blind(actor):
    return [c for c in actor.conditions.values() if c.condition_id.endswith('blinded')]


def labels(t, m):
    return [g['label'] for g in t.state(m)['menu']['actions']]


def said(e):
    return ' '.join(str(v.payload.get('text') or v.payload.get('log') or '') for v in e.events
                    if v.event_type == 'PASSIVE_TRIGGERED')


def start(tmp_path, talents=(BREATH,), *, distance=3, bundle_edit=None, kit=BOW, right_score=2,
          positions=None, cause=(), prepare=()):
    """A fight on the pillar arena whose two fighters share row 5 (no pillar between them)."""
    return fight(tmp_path, [TRAIN, *talents], left_kit=kit, left_score=30, right_score=right_score,
                  positions=positions or {LEFT: {"x": 3, "y": 5}, RIGHT: {"x": 3 + distance, "y": 5}},
                  bundle_edit=bundle_edit, cause=cause, prepare=prepare, prepare_target='SELF')


def breathe(t, m, target=RIGHT, *, weapon=None):
    return resolve(lambda a: act(t, m, 'Rangefinding Breath', a),
                   {CHOICE: [target], **({WEAPON: weapon} if weapon else {})})


def weapon_ids(c, m):
    """The catalogue ids of the ranged weapons the shooter holds, for a scripted weapon choice."""
    from combat.ext import sniper_rangefinding

    session = c._load_session(m)
    return list(sniper_rangefinding.ranged_weapons(session.engine, session.engine.state.actors[LEFT]))


def quick(actor_id, feet):
    """A bundle edit that gives one fighter a plain walking Speed, for a move a test needs."""
    def edit(bundle):
        if bundle['actor_template']['entity_id'] == actor_id:
            bundle['actor_template']['speed_ft'] = feet
    return edit


def edits(*fns):
    """Several bundle edits at once, so a test can pin a Speed and an Armor Class in one call."""
    def edit(bundle):
        for fn in fns:
            fn(bundle)
    return edit


def unmissable(actor_id, armor_class=40):
    """A bundle edit that gives one fighter an Armor Class no printed attack in these tests can beat."""
    def edit(bundle):
        if bundle['actor_template']['entity_id'] == actor_id:
            bundle['actor_template']['armor_class'] = armor_class
    return edit


def move_to(t, m, cell, answers=()):
    menu = t.state(m)['menu']
    cid = next(o['candidate_id'] for o in menu['moves'] if o.get('destination') == cell)
    return t.act(m, cid, menu['decision_id'], menu['state_version'], t.state(m)['last_sequence'], list(answers))


def measure(tmp_path, *, kit, distance):
    """Breathe once and return the words the table said plus the record that carries the printed answer."""
    c, t, m = start(tmp_path, kit=kit, distance=distance)
    breathe(t, m)
    e = reload(c, m)
    assert len(aimed(e)) == 1, "the printed shot is set up beside the knowledge it was measured for"
    return said(e), knows(e)


# --------------------------------------------------------------------------- the button and the choice
def test_bonus_action_button_exists_only_for_the_owner(tmp_path):
    for n, talents in enumerate(([TRAIN], [TRAIN, BREATH])):
        c, t, m = start(tmp_path / str(n), talents)
        assert ('Rangefinding Breath' in labels(t, m)) is (n == 1)


def test_choosing_a_target_sets_exactly_one_aimed_line_naming_it(tmp_path):
    c, t, m = start(tmp_path)
    breathe(t, m)
    e = reload(c, m)
    held = aimed(e)
    assert len(held) == 1
    assert held[0].data['target'] == RIGHT
    assert RIGHT in held[0].data['label'] or 'Visitor' in held[0].data['label']


def test_martial_focus_reports_the_cover(tmp_path):
    c, t, m = start(tmp_path)
    breathe(t, m)
    assert 'cover against you' in said(reload(c, m))


def test_a_character_without_the_talent_is_unaffected(tmp_path):
    def strip(bundle):
        bundle['typed_passives'] = [r for r in bundle.get('typed_passives', [])
                                    if r.get('block') != 'sniper_rangefinding']
        bundle['action_catalog'] = [a for a in bundle['action_catalog']
                                    if 'Rangefinding Breath' not in a['display_name']]
        ids = {a['source_definition_id'] for a in bundle['action_catalog']}
        bundle['actor_template']['action_ids'] = [i for i in bundle['actor_template']['action_ids'] if i in ids]
    c, t, m = start(tmp_path, bundle_edit=strip)
    assert 'Rangefinding Breath' not in labels(t, m)
    assert aimed(reload(c, m)) == []


# --------------------------------------------------------------------------- finding 2: the weapon's own ranges, in feet
@pytest.mark.parametrize('name,kit,distance,expected', [
    # The pellet bow's printed range is 30/120 and the bow's is 150/600: the same 35 feet is one weapon's
    # long range and the other's normal range, which a fixed half-of-long-range guess cannot produce.
    ('sling-normal', SLING, 6, 'within normal range'),
    ('sling-long', SLING, 7, 'at long range'),
    ('bow-normal', BOW, 7, 'within normal range'),
])
def test_the_band_is_read_from_the_weapons_own_two_ranges(tmp_path, name, kit, distance, expected):
    words, held = measure(tmp_path, kit=kit, distance=distance)
    assert expected in words, words
    assert held and held[0].data['band'] == ('normal' if expected.startswith('within') else 'long'), held


def test_the_bands_stop_exactly_at_the_weapons_own_printed_boundaries(tmp_path):
    """30 feet is the pellet bow's normal range (offered, 'within'), 35 feet is past it ('long')."""
    assert 'within normal range' in measure(tmp_path / 'six', kit=SLING, distance=6)[0]
    assert 'at long range' in measure(tmp_path / 'seven', kit=SLING, distance=7)[0]


def test_a_creature_beyond_the_measured_weapons_long_range_is_not_offered(tmp_path):
    """The grabbed improvised weapon is printed Thrown 20/60, so 80 feet is out of its reach entirely."""
    c, t, m = start(tmp_path, kit=BOW, positions={LEFT: {"x": 2, "y": 5}, RIGHT: {"x": 18, "y": 5}})
    act(t, m, 'Grab an improvised weapon')
    breathe(t, m, weapon=[k for k in weapon_ids(c, m) if 'improvised' in k])
    e = reload(c, m)
    assert aimed(e) == [], "nothing may be set up on a creature the weapon cannot reach"
    assert "long range of 60 feet" in said(e) and "No creature you can perceive" in said(e), said(e)


def test_both_ranged_weapons_in_hand_are_offered_with_their_own_ranges(tmp_path):
    c, t, m = start(tmp_path, kit=BOW, positions={LEFT: {"x": 2, "y": 5}, RIGHT: {"x": 14, "y": 5}})
    act(t, m, 'Grab an improvised weapon')
    _, prompts = resolve(lambda a: act(t, m, 'Rangefinding Breath', a), {CHOICE: [RIGHT]})
    ask = next(p for p in prompts if p['context']['reaction_source_id'] == WEAPON)
    labels_on_prompt = [o['label'] for o in ask['choice']['options']]
    assert any('normal range 150 ft, long range 600 ft' in label for label in labels_on_prompt), labels_on_prompt
    assert any('normal range 20 ft, long range 60 ft' in label for label in labels_on_prompt), labels_on_prompt
    held = aimed(reload(c, m))
    assert held and held[0].data['normal_ft'] == 150 and held[0].data['long_ft'] == 600, held


# --------------------------------------------------------------------------- finding 1: until the end of your NEXT turn
def test_the_line_survives_the_casting_turn_and_ends_at_the_end_of_the_next_one(tmp_path):
    c, t, m = start(tmp_path)
    breathe(t, m)
    held = aimed(reload(c, m))
    assert len(held) == 1
    assert held[0].expires_on == 'END_OF_SOURCE_TURN_AT:2', held[0].expires_on  # the shooter's counter is 1
    turn(t, m, RIGHT)
    assert len(aimed(reload(c, m))) == 1, "'until the end of your next turn' cannot end on the casting turn"
    turn(t, m, LEFT)
    assert len(aimed(reload(c, m))) == 1, "the next turn is when the shooter uses it"
    assert act(t, m, 'end')['status'] == 'COMMITTED'
    assert aimed(reload(c, m)) == [], "an expiry nothing removes would last the rest of the fight"


def test_a_later_round_cast_ends_the_same_way(tmp_path):
    """The window is counted from the shooter's own turn counter, not a fixed first turn."""
    c, t, m = start(tmp_path)
    for _ in range(4):
        turn(t, m, RIGHT if t.state(m)['menu']['actor_id'] == LEFT else LEFT)
    assert t.state(m)['menu']['actor_id'] == LEFT
    started = reload(c, m).state.actors[LEFT].turns_started
    breathe(t, m)
    held = aimed(reload(c, m))
    assert held and held[0].expires_on == f'END_OF_SOURCE_TURN_AT:{started + 1}', (started, held)
    turn(t, m, RIGHT)
    assert len(aimed(reload(c, m))) == 1, "'until the end of your next turn' again, a round later"
    turn(t, m, LEFT)
    assert len(aimed(reload(c, m))) == 1
    assert act(t, m, 'end')['status'] == 'COMMITTED'
    assert aimed(reload(c, m)) == []


# --------------------------------------------------------------------------- finding 3: only a ranged attack on that creature spends it
def test_a_melee_attack_keeps_the_aimed_line(tmp_path):
    """Punching the marked creature must not spend a setup printed for the next RANGED attack."""
    c, t, m = start(tmp_path, distance=1)
    breathe(t, m)
    assert 'Unarmed Strike' in labels(t, m)
    act(t, m, 'Unarmed Strike', target_id=RIGHT)
    assert len(aimed(reload(c, m))) == 1, "the printed line is for the next RANGED attack, not a punch"
    turn(t, m, RIGHT)
    turn(t, m, LEFT)
    assert len(aimed(reload(c, m))) == 1
    act(t, m, BOW_ATTACK, target_id=RIGHT)
    assert aimed(reload(c, m)) == []


def test_a_shot_at_another_creature_keeps_the_aimed_line(tmp_path):
    c, t, m = triple_fight(tmp_path, [TRAIN, BREATH], left_kit=BOW, left_score=30)
    breathe(t, m)
    assert len(aimed(reload(c, m))) == 1
    act(t, m, BOW_ATTACK, target_id=OTHER)
    assert len(aimed(reload(c, m))) == 1, "the line is aimed at one creature"
    turn(t, m, RIGHT)
    turn(t, m, LEFT)
    assert len(aimed(reload(c, m))) == 1
    act(t, m, BOW_ATTACK, target_id=RIGHT)
    assert aimed(reload(c, m)) == []


def test_a_miss_still_spends_the_aimed_line(tmp_path):
    c, t, m = start(tmp_path, kit=SLING, distance=4, bundle_edit=unmissable(RIGHT))
    breathe(t, m)
    act(t, m, SLING_ATTACK, target_id=RIGHT)
    e = reload(c, m)
    roll = next(r for r in e.rolls if r.actor_id == LEFT and r.reason.startswith('ATTACK:'))
    assert roll.total < 40, roll.total
    assert aimed(e) == [], "'your next ranged attack against it' is spent whether the roll hits or misses"


def test_the_shot_still_rolls_one_die_and_keeps_the_aimed_line_until_it_is_spent(tmp_path):
    """The printed line grants an Aimed Line, not Advantage: the roll must not become a best-of-two."""
    c, t, m = start(tmp_path)
    breathe(t, m)
    assert len(aimed(reload(c, m))) == 1
    act(t, m, BOW_ATTACK, target_id=RIGHT)
    e = reload(c, m)
    roll = next(v for v in e.rolls if v.actor_id == LEFT and v.reason.startswith('ATTACK:'))
    assert roll.expression.startswith('1d20'), roll.expression
    assert not aimed(e), "the printed 'next ranged attack against it' spends the line"


# --------------------------------------------------------------------------- finding 4: the promise's range and cover clauses
def test_a_target_that_leaves_the_measured_range_loses_the_setup(tmp_path):
    """The grabbed improvised weapon reaches 60 feet; 80 feet is past it, so the printed benefit lapses."""
    c, t, m = start(tmp_path, positions={LEFT: {"x": 2, "y": 5}, RIGHT: {"x": 14, "y": 5}}, right_score=30)
    act(t, m, 'Grab an improvised weapon')
    breathe(t, m, weapon=[k for k in weapon_ids(c, m) if 'improvised' in k])
    e = reload(c, m)
    assert len(aimed(e)) == 1 and aimed(e)[0].data['long_ft'] == 60, aimed(e)
    turn(t, m, RIGHT)
    resolve(lambda answers: move_to(t, m, {"x": 18, "y": 5}, answers))
    e = reload(c, m)
    assert aimed(e) == [], "a target outside the weapon's range keeps no Aimed Line"
    assert "beyond your weapon's range" in said(e) and "the Aimed Line on Visitor is lost" in said(e), said(e)


def test_a_target_that_gains_total_cover_loses_the_setup(tmp_path):
    """Pillar five of the arena sits between (8,6) and (11,6): the printed 'does not gain Total Cover' fails."""
    c, t, m = start(tmp_path, positions={LEFT: {"x": 8, "y": 6}, RIGHT: {"x": 6, "y": 6}},
                    right_score=30, bundle_edit=quick(RIGHT, 80))
    breathe(t, m)
    assert len(aimed(reload(c, m))) == 1
    turn(t, m, RIGHT)
    resolve(lambda answers: move_to(t, m, {"x": 11, "y": 6}, answers))
    e = reload(c, m)
    assert e._effect_distance(e.state.actors[LEFT], e.state.actors[RIGHT]) == 15
    assert aimed(e) == [], "a target that gained Total Cover keeps no Aimed Line"
    assert "gained Total Cover from a wall or solid barrier" in said(e), said(e)
    assert len(knows(e)) == 1 and knows(e)[0].data['total_cover'] == 1
    assert 'with Total Cover against you' in said(e)
    resolve(lambda answers: move_to(t, m, {"x": 8, "y": 5}, answers))
    e = reload(c, m)
    assert aimed(e) == [], "returning from cover cannot restore a lost Aimed Line"
    assert len(knows(e)) == 1 and knows(e)[0].data['total_cover'] == 0
    assert 'now Visitor is within normal range, with no cover against you' in said(e)


def test_the_promised_range_is_refreshed_when_the_shooter_moves(tmp_path):
    """'Until the end of your next turn, you know': a band that moved is said again, once."""
    c, t, m = start(tmp_path, kit=SLING, distance=7)
    breathe(t, m)
    assert 'at long range' in said(reload(c, m))
    assert move_to(t, m, {"x": 5, "y": 5})['status'] == 'COMMITTED'
    e = reload(c, m)  # the reloaded fight keeps the refreshed band, so the promise survives a commit
    held = knows(e)
    assert held and held[0].data['band'] == 'normal', held
    assert 'now Visitor is within normal range' in said(e), said(e)
    assert act(t, m, 'end')['status'] == 'COMMITTED'
    assert len(aimed(reload(c, m))) == 1, "the refreshed knowledge must not re-spend the line"
    assert len(knows(reload(c, m))) == 1, "and both records run to the same printed expiry"


# ------------------------------- review 1: the promised knowledge outlives the shot
def test_the_promised_knowledge_outlives_a_shot_that_was_lost_and_is_kept_up_to_date(tmp_path):
    """'Beyond the weapon's range' is one of the three bands the printed knowledge reports, so a target that
    leaves the measured range only loses the Aimed Line: the knowledge goes on being measured, through the
    target's next movement and across a commit, until the printed expiry."""
    c, t, m = start(tmp_path, positions={LEFT: {"x": 2, "y": 5}, RIGHT: {"x": 12, "y": 5}},
                    right_score=30, bundle_edit=quick(RIGHT, 60))
    act(t, m, 'Grab an improvised weapon')                       # Thrown 20/60
    breathe(t, m, weapon=[k for k in weapon_ids(c, m) if 'improvised' in k])
    e = reload(c, m)
    assert len(aimed(e)) == 1 and knows(e)[0].data['long_ft'] == 60
    assert knows(e)[0].data['band'] == 'long', "50 ft is past its normal 20 and inside its 60"
    turn(t, m, RIGHT)
    resolve(lambda answers: move_to(t, m, {"x": 16, "y": 5}, answers))   # 70 ft: past the weapon's long range
    e = reload(c, m)
    assert aimed(e) == [], "the printed shot needs the target within that weapon's range"
    assert 'the Aimed Line on Visitor is lost, because it is beyond your weapon' in said(e), said(e)
    assert 'You keep knowing how far away it is' in said(e), said(e)
    measured = knows(e)
    assert len(measured) == 1 and measured[0].data['band'] == 'beyond', measured

    resolve(lambda answers: move_to(t, m, {"x": 10, "y": 5}, answers))   # a second movement, 40 ft: back in range
    e = reload(c, m)
    measured = knows(e)
    assert len(measured) == 1 and measured[0].data['band'] == 'long', measured
    assert 'now Visitor is at long range' in said(e), said(e)
    turn(t, m, LEFT)
    assert len(knows(reload(c, m))) == 1
    assert act(t, m, 'end')['status'] == 'COMMITTED'
    assert knows(reload(c, m)) == [], "'until the end of your next turn' still ends it"


def test_the_promised_knowledge_outlives_the_shot_that_spends_the_aimed_line(tmp_path):
    """The printed rule is two sentences: the knowledge runs to the end of your next turn whether or not the
    Aimed Line is still there, and the shot spends only the Aimed Line."""
    c, t, m = start(tmp_path, kit=SLING, distance=4, right_score=30,
                    bundle_edit=edits(quick(RIGHT, 60), unmissable(RIGHT)))
    breathe(t, m)                                                  # 20 ft: within the pellet bow's normal 30
    act(t, m, SLING_ATTACK, target_id=RIGHT)                       # a miss still spends the Aimed Line
    e = reload(c, m)
    assert aimed(e) == [], "'your next ranged attack against it' spends the Aimed Line"
    assert len(knows(e)) == 1, "it does not spend the knowledge the same sentence promised"
    turn(t, m, RIGHT)
    resolve(lambda answers: move_to(t, m, {"x": 16, "y": 5}, answers))   # 65 ft: at long range, still in reach
    e = reload(c, m)
    measured = knows(e)
    assert len(measured) == 1 and measured[0].data['band'] == 'long', measured
    assert 'now Visitor is at long range' in said(e), said(e)
    assert 'You keep knowing how far away it is' in said(e), said(e)


def test_a_legacy_combined_record_keeps_its_knowledge_and_original_expiry(tmp_path):
    """Supplemental unit coverage for the pre-fix shape; table regressions cover real commits above."""
    from combat.ext.condition_ownership import remove_instance
    from combat.ext.sniper_rangefinding import _recheck

    c, t, m = start(tmp_path, kit=SLING, distance=4, bundle_edit=unmissable(RIGHT))
    breathe(t, m)
    session = c._load_session(m)
    e = session.engine
    shooter = e.state.actors[LEFT]
    measurement = knows(e)[0]
    line = aimed(e)[0]
    line.data = {**line.data, 'band': measurement.data['band'], 'cover': measurement.data['cover']}
    key = next(k for k, v in shooter.conditions.items() if v is measurement)
    remove_instance(e, shooter, key, BREATH)
    assert knows(e) == [] and aimed(e)[0].data['band'] == 'normal'
    _recheck(e, shooter)
    key = next(k for k, v in shooter.conditions.items() if v is line)
    remove_instance(e, shooter, key, BREATH)
    _recheck(e, shooter)
    assert aimed(e) == [] and len(knows(e)) == 1
    assert knows(e)[0].expires_on == line.expires_on


# ------------------------------- review 2: perception chooses the target; it does not cancel the setup
def test_temporary_blindness_after_a_valid_selection_keeps_the_setup_and_recovers(tmp_path):
    """'Choose one creature you can perceive' is the printed condition of choosing. The printed ongoing conditions
    are range and Total Cover only, so a temporary blinding does not destroy a setup the shooter may not abandon:
    it survives the shooter's next turn start and the commit, the expiry still ends it, and the talent works
    normally again once sight returns."""
    c, t, m = start(tmp_path, cause=[{"type": "condition", "condition": "blinded"}],
                    prepare=[{"type": "remove_condition", "condition": "blinded", "applies_to": "self"}])
    breathe(t, m)
    e = reload(c, m)
    assert len(aimed(e)) == 1 and len(knows(e)) == 1
    turn(t, m, RIGHT)
    act(t, m, 'Cause', target_id=LEFT)       # the Visitor blinds the shooter until the end of the shooter's next turn
    assert blind(reload(c, m).state.actors[LEFT]), "the shooter is blind for this regression to mean anything"
    turn(t, m, LEFT)
    e = reload(c, m)
    assert len(aimed(e)) == 1, "in range and uncovered: the printed shot still stands while the shooter is blind"
    assert len(knows(e)) == 1 and knows(e)[0].data['band'] == 'normal', knows(e)

    breathe(t, m)                            # choosing again is a new choice, and it still needs perception
    e = reload(c, m)
    assert 'No creature you can perceive is within' in said(e), said(e)
    assert len(aimed(e)) == 1 and len(knows(e)) == 1, "and a refused new choice does not disturb the standing one"

    act(t, m, 'Prepare')
    e = reload(c, m)
    assert not blind(e.state.actors[LEFT])
    assert len(aimed(e)) == 1 and len(knows(e)) == 1, "sight returns within the original knowledge window"
    act(t, m, BOW_ATTACK, target_id=RIGHT)
    e = reload(c, m)
    assert aimed(e) == [] and len(knows(e)) == 1
    assert 'your shot at Visitor counts as an Aimed Line' in said(e)
    assert act(t, m, 'end')['status'] == 'COMMITTED'
    e = reload(c, m)
    assert aimed(e) == [] and knows(e) == [], "'until the end of your next turn' ends both records as printed"
    assert not blind(e.state.actors[LEFT])
    turn(t, m, RIGHT)
    turn(t, m, LEFT)
    breathe(t, m)
    e = reload(c, m)
    assert len(aimed(e)) == 1 and len(knows(e)) == 1, "and the talent is not broken once the sight returns"


# --------------------------------------------------------------------------- checklist 9 and 13: who decides, and what they read
def test_an_ai_shooter_takes_the_choices_itself(tmp_path):
    c, t, m = start(tmp_path, distance=4)
    send = action_sender(c, t, m, 'Rangefinding Breath', ai=True)
    _, prompts = resolve(send)
    assert prompts == [], "an AI fighter decides its own target; it is never asked"
    assert len(aimed(reload(c, m))) == 1


def test_the_words_a_player_reads_explain_what_an_aimed_line_does(tmp_path):
    c, t, m = start(tmp_path)
    group = next(g for g in t.state(m)['menu']['actions'] if g['label'] == 'Rangefinding Breath')
    text = group.get('description') or ''
    for fragment in ('Bonus Action', 'no cultivation points', 'next turn', 'Total Cover', 'range'):
        assert fragment in text, (fragment, text)
    breathe(t, m)
    words = said(reload(c, m))
    for fragment in ('Visitor', 'Aimed Line', 'until the end of your next turn'):
        assert fragment in words, (fragment, words)
    for jargon in ('condition:', 'typed.', 'aimed_line', '.py', 'ranged_attacks'):
        assert jargon not in text and jargon not in words, (jargon, text, words)


# --------------------------------------------------------------------------- finding 5: honest coverage
def test_no_gm_reminder_text_survives_the_measured_clauses(tmp_path):
    c, t, m = start(tmp_path)
    breathe(t, m)
    e = reload(c, m)
    stale = [v for v in e.events if v.event_type == 'GM_RIDER'
             and 'RANGEFINDING' in str(v.source_definition_id).upper()]
    assert not stale, [v.payload for v in stale]


def test_the_chapter_still_admits_what_the_table_cannot_run(tmp_path):
    """The object choice and the Aimed Line consumers are GM calls, so the coverage is not FULL."""
    mechanics = json.loads(TYPED_AUTHORITY.read_bytes())['mechanics'][BREATH]
    assert mechanics['coverage'] == 'CORE_WITH_RIDERS', mechanics['coverage']
    joined = ' '.join(mechanics['riders'])
    assert 'object' in joined, joined
    assert 'Aimed Line' in joined, joined
    for jargon in ('condition:', 'typed.', '.py', 'combat/', 'plug-in'):
        assert jargon not in joined, (jargon, joined)
