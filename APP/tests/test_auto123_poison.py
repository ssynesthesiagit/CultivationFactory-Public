"""AUTO123 (review fixes) -- Poison: Coated Weapon, Venom in the Wound, and the two save-success Temporary HP riders.

Every test drives the real table service (combat/ext/auto_worker1_support.fight -> TabletopService.act) and re-reads the
state through tests.hunt15_support.reload, which reloads the fight from disk, asserts the two loaded states agree and
asserts a PASS replay -- so a pass means the printed clause happens on the same path a player's fight uses and the fight
still reloads byte-for-byte from its recorded events.

Nothing here reads a plug-in helper to decide an outcome: each case sets up the situation, performs a service action and
asserts on the committed, reloaded fight. The levers that make a save deterministic are derived from the fixture and
documented below rather than from a seed.

A caution that several cases here depend on: a SELF-targeting setup action supplies *no* target, so an effect that says
``applies_to: 'target'`` on it silently does nothing (combat/typed_executor.resolve_typed: "SELF supplies an implicit
actor fallback"). The cases that act on the caster itself therefore say ``applies_to: 'self'``, and every case that must
commit damage checks the committed damage rather than assuming its effect packet ran.
"""
import pytest

from combat.ext import poison
from combat.ext.stacking_marks import count
from tests.auto_worker1_support import LEFT, RIGHT, fight, act, reload, action_sender
from tests.auto_worker1_stars_support import resolve, turn

P = 'tianxia.talent.poison.'
COATED = P + 'coated_weapon'
WOUND = P + 'venom_in_the_wound'
BODY = P + 'venom_body_method'
THOUSAND = P + 'thousand_poison_immunity'
DELIVER = poison.DELIVER
POOL = 'resource:core.qi'
COATING = 'condition:typed.poison_coating'
DAGGER = 'action:typed.945a1f5770.weapon.bi_shou'
THOUSAND_CHOICE = 'choice:needle.poison_thousand_temp_hp'
RIDE_CHOICE = 'choice:needle.poison_venom_in_the_wound'
# A hit must not be a coin flip: an armourless target with the lowest Dexterity cannot miss a +100 attack.
SOFT = {'items': [{'item_id': 'tianxia.mortal.weapon.bi_shou', 'name': 'Bi Shou (Dagger)', 'quantity': 1}]}

# Deterministic save levers, read off the fixture rather than a seed. The coated attack's Constitution save uses the
# ATTACKING action's save DC, which the compiler builds as 10 + that character's Proficiency Bonus, and the target's save
# modifier is (score - 10) // 2:
#   left_pb=2 with right_score=34 -> DC 12 against +12, so the target cannot fail (lowest total 13).
#   left_pb=6 with right_score=1  -> DC 16 against -5, so the target cannot succeed (highest total 15).
CANNOT_FAIL = dict(left_pb=2, right_score=34)
CANNOT_PASS = dict(left_pb=6, right_score=1)
# LEFT's own test action takes its save DC from left_save_dc, so -100 makes LEFT's own saves certain successes.
LEFT_SAVES = dict(left_save_dc=-100)
# Both sides so low-initiative that RIGHT is the first actor in the order; the fixture's turn() helper has already passed
# RIGHT's opening turn, so the fight starts on LEFT's turn in round 1.
RIGHT_FIRST = dict(left_score=1, right_score=30)

POISON_HIT = [{'type': 'damage', 'flat': 5, 'damage_types': ['poison'], 'applies_to': 'target'},
              {'type': 'save', 'ability': 'con',
               'on_fail': [{'type': 'condition', 'condition': 'poisoned', 'applies_to': 'target',
                            'expires_on': 'START_OF_TARGET_NEXT_TURN'}],
               'on_success': []}]
# The fixture's creatures have 1000 maximum Hit Points, so this both wounds the target ("below half Hit Points") and is
# the committed damage the printed Venom in the Wound clause needs.
WOUNDING_POISON = [{'type': 'save', 'ability': 'con',
                    'on_fail': [{'type': 'damage', 'flat': 600, 'damage_types': ['poison'], 'applies_to': 'target'}],
                    'on_success': [{'type': 'damage', 'flat': 600, 'damage_types': ['poison'], 'applies_to': 'target'}]}]
# The same Toxin Effect with no damage packet at all, so a Temporary HP limit is measured on its own: nothing else can
# change the stored Temporary HP between the first save and the second.
POISON_SAVE_ONLY = POISON_HIT[1:]
# ...and the same save aimed at the caster. A SELF-targeting action supplies no target for an "applies_to: target" effect
# (combat/typed_executor.resolve_typed), so an owner poisoning itself has to say "applies_to: self".
POISON_SAVE_SELF = [{'type': 'save', 'ability': 'con', 'applies_to': 'self',
                     'on_fail': [{'type': 'condition', 'condition': 'poisoned', 'applies_to': 'self',
                                  'expires_on': 'START_OF_TARGET_NEXT_TURN'}],
                     'on_success': []}]
