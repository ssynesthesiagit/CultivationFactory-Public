"""AUTO77 (Fire sphere): the printed fire effects the table now runs, at the table.

Every test here plays the real compiled character through the real engine (tests.test_auto_support._engine over
combat.factory_compiler.compile_character), so it fails if the printed effect stops happening in a fight, not only if a
helper changes. The printed text is the owner's, in APP/authority/typed_mechanics/rules_text.json.
"""

from __future__ import annotations

import copy
import json
from functools import lru_cache
from pathlib import Path

import pytest

from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent, ReactionDecision
from combat.gate4_engine import Gate4ControllerEngine
from tests.h1_support import sheet
from tests.test_auto_support import ME, _engine
from tests.test_zones import SHEET

ROOT = Path(__file__).resolve().parents[1]
AUTH = json.loads((ROOT / 'authority/Tianxia_Typed_Mechanics_Authority_R1.json').read_text())['mechanics']
SPHERE = 'tianxia.sphere.fire'
FIRE = 'tianxia.talent.fire.'
ALLY = 'actor:factory.auto77f1-ally'
SECOND = 'actor:factory.auto77f1-second'
KIT = {'starting_kit': {'items': [{'item_id': 'tianxia.mortal.weapon.fu', 'name': 'Fu (Short Axe)', 'quantity': 1}]}}
AXE = 'Fu (Short Axe) attack'
BASE_ABILITIES = sorted(key for key, row in AUTH.items() if row.get('sphere_id') == SPHERE and row.get('kind') == 'base_ability')


@lru_cache(maxsize=None)
def compiled(keys: tuple[str, ...], cl: int = 20, dc: int = 50):
    sheet = {**SHEET, 'equipment': [KIT], 'identity': {**SHEET['identity'], 'cultivation_level': cl},
             'ability_scores_and_statistics': {**SHEET['ability_scores_and_statistics'], 'technique_save_dc': dc,
                                              'technique_attack_bonus': 40,
                                              'primary_resource': {'name': 'Qi', 'maximum': 100}},
             'spheres_and_talents': {'sphere_record_ids': [SPHERE],
                                     'learned_talent_record_ids': list(dict.fromkeys([*BASE_ABILITIES, *keys]))}}
    return compile_character(sheet, actor_id=ME)


def fight(*keys: str, cl: int = 20, dc: int = 50, foe_at: tuple[int, int] = (4, 6)):
    bundle = copy.deepcopy(compiled(tuple(keys), cl, dc))
    engine = _engine(bundle, foe_at=foe_at)
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    foe.maximum_hp = foe.current_hp = 2000
    foe.armor_class = -50
    me.resources['resource:core.martial_focus'] = 1
    return bundle, engine, me, foe


def cast(engine, prefix: str, contains: str = '', exclude: tuple[str, ...] = (), dest: tuple[int, int] | None = None,
         target: str | None = None):
    """Press one button: the first whose printed name starts with ``prefix`` (and holds ``contains``), skipping any
    longer button the caller names in ``exclude``; ``dest`` pins the square a line or area is aimed at."""
    found = [c for c in engine.legal_candidates()
             if c.display_name.startswith(prefix) and contains in c.display_name
             and not c.display_name.startswith(exclude)
             and (target is None or target in (c.target_ids or ()))
             and (dest is None or (c.destination is not None and (c.destination.x, c.destination.y) == dest))]
    assert found, (prefix, contains, dest, sorted({c.display_name for c in engine.legal_candidates()}))
    aim = engine.state.actors[AN].position
    chosen = min(found, key=lambda c: 0 if c.destination is None
                 else abs(c.destination.x - aim.x) + abs(c.destination.y - aim.y))
    engine.execute_intent(ActionIntent(intent_id='auto77', decision_id=chosen.decision_id, candidate_id=chosen.candidate_id,
                                       state_version=chosen.state_version, actor_id=chosen.actor_id, target_ids=chosen.target_ids,
                                       destination=chosen.destination))
    return chosen.display_name


def payloads(engine, kind: str):
    return [dict(event.payload) for event in engine.events if event.event_type == kind]


def expressions(engine):
    return [row['expression'].removesuffix('+0') for row in payloads(engine, 'DAMAGE_ROLLED')]


def fire_damage(engine):
    return [row for row in payloads(engine, 'DAMAGE_COMMITTED') if row.get('damage_type') == 'FIRE']


def damage_to(engine, who: str):
    """Every damage packet that landed on one creature."""
    return [dict(event.payload) for event in engine.events
            if event.event_type == 'DAMAGE_COMMITTED' and who in (event.target_ids or ())]


def condition(actor, name: str):
    return [c for c in actor.conditions.values() if c.condition_id == f'condition:typed.{name}']