WOUNDED_NO_DAMAGE = [{'type': 'condition', 'condition': 'bleeding', 'applies_to': 'target',
                      'expires_on': 'START_OF_TARGET_NEXT_TURN'},
                     {'type': 'damage', 'flat': 0, 'damage_types': ['poison'], 'applies_to': 'target'}]
# A real attack roll that hits, against a target who is bleeding and immune to Poison damage: the blow lands and commits
# nothing. This is the case the old after_hit rider could not tell apart from a wounding hit.
ZERO_DAMAGE_HIT = [{'type': 'immunity', 'damage_types': ['poison'], 'applies_to': 'target',
                    'expires_on': 'START_OF_TARGET_NEXT_TURN'},
                   {'type': 'condition', 'condition': 'bleeding', 'applies_to': 'target',
                    'expires_on': 'START_OF_TARGET_NEXT_TURN'},
                   {'type': 'attack', 'attack_kind': 'cultivation_ranged', 'count': 1,
                    'on_hit': [{'type': 'damage', 'flat': 6, 'damage_types': ['poison'], 'applies_to': 'target'}],
                    'on_miss': []}]


def _coat(actor):
    return next((row for row in actor.conditions.values() if row.condition_id == COATING), None)


def _temp_hp(actor):
    return int(actor.temporary_hp or 0)


def _events(engine, kind, actor_id=None):
    return [ev for ev in engine.events if ev.event_type == kind
            and (actor_id is None or ev.actor_id == actor_id)]


def _poison_damage(engine, target_id):
    """Damage this attack actually committed that is neither the weapon's own type nor a rider's -- the coated hit's
    printed bonus is the only Poison/Acid packet an ordinary dagger attack produces."""
    return [int(ev.payload.get('hp_damage') or 0) for ev in _events(engine, 'DAMAGE_COMMITTED')
            if target_id in (ev.target_ids or ())
            and str(ev.payload.get('damage_type') or '').upper() in ('POISON', 'ACID')]


def _coated_hit(c, t, m):
    """Coat the held dagger, then hit with it in the same turn."""
    resolve(action_sender(c, t, m, 'Coat a Weapon'), {'choice:needle.poison_coated_weapon': [DAGGER]})
    resolve(action_sender(c, t, m, 'Bi Shou (Dagger) attack', target_id=RIGHT))


# ------------------------------------------------------------------------------ Coated Weapon


def test_coating_compiles_as_a_bonus_action_that_costs_one_cp(tmp_path):
    """Printed: "Action Type: Bonus Action / Duration: 1 minute / Cost: 1 CP" -- not a free Action, and not an Attack."""
    c, t, m = fight(tmp_path, [COATED], cl=15)
    labels = [o['label'] for g in t.state(m)['menu']['actions'] for o in g['options']]
    assert 'Coat a Weapon' in labels
    e = reload(c, m)
    action = next(a for a in e.action_catalog.values() if a.display_name == 'Coat a Weapon')
    assert action.economy.value == 'BONUS_ACTION'
    assert ((POOL, 1),) == tuple(tuple(row) for row in action.costs)


def test_coating_is_tracked_with_the_printed_charges_and_ends_after_its_applications(tmp_path):
    """Printed: "The coating ends after 1 minute or after it has applied a Dose Mark a number of times equal to your
    Proficiency Bonus." The condition carries that charge count and a 1-minute (ten round) deadline."""
    c, t, m = fight(tmp_path, [COATED], cl=15, left_pb=4)
    resolve(action_sender(c, t, m, 'Coat a Weapon'), {'choice:needle.poison_coated_weapon': [DAGGER]})
    e = reload(c, m)
    me = e.state.actors[LEFT]
    coat = _coat(me)
    assert coat is not None, 'coating the weapon did nothing'
    assert int(coat.data['charges']) == 4, 'charges must be the Proficiency Bonus'
    assert coat.expires_on == 'END_OF_SOURCE_TURN_AT:%d' % (me.turns_started + 10), '1 minute is ten of the owner rounds'
    assert e.state.actors[LEFT].resources[POOL] == 99, 'the printed 1 CP is charged'


def test_a_coated_hit_deals_exactly_one_proficiency_bonus_of_extra_damage(tmp_path):
    """Printed: "it deals additional Poison or Acid damage equal to your Proficiency Bonus" -- once.

    A typed amount's `flat` and its `formula` are separate additive terms (combat/typed_amounts.dice_terms sums both into
    the roll modifier), so naming the Proficiency Bonus twice rolled 8 for a Proficiency Bonus of 4.
    """
    c, t, m = fight(tmp_path, [COATED], cl=15, left_pb=4, left_attack_bonus=100, right_kit=SOFT)
    _coated_hit(c, t, m)
    e = reload(c, m)
    rider = _poison_damage(e, RIGHT)
    assert rider, 'the coated attack dealt its printed bonus damage'
    assert sum(rider) == 4, f'the coating must add exactly the Proficiency Bonus (4), not two copies: {rider}'


def test_a_coated_hit_the_target_survives_spends_no_coating_charge(tmp_path):
    """A saved target applies no Dose Mark, so the printed charge is not spent by that hit."""
    c, t, m = fight(tmp_path, [COATED], cl=15, left_attack_bonus=100, right_kit=SOFT, **CANNOT_FAIL)
    _coated_hit(c, t, m)
    e = reload(c, m)
    me, target = e.state.actors[LEFT], e.state.actors[RIGHT]
    save = _events(e, 'SAVE_ROLLED', RIGHT)[-1]
    assert save.payload['success'], 'the target cannot fail this save'
    assert count(e, me, target, 'Dose Mark') == 0
    assert int(_coat(me).data['charges']) == 2, 'a successful save must not spend a coating charge'


def test_a_saved_target_that_already_carries_my_dose_mark_keeps_its_stack_and_my_charge(tmp_path):
    """The charge is spent by an *applied* Dose Mark, not by the mere presence of one.

    A native mark's condition id carries its owner (`condition:typed.mark.dose_mark.<owner>`), so a test for a bare
    `dose_mark` suffix could never see the mark this save just placed -- and would have spent a charge on any creature
    already marked, saved or not.
    """
    c, t, m = fight(tmp_path, [COATED], cl=15, left_attack_bonus=100, right_kit=SOFT,
                    prepare=[{'type': 'mark', 'mark': 'Dose Mark', 'applies_to': 'target'}], **CANNOT_FAIL)
    act(t, m, 'Prepare', target_id=RIGHT)          # the target starts already holding one of my Dose Marks
    e0 = reload(c, m)
    assert count(e0, e0.state.actors[LEFT], e0.state.actors[RIGHT], 'Dose Mark') == 1, 'precondition: one mark is placed'
    _coated_hit(c, t, m)
    e = reload(c, m)
    me, target = e.state.actors[LEFT], e.state.actors[RIGHT]
    assert _events(e, 'SAVE_ROLLED', RIGHT)[-1].payload['success']
    assert count(e, me, target, 'Dose Mark') == 1, 'a saved target adds no second Dose Mark'
    assert int(_coat(me).data['charges']) == 2, 'an already-marked creature must not cost a coating charge'


def test_the_coating_runs_out_after_proficiency_bonus_applied_dose_marks(tmp_path):
    """Printed: "the coating ends after ... it has applied a Dose Mark a number of times equal to your Proficiency
    Bonus." Two charges (Proficiency Bonus 2), two failed saves, then the venom is gone."""
    c, t, m = fight(tmp_path, [COATED], cl=15, left_attack_bonus=100, right_kit=SOFT, **CANNOT_PASS)
    resolve(action_sender(c, t, m, 'Coat a Weapon'), {'choice:needle.poison_coated_weapon': [DAGGER]})
    for spent in range(1, 7):
        if spent > 1:
            resolve(lambda answers: act(t, m, 'end', answers))   # LEFT's turn ends; the next one starts a new turn
            turn(t, m, LEFT)
        resolve(action_sender(c, t, m, 'Bi Shou (Dagger) attack', target_id=RIGHT))
        e = reload(c, m)
        me = e.state.actors[LEFT]
        assert not _events(e, 'SAVE_ROLLED', RIGHT)[-1].payload['success'], 'the target cannot make this save'
        assert count(e, me, e.state.actors[RIGHT], 'Dose Mark') == spent
        if spent < 6:
            assert _coat(me) is not None and int(_coat(me).data['charges']) == 6 - spent, \
                f'after {spent} applied Dose Marks the printed charges must be 6 - {spent}'
    assert _coat(reload(c, m).state.actors[LEFT]) is None, 'the last printed charge ends the coating'


def test_the_coating_pill_states_once_per_turn_its_lifetime_and_the_uses_left(tmp_path):
    """A player must be able to read the printed frequency and the remaining uses off the pill, and know what a Dose Mark
    does -- it is named there, so it has to say what it is."""
    c, t, m = fight(tmp_path, [COATED], cl=15, left_pb=4)
    resolve(action_sender(c, t, m, 'Coat a Weapon'), {'choice:needle.poison_coated_weapon': [DAGGER]})
    e = reload(c, m)
    label = str(_coat(e.state.actors[LEFT]).data['label'])
    assert 'Once per turn' in label, label
    assert 'each hit this turn' not in label, label
    assert '1 minute' in label, label
    assert '4' in label, label
    assert 'Dose Mark' in label and 'Toxin Burden' in label and 'long rest' in label, label


# ------------------------------------------------------------------------------ Venom in the Wound