def fire_only_picks(engine, **picks):
    """Immediate answer provider for this module's own ``choice:fire.*`` questions only; every other reaction is left to
    the engine (returning None), so unrelated questions behave exactly as they do in a real fight. Returns the requests
    seen, in order."""
    seen = []

    def provider(request):
        if not str(request['reaction_source_id']).startswith('choice:fire.'):
            return None, None
        seen.append(request)
        options = list(request['legal_option_ids'])
        choose = picks.get(str(request['reaction_source_id'])) or picks.get(str(request['reaction_source_id']).split('.')[-1])
        chosen = choose(options) if choose is not None else options[:1]
        return ReactionDecision(checkpoint=request['checkpoint'], reactor_id=request['reactor_id'],
                                reaction_source_id=request['reaction_source_id'],
                                selection='DECLINE' if chosen is None else 'USE',
                                option_ids=tuple(chosen or ())), None

    engine.set_reaction_provider(provider)
    return seen


def end_turn(engine):
    candidate = next(c for c in engine.legal_candidates() if c.display_name == 'End turn')
    engine.execute_intent(ActionIntent(intent_id=f'end-{engine.state.event_sequence}', decision_id=candidate.decision_id,
                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                       actor_id=candidate.actor_id, target_ids=candidate.target_ids))
    return engine.state.current_actor_id


# --------------------------------------------------------------------------- Burning Weapon
def test_burning_weapon_flames_the_imbued_strike_with_printed_fire_damage_and_burn():
    """"Imbue one weapon, unarmed strike, or natural weapon with flame. Once per turn when the bearer hits with that weapon,
    add Fire damage: 1-10: 1d6; 11-16: 2d6; 17-20: 3d6. The hit applies Burn."

    Before this the compiled action charged 1 CP and did nothing else: no added roll, no Burn, four reminder lines."""
    _, engine, me, foe = fight('FIRE_TAL_BURNING_WEAPON')
    assert cast(engine, 'Burning Weapon') == 'Burning Weapon'
    assert cast(engine, AXE) == AXE
    assert '3d6' in expressions(engine), expressions(engine)
    assert fire_damage(engine), fire_damage(engine)
    assert condition(foe, 'burning'), sorted(foe.conditions)


@pytest.mark.parametrize('cl,expression', [(5, '1d6'), (11, '2d6'), (17, '3d6')])
def test_burning_weapon_extra_damage_scales_with_cultivation_level(cl, expression):
    """"Cultivation Level Extra Damage: 1-10: 1d6; 11-16: 2d6; 17-20: 3d6"."""
    _, engine, _me, _foe = fight('FIRE_TAL_BURNING_WEAPON', cl=cl)
    cast(engine, 'Burning Weapon')
    cast(engine, AXE)
    assert expression in expressions(engine), expressions(engine)


def test_burning_weapon_adds_fire_damage_once_per_turn():
    """"Once per turn when the bearer hits with that weapon": the second imbued strike on the same turn adds nothing."""
    _, engine, me, _foe = fight('FIRE_TAL_BURNING_WEAPON')
    cast(engine, 'Burning Weapon')
    cast(engine, AXE)
    me.action_available = True   # the bearer's second strike on the same turn, given back for the test
    cast(engine, AXE)
    assert expressions(engine).count('3d6') == 1, expressions(engine)


def test_burning_weapon_does_not_burn_the_bearer_or_a_creature_it_never_hit():
    """The flame rides the bearer's own hit; the Talent does not burn whoever it is used on."""
    _, engine, me, foe = fight('FIRE_TAL_BURNING_WEAPON')
    cast(engine, 'Burning Weapon')
    assert not condition(me, 'burning') and not condition(foe, 'burning')


def test_a_character_without_burning_weapon_never_gets_the_added_fire_damage():
    """Default-inert: the added roll and Burn need this character's own compiled row."""
    _, engine, me, foe = fight(FIRE + 'blazing_armor')
    assert not [name for name in {c.display_name for c in engine.legal_candidates()} if name.startswith('Burning Weapon')]
    cast(engine, AXE)
    assert '3d6' not in expressions(engine)
    assert not condition(foe, 'burning')


def test_burning_weapon_keeps_its_flame_on_later_turns_and_ends_with_its_concentration():
    """"Duration: Concentration, up to 1 minute" -- the flame rides the whole concentration, not the turn it was made on.

    Before this the state carried END_OF_CURRENT_TURN, so every turn after the first lost the paid-for damage and Burn, and
    it was filed under a mechanic id, so no concentration cleanup could ever take it."""
    _, engine, me, foe = fight('FIRE_TAL_BURNING_WEAPON')
    cast(engine, 'Burning Weapon')
    (state,) = condition(me, 'state.burning_weapon')
    assert state.expires_on == 'CONCENTRATION_END'
    assert state.source_definition_id == me.concentration.source_definition_id
    cast(engine, AXE)
    assert expressions(engine).count('3d6') == 1
    end_turn(engine)  # the foe's turn
    assert end_turn(engine) == ME, 'back to the bearer for a second turn'
    assert condition(me, 'state.burning_weapon'), 'the flame is still burning after one more round'
    cast(engine, AXE)
    assert expressions(engine).count('3d6') == 2, expressions(engine)
    engine._end_concentration(me, 'FAILED_DAMAGE_CHECK')
    assert not condition(me, 'state.burning_weapon')
    me.action_available = True   # one more strike that same turn, given back for the test
    cast(engine, AXE)
    assert expressions(engine).count('3d6') == 2, 'the flame is gone with its Concentration'