@pytest.mark.parametrize('success', [True, False], ids=['save-success', 'save-failure'])
def test_venom_in_the_wound_rides_save_resolved_damage_and_not_only_attack_hits(tmp_path, success):
    """Printed: "When you damage a creature ...". The engine reports committed damage for a damage effect resolved by a
    save as well as for an attack, so a poison effect that is not an attack still offers the printed rider.

    WOUNDING_POISON commits its damage only inside the save's own branch, so nothing at all is dealt before the save:
    an earlier version of this fixture damaged the target before the save and would have passed on a packet the rider
    could never have reached."""
    c, t, m = fight(tmp_path, [WOUND], cl=15, prepare=WOUNDING_POISON,
                    left_save_dc=-100 if success else 100)
    _, prompts = resolve(action_sender(c, t, m, 'Prepare', target_id=RIGHT), {RIDE_CHOICE: ['RIDE']})
    assert any(RIDE_CHOICE in str(p.get('context')) for p in prompts), \
        'damage that was committed by a save must offer the printed ride, not only an attack hit'
    e = reload(c, m)
    me, target = e.state.actors[LEFT], e.state.actors[RIGHT]
    damages = [ev for ev in _events(e, 'DAMAGE_COMMITTED') if RIGHT in (ev.target_ids or ())]
    saves = _events(e, 'SAVE_ROLLED', RIGHT)
    assert saves[0].payload['success'] is success
    assert saves[0].sequence < damages[0].sequence, 'damage must resolve inside the save branch'
    assert damages and all(int(ev.payload.get('hp_damage') or 0) > 0 for ev in damages), \
        f'precondition: the save resolved real damage: {damages}'
    assert me.resources[POOL] == 98, 'the printed 2 CP is charged'
    assert count(e, me, target, 'Dose Mark') == (1 if success else 0)
    assert count(e, me, target, 'Toxin Burden') == (0 if success else 1)


def test_venom_in_the_wound_is_not_offered_when_no_damage_was_dealt(tmp_path):
    """"When you damage a creature" -- an effect that commits no damage at all is not damage."""
    c, t, m = fight(tmp_path, [WOUND], cl=15, prepare=WOUNDED_NO_DAMAGE)
    _, prompts = resolve(action_sender(c, t, m, 'Prepare', target_id=RIGHT))
    assert not any(RIDE_CHOICE in str(p.get('context')) for p in prompts), \
        'no damage committed means no printed ride to pay for'
    assert reload(c, m).state.actors[LEFT].resources[POOL] == 100, 'declining costs nothing'


@pytest.mark.parametrize('immune', [True, False])
def test_a_hit_reduced_to_zero_damage_is_not_offered_the_ride(tmp_path, immune):
    """The boundary the former after_hit rider could not see: a real attack that HITS a bleeding target and commits no
    damage at all, because that target is immune to the damage type.

    The paired ``immune=False`` case is the positive control -- the very same attack against a target with no immunity
    deals damage and does offer the ride -- so a pass on the first half cannot be a hit that simply missed."""
    effects = ZERO_DAMAGE_HIT if immune else [row for row in ZERO_DAMAGE_HIT if row['type'] != 'immunity']
    c, t, m = fight(tmp_path, [WOUND], cl=15, prepare=effects, prepare_attack_bonus=100,
                    left_attack_bonus=100, **LEFT_SAVES)
    _, prompts = resolve(action_sender(c, t, m, 'Prepare', target_id=RIGHT),
                         {} if immune else {RIDE_CHOICE: ['RIDE']})
    e = reload(c, m)
    strike = _events(e, 'ATTACK_ROLLED', LEFT)
    assert strike and strike[-1].payload['provisional_hit'], 'the attack really hit'
    if immune:
        damages = [ev for ev in _events(e, 'DAMAGE_COMMITTED') if RIGHT in (ev.target_ids or ())]
        assert damages and all(int(ev.payload.get('hp_damage') or 0) == 0
                               and int(ev.payload.get('temporary_hp_absorbed') or 0) == 0 for ev in damages), \
            f'precondition: the hit committed no damage: {damages}'
    assert any(RIDE_CHOICE in str(p.get('context')) for p in prompts) is (not immune), \
        'the ride follows committed damage, not the fact that an attack landed'
    assert e.state.actors[LEFT].resources[POOL] == (100 if immune else 98)


@pytest.mark.parametrize('take', [True, False])
def test_venom_in_the_wound_costs_two_cp_only_when_the_player_takes_the_ride(tmp_path, take):
    """Printed: "you may spend 2 CP" -- so declining is a real outcome and spends nothing."""
    c, t, m = fight(tmp_path, [WOUND], cl=15, prepare=WOUNDING_POISON, **LEFT_SAVES)
    resolve(action_sender(c, t, m, 'Prepare', target_id=RIGHT), {RIDE_CHOICE: ['RIDE'] if take else []})
    e = reload(c, m)
    me, target = e.state.actors[LEFT], e.state.actors[RIGHT]
    assert me.resources[POOL] == (98 if take else 100)
    assert count(e, me, target, 'Dose Mark') == (1 if take else 0)


def test_the_venom_in_the_wound_prompt_names_the_blow_the_creature_and_what_the_marks_do(tmp_path):
    """Checklist 13: the prompt says what happened, to whom, what it costs and what each outcome leaves behind."""
    c, t, m = fight(tmp_path, [WOUND], cl=15, prepare=WOUNDING_POISON, **LEFT_SAVES)
    _, prompts = resolve(action_sender(c, t, m, 'Prepare', target_id=RIGHT), {RIDE_CHOICE: ['RIDE']})
    prompt = next((p.get('moment') for p in prompts if RIDE_CHOICE in str(p.get('context'))), '')
    assert 'Prepare' in prompt, prompt
    assert 'Visitor' in prompt, prompt
    # the table names the paying pool, so assert the printed price is quoted rather than which pool it is
    assert 'Spend 2' in prompt, prompt
    assert 'Qi' in prompt or 'CP' in prompt, prompt
    assert 'Toxin Burden' in prompt and 'Dose Mark' in prompt, prompt


# ------------------------------------------------------------------------------ the Blood rider's Disadvantage
BLOOD = 'tianxia.sphere.blood'
# The printed rider needs a bleeding, wounded target and the ride accepted: the saving throw the Disadvantage clause
# covers is the one Venom in the Wound itself makes, under its own source id.
WOUND_BLEEDING = [{'type': 'condition', 'condition': 'bleeding', 'applies_to': 'target',
                   'expires_on': 'START_OF_TARGET_NEXT_TURN'}] + WOUNDING_POISON
# Wounded by hit points alone, with no Bleeding condition, so the "if it is currently bleeding" half is what is absent.
WOUND_UNBLEEDING = WOUNDING_POISON
# A Constitution save that names no toxin, from a character who does have the Blood sphere.
UNRELATED_SAVE = [{'type': 'condition', 'condition': 'bleeding', 'applies_to': 'target',
                   'expires_on': 'START_OF_TARGET_NEXT_TURN'},
                  {'type': 'damage', 'flat': 5, 'damage_types': ['bludgeoning'], 'applies_to': 'target'},
                  {'type': 'save', 'ability': 'con',
                   'on_fail': [{'type': 'condition', 'condition': 'stunned', 'applies_to': 'target',
                                'expires_on': 'START_OF_TARGET_NEXT_TURN'}],
                   'on_success': []}]


def _saves(engine, actor_id=None):
    return [ev for ev in _events(engine, 'SAVE_ROLLED', actor_id)]


def _last_save(c, m):
    """The target's most recent save in the reloaded fight."""
    return _saves(reload(c, m), RIGHT)[-1]


def _wound_save(engine):
    """The saving throw the printed Venom in the Wound rider itself made."""
    return next(ev for ev in _saves(engine, RIGHT) if ev.source_definition_id == WOUND)


def _mode_of(save):
    return save.payload.get('mode'), len(save.payload.get('dice') or [])


@pytest.mark.parametrize('bleeding', [True, False])
def test_the_blood_sphere_gives_a_bleeding_target_disadvantage_on_the_wounds_own_save(tmp_path, bleeding):
    """Printed: "If you have the Blood sphere ... the target has Disadvantage on the saving throw if it is currently
    bleeding." Disadvantage is a d20 mode -- two dice, the lower kept -- not a one-less modifier on a single die.

    The saving throw the clause names is the rider's own, so this asserts on the save whose source is Venom in the
    Wound and not on whichever save happened to be last."""
    prepare = WOUND_BLEEDING if bleeding else WOUND_UNBLEEDING
    c, t, m = fight(tmp_path, [WOUND], cl=15, prepare=prepare, spheres=[BLOOD], **LEFT_SAVES)
    resolve(action_sender(c, t, m, 'Prepare', target_id=RIGHT), {RIDE_CHOICE: ['RIDE']})
    save = _wound_save(reload(c, m))
    assert _mode_of(save) == (('DISADVANTAGE', 2) if bleeding else ('NORMAL', 1)), save.payload


def test_a_poison_only_character_never_imposes_the_bleeding_disadvantage(tmp_path):
    """"If you have the Blood sphere" -- a character with only the Poison Sphere has not bought that clause, so the
    rider's own save is an ordinary one. Without this gate every Venom in the Wound character taxed unrelated saves."""
    c, t, m = fight(tmp_path, [WOUND], cl=15, prepare=WOUND_BLEEDING, **LEFT_SAVES)
    resolve(action_sender(c, t, m, 'Prepare', target_id=RIGHT), {RIDE_CHOICE: ['RIDE']})
    save = _wound_save(reload(c, m))
    assert _mode_of(save) == ('NORMAL', 1), save.payload