def test_burning_weapon_offers_the_bearers_weapons_by_name_and_honours_a_declined_imbue():
    """A real choice: the menu names the weapons, and a real "no" imbuing nothing is a "no"."""
    _, engine, me, _foe = fight('FIRE_TAL_BURNING_WEAPON')
    seen = fire_only_picks(engine)
    cast(engine, 'Burning Weapon')
    (request,) = seen
    assert request['reaction_source_id'] == 'choice:fire.imbue_weapon'
    assert request['legal_option_ids'] == ['tianxia.mortal.weapon.fu', 'unarmed']
    labels = request['choice_trigger']['labels']
    assert labels['tianxia.mortal.weapon.fu'] == 'Flame your Fu (Short Axe)', labels
    assert not any('tianxia.mortal' in text for text in labels.values()), labels
    assert 'unarmed strike' in labels['unarmed'], labels
    _, declined, me2, _ = fight('FIRE_TAL_BURNING_WEAPON')
    fire_only_picks(declined, **{'imbue_weapon': lambda options: None})
    cast(declined, 'Burning Weapon')
    assert not condition(me2, 'state.burning_weapon'), 'a declined Burning Weapon imbues nothing'


def test_burning_weapon_imbues_the_strike_of_a_bearer_the_user_touches():
    """"Imbue one weapon, unarmed strike, or natural weapon ... when the bearer hits with that weapon": the bearer is the
    creature the Touch-range action was aimed at, and the flame rides *its* strike."""
    bundle = copy.deepcopy(compiled(('FIRE_TAL_BURNING_WEAPON',)))
    ally = compile_character({**SHEET, 'identity': {**SHEET['identity'], 'display_name': 'Wandering Student'}},
                             actor_id=ALLY)
    foe_bundle = compile_character(SHEET, actor_id=AN)
    engine = Gate4ControllerEngine(ROOT, match_seed='AUTO77F1-BEARER', typed_bundles=(bundle, ally, foe_bundle),
                                   roster_setup={'primary_actor_ids': [ME, ALLY, AN],
                                                 'team_by_actor': {ME: 'team:a', ALLY: 'team:a', AN: 'team:b'},
                                                 'starting_positions': {ME: {'x': 3, 'y': 6}, ALLY: {'x': 4, 'y': 6},
                                                                        AN: {'x': 5, 'y': 6}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    me, ally_actor, foe = engine.state.actors[ME], engine.state.actors[ALLY], engine.state.actors[AN]
    for actor in (me, ally_actor, foe):
        actor.maximum_hp = actor.current_hp = 400
    foe.armor_class = -50
    cast(engine, 'Burning Weapon', target=ALLY)
    assert condition(ally_actor, 'state.burning_weapon'), 'the ally the user touched carries the flame'
    assert not condition(me, 'state.burning_weapon')
    assert end_turn(engine) == ALLY, 'now the bearer acts'
    strike = next((c for c in engine.legal_candidates() if c.actor_id == ALLY and 'Unarmed' in c.display_name), None)
    assert strike is not None, sorted({c.display_name for c in engine.legal_candidates()})
    engine.execute_intent(ActionIntent(intent_id='ally-strike', decision_id=strike.decision_id, candidate_id=strike.candidate_id,
                                       state_version=strike.state_version, actor_id=ALLY, target_ids=strike.target_ids,
                                       destination=strike.destination))
    assert '3d6' in expressions(engine), expressions(engine)
    assert condition(foe, 'burning'), 'the bearer applied Burn to what it hit'


# --------------------------------------------------------------------------- a countered cast (AUTO77r1f1)
COUNTERWEAVE = 'TAL_QIWEAVING_COUNTERWEAVE'


def countered(talents, cl=20, dc=50):
    """The owner's Fire talents against a fighter whose own Counterweave wins every contest it is offered
    ("Use Unweave Pattern against the triggering technique ... On a success, the technique fails"): the talent the owner
    uses is read as countered and resolves nothing at all. A real technique_used reaction, answered by the engine from that
    fighter's own compiled reaction plan -- not a stubbed engine flag."""
    bundle = copy.deepcopy(compiled(tuple(talents), cl, dc))
    foe_sheet = sheet([COUNTERWEAVE], cl=cl, dc=dc)
    foe_sheet['identity']['display_name'] = 'Unweaver'
    foe_sheet['ability_scores_and_statistics']['technique_attack_bonus'] = 100   # the contest is won, every time
    other = {**SHEET, 'identity': {**SHEET['identity'], 'display_name': 'Second Enemy'}}
    engine = Gate4ControllerEngine(ROOT, match_seed='AUTO77R1F1-COUNTER',
                                   typed_bundles=(bundle, compile_character(foe_sheet, actor_id=AN),
                                                  compile_character(other, actor_id=SECOND)),
                                   roster_setup={'primary_actor_ids': [ME, AN, SECOND],
                                                 'team_by_actor': {ME: 'team:a', AN: 'team:b', SECOND: 'team:b'},
                                                 'starting_positions': {ME: {'x': 3, 'y': 6}, AN: {'x': 4, 'y': 6},
                                                                        SECOND: {'x': 4, 'y': 7}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    me, foe, enemy = engine.state.actors[ME], engine.state.actors[AN], engine.state.actors[SECOND]
    for actor in (me, foe, enemy):
        actor.maximum_hp = actor.current_hp = 2000
        actor.armor_class = -50
    me.resources['resource:core.martial_focus'] = 1
    return engine, me, foe, enemy


def riders(engine):
    return [str(row.get('rider') or '') for row in payloads(engine, 'GM_RIDER')]


def test_a_countered_burning_weapon_imbues_nothing_and_never_burns():
    """"Duration: Concentration, up to 1 minute": a Burning Weapon the table reads as countered never began that
    Concentration, so the printed flame never existed -- no question, no state, and no added Fire damage on any later turn.

    Before this the state was filed with UNTIL_REMOVED whenever the Concentration was absent, so a failed cast became a
    buff with no deadline at all: fight-long extra Fire damage and Burn from a talent that did nothing."""
    engine, me, foe, _enemy = countered(('FIRE_TAL_BURNING_WEAPON',))
    seen = fire_only_picks(engine)
    cast(engine, 'Burning Weapon')
    assert any('the technique is countered' in text for text in riders(engine)), riders(engine)
    assert [row['reaction_source_id'] for row in seen] == [], 'a cast that failed is asked nothing'
    assert not condition(me, 'state.burning_weapon')
    assert me.concentration is None, 'the printed Concentration was never begun'
    cast(engine, AXE)
    assert not fire_damage(engine), fire_damage(engine)
    assert not condition(foe, 'burning'), sorted(foe.conditions)


# --------------------------------------------------------------------------- White-Hot Focus
FOCUS_MODES = ('Disadvantage', 'key ability modifier', 'Advantage on one attack roll', "ignore one target's Resistance")


@pytest.mark.parametrize('reads', FOCUS_MODES)
def test_white_hot_focus_offers_one_button_per_benefit_the_table_resolves(reads):
    """"The next Fire talent you use this turn gains one:" -- one button per printed benefit the table can run."""
    _, engine, _me, _foe = fight(FIRE + 'white_hot_focus')
    names = {c.display_name for c in engine.legal_candidates() if c.display_name.startswith('White-Hot Focus')}
    assert any(reads in name for name in names), sorted(names)
    assert all('CP' in name for name in names if reads in name)


def test_white_hot_focus_disadvantage_is_spent_on_the_next_fire_saving_throw():
    """"one target has Disadvantage on its saving throw". Conflagration's own Dexterity save is the next Fire talent's."""
    _, engine, me, foe = fight(FIRE + 'white_hot_focus')
    cast(engine, 'White-Hot Focus', 'Disadvantage')
    cast(engine, 'Conflagration', 'at 4,6')
    saves = [row for row in payloads(engine, 'SAVE_ROLLED') if row['actor_id'] == foe.entity_id]
    assert saves and saves[-1]['mode'] == 'DISADVANTAGE', saves
    assert not [c for c in me.conditions.values() if 'white_hot_focus_save_disadvantage' in c.condition_id]


def test_white_hot_focus_adds_the_key_ability_modifier_to_one_fire_damage_roll():
    """"add your Path key ability modifier to one Fire damage roll": the modifier lands on the roll, and only one roll."""
    _, engine, me, _foe = fight(FIRE + 'white_hot_focus')
    cast(engine, 'White-Hot Focus', 'key ability modifier')
    cast(engine, 'Ignite: Push Target')
    _, plain, _me, _foe = fight(FIRE + 'white_hot_focus')
    cast(plain, 'Ignite: Push Target')
    before_modifier = int(payloads(plain, 'DAMAGE_ROLLED')[-1]['expression'].split('+')[1])
    after_modifier = int(payloads(engine, 'DAMAGE_ROLLED')[-1]['expression'].split('+')[1])
    assert after_modifier == 2 * before_modifier, (before_modifier, after_modifier)
    assert not [c for c in me.conditions.values() if 'white_hot_focus_damage' in c.condition_id]


def test_white_hot_focus_takes_the_printed_self_damage():
    """"After the talent resolves, take Fire damage equal to your Proficiency Bonus." """
    _, engine, me, _foe = fight(FIRE + 'white_hot_focus')
    before = me.current_hp
    cast(engine, 'White-Hot Focus', 'Disadvantage')
    assert me.current_hp == before, 'backlash waits for the next talent to resolve'
    cast(engine, 'Ignite', target=AN)
    assert before - me.current_hp == me.proficiency_bonus, (before, me.current_hp, me.proficiency_bonus)
    assert [row for row in fire_damage(engine) if row.get('hp_damage') == me.proficiency_bonus]


def test_white_hot_focus_does_nothing_for_a_character_that_does_not_own_it():
    """Default-inert for everyone else."""
    _, engine, me, _foe = fight(FIRE + 'blazing_armor')
    assert not [name for name in {c.display_name for c in engine.legal_candidates()} if name.startswith('White-Hot Focus')]
    cast(engine, 'Ignite: Push Target')
    assert not [c for c in me.conditions.values() if 'white_hot_focus' in c.condition_id]


@pytest.mark.parametrize('talent,button', [('FIRE_TAL_FIREBALL_ART', 'Fireball Art'),
                                           ('FIRE_TAL_INCINERATING_LANCE', 'Incinerating Lance')])
def test_white_hot_focus_reaches_every_fire_talent_not_only_the_lower_case_ids(talent, button):
    """"The next Fire talent you use this turn": every Fire talent, whatever its id's spelling. The uppercase
    ``FIRE_TAL_*`` ids are compiled under the Fire sphere and must gain the printed benefit too."""
    _, engine, me, foe = fight(FIRE + 'white_hot_focus', talent)
    fire_only_picks(engine)
    cast(engine, 'White-Hot Focus', 'Disadvantage')
    cast(engine, button, exclude=(button + ' + Overheat',))
    saves = [row for row in payloads(engine, 'SAVE_ROLLED') if row['actor_id'] == foe.entity_id]
    assert saves and saves[-1]['mode'] == 'DISADVANTAGE', (talent, saves)
    assert not [c for c in me.conditions.values() if 'white_hot_focus' in c.condition_id], 'and it is spent'


def test_white_hot_focus_is_spent_by_a_fire_talent_with_no_roll_to_touch():
    """"The next Fire talent you use this turn": a talent aimed at nothing still used it up, so a later talent that does have
    a saving throw gets nothing. Before this the state survived any talent without a matching roll."""
    _, engine, me, _foe = fight(FIRE + 'white_hot_focus')
    fire_only_picks(engine)
    cast(engine, 'White-Hot Focus', 'Disadvantage')
    cast(engine, 'Conflagration', 'at 1,10')  # an empty square: no creature makes a save
    assert not [c for c in me.conditions.values() if 'white_hot_focus' in c.condition_id]


def test_white_hot_focus_asks_which_affected_creature_gets_the_benefit():
    """"one target has Disadvantage on its saving throw": which creature is that creature is the caster's answer, not the
    order the engine happened to roll them in. This fight offers two enemies; the answer names the second."""
    bundle = copy.deepcopy(compiled((FIRE + 'white_hot_focus',)))
    second = compile_character({**SHEET, 'identity': {**SHEET['identity'], 'display_name': 'Second Enemy'}}, actor_id=SECOND)
    foe_bundle = compile_character(SHEET, actor_id=AN)
    engine = Gate4ControllerEngine(ROOT, match_seed='AUTO77F1-FOCUS', typed_bundles=(bundle, foe_bundle, second),
                                   roster_setup={'primary_actor_ids': [ME, AN, SECOND],
                                                 'team_by_actor': {ME: 'team:a', AN: 'team:b', SECOND: 'team:b'},
                                                 'starting_positions': {ME: {'x': 3, 'y': 6}, AN: {'x': 4, 'y': 6},
                                                                        SECOND: {'x': 4, 'y': 7}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    me, first, other = engine.state.actors[ME], engine.state.actors[AN], engine.state.actors[SECOND]
    for actor in (me, first, other):
        actor.maximum_hp = actor.current_hp = 400
    seen = fire_only_picks(engine, **{'white_hot_focus_target': lambda options: [SECOND]})
    cast(engine, 'White-Hot Focus', 'Disadvantage')
    assert [request['legal_option_ids'] for request in seen] == [], 'no choice is asked before a Fire talent is used'
    cast(engine, 'Conflagration')
    (request,) = seen
    assert request['reaction_source_id'] == 'choice:fire.white_hot_focus_target'
    assert sorted(request['legal_option_ids']) == sorted([AN, SECOND]), request['legal_option_ids']
    assert ME not in request['legal_option_ids'], 'the caster is not a target of their own talent'
    modes = {who: [row['mode'] for row in payloads(engine, 'SAVE_ROLLED') if row['actor_id'] == who] for who in (AN, SECOND)}
    assert modes[SECOND] == ['DISADVANTAGE'], modes
    assert modes[AN] == ['NORMAL'], modes


def test_white_hot_focus_is_spent_by_a_countered_talent_and_a_second_use_of_the_same_action_gets_nothing():
    """"The next Fire talent you use this turn" is one attempted activation, not one action definition.

    The talent it was bound to was countered, so the use happened and spent it. Where an extra action lets the very same
    Fire action be used again this turn, that second activation is a different talent: it must neither be asked which
    creature gains the benefit, nor inherit the first activation's benefit or its target.

    Before this the binding recorded only the action's own id, so the second activation of the same action found the old
    binding satisfied, asked nothing, and the first activation's chosen creature saved at Disadvantage."""
    engine, me, foe, _enemy = countered((FIRE + 'white_hot_focus',))
    foe.resources['resource:core.martial_focus'] = 0     # it cannot counter while White-Hot Focus is being cast
    seen = fire_only_picks(engine)
    cast(engine, 'White-Hot Focus', 'Disadvantage')
    assert [row['reaction_source_id'] for row in seen] == [], 'casting White-Hot Focus itself asks nothing'
    foe.resources['resource:core.martial_focus'] = 1     # and now it spends that Focus countering the next Fire talent
    cast(engine, 'Conflagration', 'at 4,6')
    assert any('the technique is countered' in text for text in riders(engine)), riders(engine)
    assert [row['reaction_source_id'] for row in seen] == ['choice:fire.white_hot_focus_target'], seen
    me.action_available = True                          # the same action again this turn, given back for the test
    cast(engine, 'Conflagration', 'at 4,6')             # the same action again this turn, at the same creature
    assert [row['reaction_source_id'] for row in seen] == ['choice:fire.white_hot_focus_target'], \
        'the spent activation is not asked about again'
    saves = [row['mode'] for row in payloads(engine, 'SAVE_ROLLED') if row['actor_id'] == AN]
    assert saves == ['NORMAL'], f'the second use inherits nothing: {saves}'
    assert not [c for c in me.conditions.values() if 'white_hot_focus' in c.condition_id], 'and it is gone'


def test_white_hot_focus_spent_on_a_countered_talent_never_reaches_another_creature():
    """The same rule when the second activation of that action is aimed somewhere else: the first activation's answer
    (which creature) must not be reused, and nothing may be left over for a later talent."""
    engine, me, foe, other = countered((FIRE + 'white_hot_focus',))
    foe.resources['resource:core.martial_focus'] = 0
    seen = fire_only_picks(engine)
    cast(engine, 'White-Hot Focus', 'Disadvantage')
    foe.resources['resource:core.martial_focus'] = 1
    cast(engine, 'Conflagration', 'at 4,6')             # countered: the attempt still spent the Focus
    me.action_available = True
    cast(engine, 'Conflagration', 'at 4,7')             # the same action again, aimed at the other enemy
    assert [row['reaction_source_id'] for row in seen] == ['choice:fire.white_hot_focus_target'], seen
    saves = [row['mode'] for row in payloads(engine, 'SAVE_ROLLED') if row['actor_id'] == SECOND]
    assert saves == ['NORMAL'], saves
    assert not [c for c in me.conditions.values() if 'white_hot_focus' in c.condition_id], 'and it is gone'
    me.action_available = True
    cast(engine, 'Conflagration', 'at 4,7')
    assert [row['reaction_source_id'] for row in seen] == ['choice:fire.white_hot_focus_target'], \
        'a third activation is asked nothing either'


# --------------------------------------------------------------------------- the printed Overheat augments
def test_scorching_ray_art_overheat_adds_one_ray():
    """"Augment - 1 CP: Create one additional ray. After all rays resolve, take Fire damage equal to your Proficiency Bonus." """
    _, plain, _me, _foe = fight('FIRE_TAL_SCORCHING_RAY_ART')
    _, engine, me, _foe = fight('FIRE_TAL_SCORCHING_RAY_ART')
    cast(plain, 'Scorching Ray Art', exclude=('Scorching Ray Art + Overheat',))
    rays = len(payloads(plain, 'ATTACK_ROLLED'))
    cast(engine, 'Scorching Ray Art + Overheat')
    assert len(payloads(engine, 'ATTACK_ROLLED')) == rays + 1, (rays, len(payloads(engine, 'ATTACK_ROLLED')))
    assert me.proficiency_bonus in [row.get('hp_damage') for row in fire_damage(engine)]


def test_fireball_art_overheat_adds_two_dice_and_twice_the_proficiency_bonus():
    """"Augment - 2 CP: Increase damage by 2d6. After the attack resolves, take Fire damage equal to twice your Proficiency
    Bonus." """
    _, plain, _me, _foe = fight('FIRE_TAL_FIREBALL_ART')
    _, engine, _me2, _foe2 = fight('FIRE_TAL_FIREBALL_ART')
    cast(plain, 'Fireball Art', exclude=('Fireball Art + Overheat',))
    cast(engine, 'Fireball Art + Overheat')
    assert expressions(plain)[0].endswith('d6'), expressions(plain)
    assert int(expressions(plain)[0].split('d')[0]) + 2 == int(expressions(engine)[0].split('d')[0]), (
        expressions(plain), expressions(engine))
    assert [row.get('hp_damage') for row in fire_damage(engine)][-1] == 2 * plain.state.actors[ME].proficiency_bonus


def test_incinerating_lance_overheat_adds_two_dice():
    """"Augment - 2 CP: The line becomes 10 feet wide and damage increases by 2d8." """
    _, plain, _me, _foe = fight('FIRE_TAL_INCINERATING_LANCE')
    _, engine, _me, _foe = fight('FIRE_TAL_INCINERATING_LANCE')
    cast(plain, 'Incinerating Lance', exclude=('Incinerating Lance + Overheat',))
    cast(engine, 'Incinerating Lance + Overheat')
    assert int(expressions(plain)[0].split('d')[0]) + 2 == int(expressions(engine)[0].split('d')[0])


def test_incinerating_lance_overheat_really_widens_the_line():
    """"The line becomes 10 feet wide": a creature five feet to the side of the line is inside the widened one and outside the
    printed 5-foot one, so it must save, take Fire damage and become Burning only for the 2 CP button.

    The widened area keeps the printed 120-foot length: the augment changed ``area.width_ft`` where typed_executor's line
    geometry reads it, not the length, and not the display-only ``radius_ft``."""
    wide = {'width_ft': 10}
    plain = {'width_ft': 5}
    assert wide['width_ft'] == 10 and plain['width_ft'] == 5
    bundle = compiled(('FIRE_TAL_INCINERATING_LANCE',))
    areas = {row['display_name']: row['parameters']['typed'].get('area') for row in bundle['action_catalog']
             if 'Incinerating Lance' in row['display_name']}
    hot = next(name for name in areas if 'Overheat' in name)
    assert areas[hot]['width_ft'] == 10, areas
    assert areas[hot]['size_ft'] == 120, 'the printed 120-foot length survives'

    # The enemy stands one square (5 feet) off the line the caster aims down.
    line = (13, 6)
    _, hot_engine, _me, hot_foe = fight('FIRE_TAL_INCINERATING_LANCE', foe_at=(6, 7))
    _, cold_engine, _me2, cold_foe = fight('FIRE_TAL_INCINERATING_LANCE', foe_at=(6, 7))
    # Empty hostile areas are legal on the lane baseline too. The printed
    # width is a recipient/damage rule, not a prohibition on casting that line.
    cold = next(c for c in cold_engine.legal_candidates()
                if c.display_name.startswith('Incinerating Lance') and 'Overheat' not in c.display_name
                and c.destination is not None and (c.destination.x, c.destination.y) == line)
    assert cold.metadata['hostiles_in_area'] == 0
    fire_only_picks(cold_engine)
    cold_engine.execute_intent(ActionIntent(intent_id='lance-narrow', decision_id=cold.decision_id,
        candidate_id=cold.candidate_id, state_version=cold.state_version,
        actor_id=cold.actor_id, target_ids=cold.target_ids, destination=cold.destination))
    assert not [row for row in payloads(cold_engine, 'SAVE_ROLLED') if row['actor_id'] == cold_foe.entity_id]
    assert not damage_to(cold_engine, cold_foe.entity_id)
    fire_only_picks(hot_engine)
    chosen = next(c for c in hot_engine.legal_candidates() if 'Incinerating Lance + Overheat' in c.display_name
                  and c.destination is not None and (c.destination.x, c.destination.y) == line)
    hot_engine.execute_intent(ActionIntent(intent_id='lance-wide', decision_id=chosen.decision_id,
                                           candidate_id=chosen.candidate_id, state_version=chosen.state_version,
                                           actor_id=chosen.actor_id, target_ids=chosen.target_ids,
                                           destination=chosen.destination))
    assert [row for row in payloads(hot_engine, 'SAVE_ROLLED') if row['actor_id'] == hot_foe.entity_id], \
        'the widened line reaches the creature in the extra 5 feet'
    assert damage_to(hot_engine, hot_foe.entity_id), 'and it takes Fire damage'
    assert condition(hot_foe, 'burning')
    assert not condition(cold_foe, 'burning')


# --------------------------------------------------------------------------- Overheat self-damage reduction
def backlash_packets(engine):
    """The Fire damage one Overheat augment made its own user take, as (who, hp_damage): the packet is the one whose
    source is the augment's own button and whose recipient is the user who pressed it."""
    return [(ME, dict(event.payload).get('hp_damage')) for event in engine.events
            if event.event_type == 'DAMAGE_COMMITTED' and 'overheat' in str(event.source_definition_id).lower()
            and ME in (event.target_ids or ())]


def test_furnace_heart_halves_only_the_overheat_self_damage():
    """"Overheat self-damage is reduced by half" -- the augment's own backlash to its user, and nothing else.

    The Fireball is aimed at an enemy 25 feet away, so the caster is outside its 20-foot sphere and the only Fire damage it
    takes is the augment's printed backlash; the enemy inside the Fireball still takes the full area damage, which is what an
    "Overheat self-damage" clause is not."""
    _, plain, plain_me, plain_foe = fight('FIRE_TAL_FIREBALL_ART', foe_at=(8, 6))
    _, engine, me, foe = fight('FIRE_TAL_FIREBALL_ART', FIRE + 'furnace_heart', foe_at=(8, 6))
    cast(engine, 'Furnace Heart')
    cast(plain, 'Fireball Art + Overheat', dest=(8, 6))
    cast(engine, 'Fireball Art + Overheat', dest=(8, 6))
    plain_back, hot_back = backlash_packets(plain), backlash_packets(engine)
    assert [amount for _who, amount in plain_back] == [2 * plain_me.proficiency_bonus], plain_back
    assert [amount for _who, amount in hot_back] == [plain_me.proficiency_bonus], hot_back
    assert [who for who, _amount in hot_back] == [ME]
    assert plain_foe.current_hp == foe.current_hp < 2000, 'the Fireball still burned the enemy it was aimed at'


def test_fire_sovereign_incarnation_removes_the_overheat_self_damage():
    """"Overheat self-damage is reduced to 0" -- the augment's own backlash packet is zero.

    Fire-Sovereign Incarnation also grants its printed Immunity to Fire damage, so this packet would read zero either way;
    :func:`test_furnace_heart_halves_only_the_overheat_self_damage` is what isolates the reduction hook itself (Furnace Heart
    grants no immunity and its hook does halve the same packet)."""
    _, plain, _plain_me, _plain_foe = fight('FIRE_TAL_FIREBALL_ART', foe_at=(8, 6))
    _, engine, me, _foe = fight('FIRE_TAL_FIREBALL_ART', FIRE + 'fire_sovereign_incarnation', foe_at=(8, 6))
    me.maximum_hp = me.current_hp = 400
    cast(engine, 'Fire-Sovereign Incarnation')
    before = me.current_hp
    cast(plain, 'Fireball Art + Overheat', dest=(8, 6))
    cast(engine, 'Fireball Art + Overheat', dest=(8, 6))
    assert backlash_packets(plain), 'the augment hurts without the talent'
    assert backlash_packets(engine) == [(ME, 0)], backlash_packets(engine)
    assert me.current_hp == before, (me.current_hp, before)


# --------------------------------------------------------------------------- the retired reminder lines
RETIRED = {
    'FIRE_TAL_BURNING_WEAPON': [],
    'FIRE_TAL_SCORCHING_RAY_ART': [],
    'FIRE_TAL_FIREBALL_ART': ["Unattended flammable objects ignite."],
    'FIRE_TAL_FLAME_LASH': ["Make a melee or ranged Cultivation Attack."],
    'FIRE_TAL_INCINERATING_LANCE': [],
    FIRE + 'fire_ward': [],
    FIRE + 'explosive_combustion': [],
    FIRE + 'combustive_step': [],
    FIRE + 'white_hot_focus': ["If you use a Fire talent as a Reaction before this Focus ends, resolve its chosen benefit and the Fire self-damage at the table."],
    FIRE + 'furnace_heart': [
        "Furnace Heart ends early if you are Incapacitated or fully submerged in water unless your Fire is spiritual."],
    FIRE + 'fire_sovereign_incarnation': [
        "Use Limit: Once per long rest",
        "Burn damage becomes 2d6 + Proficiency Bonus",
        "once per turn, use Ignite without spending an Action when you reduce a creature to 0 HP or destroy a significant object with Fire damage",
        "ordinary flammable unattended objects ignite when you pass within 5 feet",
        "You cannot benefit from being Hidden while Fire-Sovereign Incarnation is active unless a talent explicitly says otherwise."],
}


@pytest.mark.parametrize('mechanic_id,expected', sorted(RETIRED.items()))
def test_only_the_lines_the_table_still_leaves_to_the_gm_are_reminders(mechanic_id, expected):
    """The retired printed lines are not the GM's to read any more; the ones still listed are, exactly."""
    assert AUTH[mechanic_id]['riders'] == expected, AUTH[mechanic_id]['riders']


def test_a_compiled_fire_fighter_is_offered_no_printed_overheat_reminder():
    """No "Augment - N CP" or Cultivation Level damage line survives on the Fire buttons the table now serves."""
    _, engine, _me, _foe = fight('FIRE_TAL_FIREBALL_ART', 'FIRE_TAL_INCINERATING_LANCE', 'FIRE_TAL_SCORCHING_RAY_ART',
                                 'FIRE_TAL_BURNING_WEAPON', FIRE + 'white_hot_focus')
    shown = set()
    for action in engine.action_catalog.values():
        shown.update(((action.parameters or {}).get('typed') or {}).get('riders') or [])
    assert not [line for line in shown if line.startswith('Augment -') or 'Cultivation Level' in line], sorted(shown)