def test_the_blood_disadvantage_does_not_reach_another_poison_save(tmp_path):
    """The clause names *the* saving throw -- the rider's own -- not every toxin save the character provokes. RIGHT's
    own poison save in the same action is a normal one even with the Blood sphere bought."""
    c, t, m = fight(tmp_path, [WOUND], cl=15, prepare=WOUND_BLEEDING, spheres=[BLOOD], **LEFT_SAVES)
    resolve(action_sender(c, t, m, 'Prepare', target_id=RIGHT), {RIDE_CHOICE: ['RIDE']})
    others = [ev for ev in _saves(reload(c, m), RIGHT) if ev.source_definition_id != WOUND]
    assert others, 'the poison save this test distinguishes the rider from must really happen'
    for save in others:
        assert _mode_of(save) == ('NORMAL', 1), save.payload


def test_the_bleeding_disadvantage_does_not_touch_an_unrelated_save(tmp_path):
    """A save that names no toxin is not one the printed forged-technique clause can be shown to cover."""
    c, t, m = fight(tmp_path, [WOUND], cl=15, prepare=UNRELATED_SAVE, spheres=[BLOOD])
    resolve(action_sender(c, t, m, 'Prepare', target_id=RIGHT))
    save = _last_save(c, m)
    assert _mode_of(save) == ('NORMAL', 1), save.payload


def test_the_bleeding_disadvantage_does_not_touch_a_save_from_a_character_without_the_talent(tmp_path):
    """Checklist 3: the rider is inert for a creature that does not own Venom in the Wound. LEFT poisons and RIGHT
    bleeds, but with no talent LEFT never offers the ride, so no such saving throw is ever made."""
    c, t, m = fight(tmp_path, [], cl=15, prepare=WOUND_BLEEDING, spheres=[BLOOD], **LEFT_SAVES)
    _, prompts = resolve(action_sender(c, t, m, 'Prepare', target_id=RIGHT))
    assert not any(RIDE_CHOICE in str(p.get('context')) for p in prompts), 'a caster without the talent is never asked'
    e = reload(c, m)
    assert not [ev for ev in _saves(e, RIGHT) if ev.source_definition_id == WOUND], \
        'and no saving throw under the rider\'s own source exists to be penalised'
    for save in _saves(e, RIGHT):
        assert _mode_of(save) == ('NORMAL', 1), save.payload


# ------------------------------------------------------------------------------ save-success Temporary HP


def _left_saves_against_poison(c, t, m):
    """RIGHT spends its turn poisoning LEFT, and LEFT owns the printed rider. Returns the reloaded fight and the
    prompts that action raised, so a test can assert on what was offered as well as on what was kept."""
    _, prompts = resolve(lambda answers: act(t, m, 'Cause', answers, target_id=LEFT))
    return reload(c, m), prompts


def _temp_hp_grants(engine, actor_id=LEFT):
    """Every Temporary HP grant this creature actually received. ``combat/gate2_engine._grant_temp_hp`` keeps
    ``max(before, amount)``, so the stored number alone cannot tell a second payment from the first."""
    return [ev for ev in _events(engine, 'TEMP_HP_GRANTED') if actor_id in (ev.target_ids or ())]


def _poisoner(*, cause=POISON_HIT, **fight_kw):
    """RIGHT poisons LEFT. A save's DC is read from the *poisoning* action's numbers, so cause_save_dc=-100 is what makes
    LEFT's saving throw a certain success -- and the reward is earned only by succeeding."""
    return dict(cl=15, cause=cause, cause_name='Cause', cause_save_dc=-100, **RIGHT_FIRST, **fight_kw)


def test_venom_body_method_grants_the_saving_creatures_own_proficiency_bonus(tmp_path):
    """Printed: "you gain Temporary HP equal to your Proficiency Bonus" -- the creature that saved, not the poisoner.

    LEFT owns the rider at Proficiency Bonus 6; the poisoner RIGHT has 2, so reading the triggering action's numbers
    would have paid 2 and reading the poisoner's own numbers 4.
    """
    c, t, m = fight(tmp_path, [BODY], **_poisoner(left_pb=6, right_pb=2))
    turn(t, m, RIGHT)
    e, _ = _left_saves_against_poison(c, t, m)
    assert _temp_hp(e.state.actors[LEFT]) == 6, 'the reward uses the saving creature\'s own Proficiency Bonus'


def test_venom_body_method_pays_once_per_round_across_the_owners_turn_start(tmp_path):
    """Printed: "Once per round" -- and a turn start must not clear that clock.

    LEFT acts second, so a save during RIGHT's turn and another during LEFT's own turn fall in the same round with LEFT's
    turn start between them. Only one of them may pay. The packet here is the save alone: it commits no damage, because
    committed damage is absorbed from Temporary HP (combat/gate2_engine._deal) and would move the number this boundary is
    measured on. The guarantee is read from the grants themselves, since max(before, amount) would leave the stored
    number unchanged even if the rider paid twice.
    """
    c, t, m = fight(tmp_path, [BODY], prepare=POISON_SAVE_SELF, prepare_target='SELF',
                    **_poisoner(cause=POISON_SAVE_ONLY, left_pb=6, right_pb=2, left_save_dc=-100))
    turn(t, m, RIGHT)                                       # RIGHT's turn comes first in the round...
    e, _ = _left_saves_against_poison(c, t, m)               # ...and RIGHT poisons LEFT, who saves and is paid for that round
    assert _temp_hp(e.state.actors[LEFT]) == 6, _temp_hp_grants(e)
    paid_round = e.state.round_number
    assert len(_events(e, 'SAVE_ROLLED', LEFT)) == 1
    turn(t, m, LEFT)                                        # RIGHT's turn ends; LEFT's own turn starts here
    resolve(lambda answers: act(t, m, 'Prepare', answers))   # ...and LEFT makes a second poison save in the same round
    e = reload(c, m)
    me = e.state.actors[LEFT]
    assert e.state.round_number == paid_round, 'both saves must be in the same round'
    assert len(_events(e, 'SAVE_ROLLED', LEFT)) == 2
    assert me.turn_flags.get(poison.BODY_ROUND_KEY) == int(e.state.round_number), \
        'the once-per-round clock must survive the owner\'s turn start'
    assert _temp_hp_grants(e) and [row.payload['offered'] for row in _temp_hp_grants(e)] == [6], \
        f'exactly one grant, for this round only: {[(r.payload["offered"]) for r in _temp_hp_grants(e)]}'
    assert _temp_hp(me) == 6, 'a second save in the same round pays nothing more'


def test_thousand_poison_immunity_is_asked_and_may_be_declined(tmp_path):
    """Printed: "you may gain" -- an optional decision the player makes, asked rather than spent silently."""
    c, t, m = fight(tmp_path, [THOUSAND], cl=15, cause=POISON_SAVE_ONLY, cause_name='Cause',
                    cause_save_dc=-100, left_pb=6, right_pb=2, **RIGHT_FIRST)
    turn(t, m, RIGHT)
    _, prompts = resolve(lambda answers: act(t, m, 'Cause', answers, target_id=LEFT),
                         {THOUSAND_CHOICE: []})
    assert any(THOUSAND_CHOICE in str(p.get('context')) for p in prompts), 'the optional use must be offered'
    me = reload(c, m).state.actors[LEFT]
    assert _temp_hp(me) == 0, 'declining grants nothing'
    assert me.turn_flags.get(poison.THOUSAND_KEY) != 'spent', 'declining must not spend the once-per-rest use'


def test_thousand_poison_immunity_pays_twice_the_saving_creatures_proficiency_bonus_and_only_once(tmp_path):
    """Printed: "Once per short rest" -- a fight contains no short rest, so the use is spent for the whole fight.

    The second save happens in a later round, after the owner's turn boundary, and the guarantee is read from the grants
    and the offer: ``max(before, amount)`` would leave the stored 12 in place even if the rider paid twice."""
    c, t, m = fight(tmp_path, [THOUSAND], cl=15, cause=POISON_SAVE_ONLY, cause_name='Cause',
                    cause_save_dc=-100, left_pb=6, right_pb=2, **RIGHT_FIRST)
    turn(t, m, RIGHT)
    e, _ = _left_saves_against_poison(c, t, m)
    me = e.state.actors[LEFT]
    assert _temp_hp(me) == 12, 'twice the saving creature\'s own Proficiency Bonus (6), not twice the poisoner\'s'
    assert me.turn_flags.get(poison.THOUSAND_KEY) == 'spent'
    resolve(lambda answers: act(t, m, 'end', answers))
    turn(t, m, RIGHT)                                       # cross LEFT's turn before the next poison save
    e, prompts = _left_saves_against_poison(c, t, m)
    assert [row.payload['offered'] for row in _temp_hp_grants(e)] == [12], \
        'the once-per-short-rest use is spent for this fight'
    assert not any(THOUSAND_CHOICE in str(p.get('context')) for p in prompts), \
        'and it is not even offered again'
    assert _temp_hp(e.state.actors[LEFT]) == 12


@pytest.mark.parametrize('ai', [False, True], ids=['manual-opponent', 'ai-opponent'])
def test_the_thousand_prompt_names_the_triggering_action_on_an_opponents_turn(tmp_path, ai):
    """Checklist 9 and 13: the save resolves during somebody else's action, so the prompt must say which one."""
    c, t, m = fight(tmp_path, [THOUSAND], cl=15, cause=POISON_SAVE_ONLY, cause_name='Venomous Strike',
                    cause_save_dc=-100, left_pb=6, right_pb=2, **RIGHT_FIRST)
    turn(t, m, RIGHT)
    _, prompts = resolve(action_sender(c, t, m, 'Venomous Strike', ai=ai, target_id=LEFT),
                         {THOUSAND_CHOICE: ['TEMPORARY_HP']})
    prompt = next((p.get('moment') for p in prompts if THOUSAND_CHOICE in str(p.get('context'))), '')
    assert 'Venomous Strike' in prompt, prompt
    assert 'Keeper' in prompt, prompt
    assert '12' in prompt, prompt
    assert _temp_hp(reload(c, m).state.actors[LEFT]) == 12


def test_the_thousand_prompt_names_the_triggering_action_on_the_owners_own_turn(tmp_path):
    """The same offer, when the saving creature's own action caused the save."""
    c, t, m = fight(tmp_path, [THOUSAND], cl=15, cause=POISON_HIT, cause_name='Cause', cause_save_dc=-100,
                    prepare=POISON_SAVE_SELF, prepare_target='SELF', left_pb=6, right_pb=2, left_save_dc=-100,
                    **RIGHT_FIRST)
    _, prompts = resolve(lambda answers: act(t, m, 'Prepare', answers), {THOUSAND_CHOICE: ['TEMPORARY_HP']})
    prompt = next((p.get('moment') for p in prompts if THOUSAND_CHOICE in str(p.get('context'))), '')
    assert 'Prepare' in prompt, prompt
    assert 'Keeper' in prompt, prompt


def test_an_automatic_owner_takes_the_optional_temporary_hp_without_a_table_pause(tmp_path):
    """Checklist 9: a decision the table does not own is taken by the creature that owns it. LEFT is Local Auto here,
    so its own turn never reaches the table and the optional use must resolve itself."""
    c, t, m = fight(tmp_path, [THOUSAND], cl=15, cause=POISON_SAVE_ONLY, cause_name='Cause',
                    cause_save_dc=-100, left_pb=6, right_pb=2, **RIGHT_FIRST)
    turn(t, m, RIGHT)
    c.set_controller_mode(m, actor_id=LEFT, controller_mode='LOCAL_AUTO')
    result, prompts = resolve(lambda answers: act(t, m, 'Cause', answers, target_id=LEFT))
    assert not any(THOUSAND_CHOICE in str(p.get('context')) for p in prompts), \
        'an automatic creature is not asked at the table'
    assert result['status'] == 'COMMITTED', result['status']
    e = reload(c, m)
    assert _temp_hp(e.state.actors[LEFT]) == 12, 'it decides for itself and takes the printed benefit'
    assert e.state.actors[LEFT].turn_flags.get(poison.THOUSAND_KEY) == 'spent'


def test_venom_body_method_still_pays_when_thousand_poison_immunity_is_declined(tmp_path):
    """Each rider keeps its own limit: Venom Body Method's benefit is mandatory and must not be suppressed by a
    declined, optional one."""
    c, t, m = fight(tmp_path, [BODY, THOUSAND], **_poisoner(left_pb=6, right_pb=2))
    turn(t, m, RIGHT)
    _, prompts = resolve(lambda answers: act(t, m, 'Cause', answers, target_id=LEFT),
                         {THOUSAND_CHOICE: []})
    assert any(THOUSAND_CHOICE in str(p.get('context')) for p in prompts), 'the optional use is still offered'
    me = reload(c, m).state.actors[LEFT]
    assert _temp_hp(me) == 6, 'the mandatory once-per-round benefit survives the decline'
    assert me.turn_flags.get(poison.THOUSAND_KEY) != 'spent'


def test_a_failed_poison_save_grants_no_venom_temporary_hp(tmp_path):
    """The rider is earned by succeeding, not by taking poison."""
    c, t, m = fight(tmp_path, [BODY], cl=15, cause=POISON_HIT, cause_name='Cause',
                    cause_save_dc=100, **RIGHT_FIRST)
    turn(t, m, RIGHT)
    resolve(lambda answers: act(t, m, 'Cause', answers, target_id=LEFT))
    assert _temp_hp(reload(c, m).state.actors[LEFT]) == 0


def test_the_temporary_hp_riders_stay_inert_for_a_character_without_them(tmp_path):
    """LEFT owns neither rider and really makes a poison save, so the whole mechanism must stay out of its way."""
    c, t, m = fight(tmp_path, [], **_poisoner(left_pb=6, right_pb=2))
    turn(t, m, RIGHT)
    e, _ = _left_saves_against_poison(c, t, m)
    me = e.state.actors[LEFT]
    assert _events(e, 'SAVE_ROLLED', LEFT), 'LEFT really did make a poison save'
    assert _events(e, 'SAVE_ROLLED', LEFT)[-1].payload['success']
    assert _temp_hp(me) == 0, 'no talent, no Temporary HP'
    assert not _temp_hp_grants(e), 'and nothing was ever granted'
    assert not [k for k in me.turn_flags if 'poison' in k], 'and no bookkeeping left behind'
