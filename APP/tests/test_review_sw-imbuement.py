"""Printed-rule regressions for Imbuement, Ink, and Iron Fist."""

import copy
import json
from functools import lru_cache
from pathlib import Path

import pytest

from combat import typed_executor as te, typed_reactions as tr, zones
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent
from combat.gate4_engine import Gate4ControllerEngine
from tests.test_auto_support import ME, _engine
from tests.test_zones import SHEET
from tests.h1_support import script

ROOT = Path(__file__).resolve().parents[1]
AUTH = json.loads((ROOT/'authority/Tianxia_Typed_Mechanics_Authority_R1.json').read_text())['mechanics']
I, K, F = 'tianxia.talent.imbuement.', 'tianxia.talent.ink.', 'TAL_IRON_FIST_'


@lru_cache(maxsize=None)
def _compiled(key, cl=20, dc=50, armed=False, extra=()):
    sphere = AUTH[key]['sphere_id']
    bases = [k for k,v in AUTH.items() if v.get('sphere_id') == sphere and v.get('kind') == 'base_ability']
    kit = [{'starting_kit': {'items': [{'item_id':'tianxia.mortal.weapon.fu','name':'Fu (Short Axe)','quantity':1}]}}] if armed else []
    sheet = {**SHEET, 'equipment':kit,
        'identity': {**SHEET['identity'], 'cultivation_level':cl},
        'ability_scores_and_statistics': {**SHEET['ability_scores_and_statistics'],
            'technique_save_dc':dc, 'technique_attack_bonus':40,
            'primary_resource':{'name':'Qi','maximum':100}},
        'spheres_and_talents': {'sphere_record_ids':[sphere],
            'learned_talent_record_ids':list(dict.fromkeys([*bases,key,*extra]))}}
    return compile_character(sheet, actor_id=ME)


def _fight(key, cl=20, dc=50, armed=False, foe_at=(4,6), extra=()):
    bundle = copy.deepcopy(_compiled(key,cl,dc,armed,extra))
    engine = _engine(bundle,foe_at=foe_at)
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    foe.maximum_hp = foe.current_hp = 2000
    foe.armor_class = -50
    me.resources['resource:core.martial_focus'] = 1
    return bundle,engine,me,foe


def _cast(engine,prefix,contains='',target_id=None):
    candidates = [c for c in engine.legal_candidates() if c.display_name.startswith(prefix) and contains in c.display_name
                  and (target_id is None or target_id in c.target_ids)]
    assert candidates,(prefix,contains)
    pos = engine.state.actors[AN].position
    candidate = min(candidates,key=lambda c:(0 if c.destination is None else abs(c.destination.x-pos.x)+abs(c.destination.y-pos.y),len(c.display_name)))
    engine.execute_intent(ActionIntent(intent_id='review',decision_id=candidate.decision_id,
        candidate_id=candidate.candidate_id,state_version=candidate.state_version,actor_id=ME,
        target_ids=candidate.target_ids,destination=candidate.destination))


def _mark(engine,foe,name='Opened'):
    engine._apply_condition(foe,te.mark_condition_id(name,ME),'test:mark',ME,expires_on='UNTIL_REMOVED',data={'mark':name,'label':name})


def _ally(engine,me):
    ally = me.model_copy(deep=True)
    ally.entity_id = 'actor:review.ally'
    ally.position = me.position.model_copy(update={'y':me.position.y+1})
    engine.state.actors[ally.entity_id] = ally
    return ally


def _rolls(engine,kind):
    return [r for r in engine.rolls if r.reason.startswith(kind)]


def _damage(engine):
    return [r.expression.removesuffix('+0') for r in _rolls(engine,'DAMAGE:')]


def _conditions(actor,name):
    return [c for c in actor.conditions.values() if c.condition_id == 'condition:typed.'+name]


def _saving_die(monkeypatch,value):
    """Choose the save branch while retaining the actual DC and save resolver."""
    original = Gate4ControllerEngine._roll_save

    def roll_save(engine,*args,**kwargs):
        script(engine,[value])
        return original(engine,*args,**kwargs)

    monkeypatch.setattr(Gate4ControllerEngine,'_roll_save',roll_save)


def _assert_iron_save(engine,ability,failed):
    saves = [e.payload for e in engine.events if e.event_type == 'SAVE_ROLLED']
    assert len(saves) == 1
    save = saves[0]
    assert save['reason'].endswith(':'+ability)
    assert save['dc'] == 14  # 8 + PB 4 + chosen Iron Fist ability modifier 2.
    assert save['natural_result'] == (1 if failed else 20)
    assert save['success'] is not failed


# Fray Mandate is one button per Fray option known (rider lane C5: "Choose one Fray talent you know"), so a character needs one.
@pytest.mark.parametrize('key,contains',[(I+'quicken_and_slow','Slow'),(I+'twin_fray','Twin Fray')])
def test_fray_rolls_one_initial_save(key,contains):
    _,engine,me,foe = _fight(key,extra=(I+'quicken_and_slow',I+'suppress_function'))
    _cast(engine,'Fray Mandate',contains)
    assert len(_rolls(engine,'SAVE:')) == 1


@pytest.mark.parametrize('slug,prefix,cost',[
    ('court_of_ten_thousand_mandates','Court of Ten Thousand Mandates',3),
    ('reverse_the_weight_of_heaven','Reverse the Weight of Heaven',5),
    ('unmake_the_king_s_armor','Unmake the King',4),
    ('the_edict_that_names_the_world_again','The Edict That Names the World Again: Weakness',10),
])
def test_fixed_cost_and_printed_rest_limit_are_enforced(slug,prefix,cost):
    _,engine,me,foe = _fight(I+slug)
    before = me.resources['resource:core.qi']
    hp = me.current_hp
    _cast(engine,prefix)
    assert me.resources['resource:core.qi'] == before-cost
    assert me.current_hp == hp
    uses = {k:v for k,v in me.resources.items() if k.startswith('resource:uses.') and slug in k}
    assert uses and all(value == 0 for value in uses.values())


def test_sovereigns_mandate_reaches_beyond_the_old_thirty_feet():
    _,engine,me,foe = _fight(I+'sovereign_of_the_true_name_of_things',foe_at=(12,6),extra=(I+'quicken_and_slow',))
    _cast(engine,'Fray Mandate: Slow')
    assert _rolls(engine,'SAVE:')


def test_edict_blades_damage_waits_for_the_later_weapon_hit():
    _,engine,me,foe = _fight(I+'the_edict_that_names_the_world_again')
    hp = me.current_hp
    _cast(engine,'The Edict That Names the World Again: Blades')
    assert me.current_hp == hp and foe.current_hp == 2000
    assert not _damage(engine)


@pytest.mark.parametrize('cl,dice',[(1,'1d8+2'),(5,'2d8+2'),(11,'3d8+2'),(17,'4d8+2')])
def test_ink_lash_scales(cl,dice):
    _,engine,me,foe = _fight('INK_BASE_INK_LASH',cl=cl)
    _cast(engine,'Ink Lash')
    assert _damage(engine) == [dice]


@pytest.mark.parametrize('cl,dice',[(1,'1d8+2'),(11,'2d8+2'),(17,'3d8+2')])
def test_unmarked_brushstroke_shield_scales_without_the_mark_bonus(cl,dice):
    bundle,engine,me,foe = _fight(K+'brushstroke_shield',cl=cl)
    row = next(r for r in bundle['typed_reactions'] if r.get('feature_id') == K+'brushstroke_shield')
    remaining,_ = tr._generic_damage_reduction(engine,me,row,100,me)
    rolls = [r for r in engine.rolls if r.reason.startswith('GENERIC_AMOUNT:')]
    assert len(rolls) == 1 and rolls[0].expression == dice
    assert remaining == 100-rolls[0].total


def test_base_ink_cloud_is_lightly_obscured():
    _,engine,me,foe = _fight(K+'ink_cloud')
    _cast(engine,'Ink Cloud')
    assert zones.typed_zones(engine)
    assert all(z.trigger_profile.get('obscured') == 'light' for z in zones.typed_zones(engine))


@pytest.mark.parametrize('slug,prefix',[
    ('black_seal_edict','Black-Seal Edict'),('heaven_sealing_writ','Heaven-Sealing Writ'),
    ('ink_domain','Ink Domain'),('ink_doppelganger','Ink Doppelganger'),
    ('scripture_prison','Scripture Prison'),('scripture_wall','Scripture Wall'),
    ('world_as_canvas','World as Canvas'),
])
def test_printed_ink_concentration_is_started_and_ends(slug,prefix):
    _,engine,me,foe = _fight(K+slug)
    _mark(engine,foe,'Ink Mark')
    _cast(engine,prefix)
    assert me.concentration is not None
    engine._end_concentration(me,'test:stop')
    assert me.concentration is None
    assert not zones.typed_zones(engine)


def test_ink_domain_does_not_grant_invisibility_or_escape_advantage():
    _,engine,me,foe = _fight(K+'ink_domain')
    _cast(engine,'Ink Domain')
    assert not _conditions(foe,'invisible')
    assert te.check_mode(me,'STR','Athletics') == 'NORMAL'


def test_ink_copy_statistics_do_not_buff_or_heal_the_caster():
    _,engine,me,foe = _fight(K+'ink_doppelganger')
    ally = _ally(engine,me)
    ally.current_hp -= 5
    hp = ally.current_hp
    _cast(engine,'Ink Doppelganger',target_id=ally.entity_id)
    assert ally.current_hp == hp
    assert not any(m.target_field == 'armor_class' for m in ally.modifiers.values())


def test_scripture_wall_immunity_belongs_to_the_wall():
    _,engine,me,foe = _fight(K+'scripture_wall')
    _cast(engine,'Scripture Wall')
    assert not any(m.target_field == 'damage_immunity' for m in me.modifiers.values())
    assert any(z.trigger_profile['wall']['object']['immune'] == ['POISON','PSYCHIC'] for z in zones.typed_zones(engine))


@pytest.mark.parametrize('cl,dice',[(5,'4d6'),(11,'6d6'),(17,'8d6')])
def test_thousand_brushstrokes_scales(cl,dice):
    _,engine,me,foe = _fight(K+'thousand_brushstrokes',cl=cl)
    _cast(engine,'Thousand Brushstrokes')
    assert _damage(engine) == [dice]


@pytest.mark.parametrize('marked',[True,False])
def test_vermilion_correction_rolls_a_d4_for_an_own_mark(tmp_path, marked):
    # Correction now consumes a real check through d20_bonus, rather than the
    # old generic pending-d20 row. Preserve marked/unmarked and d4 assertions.
    from tests.test_a2_ink import setup, execute_session, CORRECTION, INK
    from tests.r1i_service_support import fixture, candidate, OWNER, FOE
    from tests.test_r1i_round3 import resolve, reload
    from tests.test_auto138_ink import owner_turn
    combat, table, mid, send, commit = fixture(tmp_path, [CORRECTION],
        foe_talents=[INK+'binding_script'], bundle_transform=setup)
    if marked:
        resolve(combat, mid, send, candidate(table, mid, 'Press Mark', FOE),
                {'choice:needle.ink_accept': 'accept'})
    commit(table.state(mid)['menu']['end_turn'])
    owner_turn(table, mid, commit, FOE)
    before, _ = resolve(combat, mid, send, candidate(table, mid, 'Test ability check', OWNER),
                        {'choice:needle.ink_correction': 'subtract'})
    engine = reload(tmp_path, mid)
    rewritten = [e for e in engine.events if e.event_type == 'D20_REWRITTEN'
                 and e.source_definition_id == CORRECTION]
    assert len(rewritten) == int(marked)
    assert not marked or -4 <= rewritten[0].payload['bonus'] <= -1
    assert not getattr(engine, '_typed_roll_outcome', None)
    assert engine.state.actors[OWNER].reaction_available is not marked
    assert sum(before['actors'][OWNER]['resources'].values()) - sum(engine.state.actors[OWNER].resources.values()) == int(marked)
    engine = execute_session(tmp_path, mid, 'Test ability check', OWNER)
    assert len([e for e in engine.events if e.event_type == 'D20_REWRITTEN'
                and e.source_definition_id == CORRECTION]) == int(marked)


def test_paid_breath_extended_strike_reaches_thirty_feet():
    _,engine,me,foe = _fight(F+'BREATH_EXTENDED_STRIKE',foe_at=(9,6))
    _cast(engine,'Unarmed Strike','Breath-Extended Strike')
    assert foe.current_hp < 2000
    assert me.resources['resource:core.martial_focus'] == 0


@pytest.mark.parametrize('dc',[50,-40])
def test_internal_hammer_does_not_impose_disadvantage(dc):
    _,engine,me,foe = _fight(F+'INTERNAL_HAMMER',dc=dc)
    _mark(engine,foe)
    _cast(engine,'Unarmed Strike','Internal Hammer')
    assert _rolls(engine,'SAVE:')
    assert not any(m.target_field == 'attack_mode' and m.value == 'DISADVANTAGE' for m in foe.modifiers.values())


def test_iron_meridian_body_does_not_damage_creatures_with_object_bonus():
    _,engine,me,foe = _fight(F+'IRON_MERIDIAN_BODY')
    _cast(engine,'Unarmed Strike (Iron Fist)')
    assert _damage(engine) == ['2d6+2']
    assert not any(event.event_type == 'DAMAGE_COMMITTED' and event.payload.get('damage_type') == 'UNTYPED'
                   for event in engine.events)


def test_leg_seal_lasts_through_the_targets_next_turn(monkeypatch):
    # fix/attack-ability (R22 merge 6592dcfa) gives Iron Fist its own DC;
    # force the failed saving die, not the unrelated sheet technique DC.
    _saving_die(monkeypatch,1)
    _,engine,me,foe = _fight(F+'MERIDIAN_SEALING_PALM')
    ally = _ally(engine,me)
    engine.state.initiative_order = (ME,AN,ally.entity_id)
    engine.state.current_slot_index = 0
    _mark(engine,foe)
    _cast(engine,'Unarmed Strike','Meridian-Sealing Palm')
    assert len(_rolls(engine,'SAVE:')) == 1
    _assert_iron_save(engine,'CON',True)
    assert me.resources['resource:core.martial_focus'] == 0
    assert engine._effective_speed(foe) == 15
    engine.end_turn()
    assert engine._effective_speed(foe) == 15
    engine.end_turn()
    assert engine._effective_speed(foe) == 30


@pytest.mark.parametrize('slug,prefix,extra',[
    ('NINE_BELL_MERIDIAN_PALM','Nine-Bell Meridian Palm','6d10'),
    ('ONE_INCH_HEAVENQUAKE','One-Inch Heavenquake','4d8'),
    ('SKY_SHATTERING_AXE_KICK','Sky-Shattering Axe Kick','4d6'),
])
@pytest.mark.parametrize('armed,normal',[(False,'2d6+2'),(True,'1d12+2')])
def test_special_strikes_deal_the_characters_unarmed_damage(slug,prefix,extra,armed,normal):
    _,engine,me,foe = _fight(F+slug,armed=armed)
    _cast(engine,prefix)
    assert _damage(engine)[:2] == [normal,extra]
    assert _rolls(engine,'ATTACK:')[0].expression == '1d20+6'


@pytest.mark.parametrize('dc,stunned',[(50,True),(-40,False)])
def test_heavenquake_uses_the_con_save_branch(monkeypatch,dc,stunned):
    # fix/attack-ability (R22 merge 6592dcfa): the Iron Fist ability owns this DC.
    _saving_die(monkeypatch,1 if stunned else 20)
    _,engine,me,foe = _fight(F+'ONE_INCH_HEAVENQUAKE',dc=dc)
    _cast(engine,'One-Inch Heavenquake')
    assert bool(_conditions(foe,'stunned')) is stunned
    assert bool(_conditions(foe,'reaction_denied')) is not stunned
    assert len(_rolls(engine,'SAVE:')) == 1
    _assert_iron_save(engine,'CON',stunned)


@pytest.mark.parametrize('dc,prone,distance',[(50,True,20),(-40,False,5)])
def test_empty_bell_uses_the_strength_save(monkeypatch,dc,prone,distance):
    # fix/attack-ability (R22 merge 6592dcfa): the Iron Fist ability owns this DC.
    _saving_die(monkeypatch,1 if prone else 20)
    _,engine,me,foe = _fight(F+'PALM_THAT_MOVES_THE_EMPTY_BELL',dc=dc)
    start = foe.position
    _cast(engine,'Palm That Moves the Empty Bell')
    assert bool(_conditions(foe,'prone')) is prone
    assert abs(foe.position.x-start.x)*5 == distance
    assert len(_rolls(engine,'SAVE:')) == 1
    _assert_iron_save(engine,'STR',prone)


def test_quivering_gate_places_its_mark_without_releasing_it():
    _,engine,me,foe = _fight(F+'QUIVERING_GATE_STRIKE')
    _cast(engine,'Quivering Gate Strike')
    assert _damage(engine) == ['2d6+2']
    assert te.bears_mark(foe,ME,'Quivering Gate')


def test_rooting_stance_waits_for_a_melee_miss_to_grant_movement():
    _,engine,me,foe = _fight(F+'ROOTING_STANCE')
    _cast(engine,'Rooting Stance')
    assert me.movement_remaining_ft == 30


@pytest.mark.parametrize('dc,prone',[(50,True),(-40,False)])
def test_sky_kick_has_an_attack_then_strength_save(monkeypatch,dc,prone):
    # fix/attack-ability (R22 merge 6592dcfa): the Iron Fist ability owns this DC.
    _saving_die(monkeypatch,1 if prone else 20)
    _,engine,me,foe = _fight(F+'SKY_SHATTERING_AXE_KICK',dc=dc)
    _cast(engine,'Sky-Shattering Axe Kick')
    assert len(_rolls(engine,'ATTACK:')) == len(_rolls(engine,'SAVE:')) == 1
    _assert_iron_save(engine,'STR',prone)
    assert bool(_conditions(foe,'prone')) is prone
    # Iron Fist's normal hit can also Open the target; this talent extends it on failure.
    if prone: assert te.bears_mark(foe,ME,'Opened')
    assert engine._effective_speed(foe) == (30 if prone else 15)


@pytest.mark.parametrize('dc',[50,-40])
def test_thousand_hand_marks_both_branches_and_grants_movement(dc):
    _,engine,me,foe = _fight(F+'THOUSAND_HAND_WAR_BODY',dc=dc)
    _cast(engine,'Thousand-Hand War Body')
    assert te.bears_mark(foe,ME,'Opened')
    assert me.movement_remaining_ft == 45 and me.turn_flags.get('oa_free_ft') == 15


def test_secret_fist_gains_advantage_before_the_hit_not_resistance_after():
    _,engine,me,foe = _fight('tianxia.talent.iron_fist.the_fist_that_taught_heaven_to_flinch')
    _cast(engine,'The Fist That Taught Heaven to Flinch')
    assert _rolls(engine,'ATTACK:')[0].mode == 'ADVANTAGE'
    assert _damage(engine)[:2] == ['2d6+2','12d10']
    assert not any(m.target_field == 'damage_resistance' for m in me.modifiers.values())


@pytest.mark.parametrize('prefix',['Place Mandate'])  # Elemental Dimming (its Fray) is the GM's (rider lane C5)
def test_elemental_mantle_does_not_deal_weapon_bonus_damage_at_cast(prefix):
    _,engine,me,foe = _fight(I+'elemental_mantle')
    hp = me.current_hp
    _cast(engine,prefix)
    assert me.current_hp == hp and foe.current_hp == 2000
    assert not _damage(engine)


def test_living_seal_moves_the_mark_not_the_caster():
    bundle,engine,me,foe = _fight(K+'living_seal_script')
    row = next(r for r in bundle['typed_reactions'] if r.get('feature_id') == K+'living_seal_script')
    tr._run_generic_effects(engine,me,foe,row,row['effects'])
    assert me.movement_remaining_ft == 30 and foe.movement_remaining_ft == 30


def test_empty_hand_structure_bonus_does_not_damage_creatures():
    _,engine,me,foe = _fight(F+'EMPTY_HAND_BREAKS_THE_FORMATION_DOOR',extra=(F+'ONE_INCH_HEAVENQUAKE',))
    _cast(engine,'One-Inch Heavenquake','Empty-Hand Breaks the Formation Door')
    assert '6d8' not in _damage(engine)
    assert _damage(engine) == ['2d6+2','4d8']


# --- AUTO118: Internal Hammer's printed failed-save suppression, and the string-valued effect branch it uses. ---

def _internal_hammer_rows():
    """The rows the compiled Internal Hammer modifier actually runs."""
    return AUTH[F+'INTERNAL_HAMMER']['modifier']['effects'][0]['effects'][0]


def test_internal_hammer_failed_save_runs_the_printed_effect_suppression():
    """Failed Save: choose one ongoing physical or martial effect and suppress it (AUTO118)."""
    fail = _internal_hammer_rows()['on_fail']
    assert [row['type'] for row in fail] == ['end_effect']
    row = fail[0]
    # select "beneficial" is Internal Hammer's stance/guard/body-enhancement case, not a hostile effect.
    assert row['select'] == 'beneficial' and row['applies_to'] == 'target'
    # "until the end of the target's next turn" is the affected creature's own turn.
    assert row['until'] == 'holder' and row['on_success'] == 'suppress'


def test_internal_hammer_never_grants_advantage_on_a_successful_save():
    """The printed text denies the target Advantage; it must never be typed as granting it (AUTO118)."""
    assert all(not effect.get('on_success') for effect in AUTH[F+'INTERNAL_HAMMER']['effects'])
    for dc in (50, -40):
        _, engine, me, foe = _fight(F+'INTERNAL_HAMMER', dc=dc)
        _mark(engine, foe)
        _cast(engine, 'Unarmed Strike', 'Internal Hammer')
        for who in (me, foe):
            assert not [m for m in who.modifiers.values() if m.target_field == 'attack_mode'], dc


def test_effect_walkers_ignore_string_valued_success_branches():
    """end_effect uses on_success="suppress"; the effect walkers must not treat that string as an effect row."""
    from combat.ext.attack_modifiers import damage_types, description
    from combat.ext.paid_hit import effect_text

    row = {'type': 'save', 'ability': 'con', 'on_fail': [{'type': 'end_effect', 'applies_to': 'target',
           'select': 'beneficial', 'on_success': 'suppress', 'until': 'holder',
           'evidence': 'Choose one ongoing physical or martial effect...'}], 'on_success': []}
    assert damage_types([row]) == []
    assert 'Choose one ongoing physical or martial effect' in description([{'effects': [row]}])
    text = effect_text([row])
    assert 'Failed save: Choose one ongoing physical or martial effect' in text
    # An empty branch adds no bare "Successful save: " label.
    assert 'Successful save:' not in text


# --- AUTO118r1f1: Internal Hammer's suppression at the table, with persistence and expiry. ---

HAMMER = F + 'INTERNAL_HAMMER'
SOVEREIGN = F + 'SOVEREIGN_IRON_BODY_INCARNATION'
ENEMY = 'actor:review.sovereign'


def _iron_sheet(talents, *, cl, dc):
    """An Iron Fist fighter owning exactly ``talents``; ``dc`` is its own Cultivation Save DC, so a foe has to beat it."""
    sphere = AUTH[HAMMER]['sphere_id']
    bases = [k for k, v in AUTH.items() if v.get('sphere_id') == sphere and v.get('kind') == 'base_ability']
    return {**SHEET, 'equipment': [{'starting_kit': {'items': [{'item_id': 'tianxia.mortal.weapon.fu',
                                                              'name': 'Fu (Short Axe)', 'quantity': 1}]}}],
            'identity': {**SHEET['identity'], 'cultivation_level': cl},
            'ability_scores_and_statistics': {**SHEET['ability_scores_and_statistics'],
                'technique_save_dc': dc, 'technique_attack_bonus': 40,
                'primary_resource': {'name': 'Qi', 'maximum': 100}},
            'spheres_and_talents': {'sphere_record_ids': [sphere],
                'learned_talent_record_ids': list(dict.fromkeys([*bases, *talents]))}}


def _scripted_dice(monkeypatch, session, values):
    """The next 20-sided dice of one transaction come from ``values``, then the seeded roller carries on.

    A natural 1 on an attack roll always misses (combat/critical_attacks.hits), which would leave this test
    asserting nothing, and the table service previews a transaction on its own cloned engine before committing
    it -- so the roller's *class* is scripted and the queue restarts whenever a roller begins at the counter the
    transaction starts from. The preview and the commit therefore roll exactly the same dice. Dice only: no rule,
    state, event or service function is replaced.
    """
    from combat.gate2_rolls import DeterministicRollAuthority

    original = DeterministicRollAuthority._die
    queue = list(values)
    start = int(session.engine.state.roll_counter)

    def _die(self, sides):
        if self.counter == start:
            queue[:] = values
        if sides == 20 and queue:
            counter = self.counter
            self.counter += 1
            return min(int(queue.pop(0)), sides), counter
        return original(self, sides)

    monkeypatch.setattr(DeterministicRollAuthority, '_die', _die)


def _hammer_table(tmp_path, control, *, enemy_talents=(SOVEREIGN,), enemy_cl=15, source_category=None):
    """A real table: this character with Internal Hammer against a foe that can maintain its own body enhancement."""
    from combat.gate5_service import CombatService

    mine = compile_character(_iron_sheet([HAMMER], cl=20, dc=40), actor_id=ME)
    setup = copy.deepcopy(next(a for a in mine['action_catalog'] if a['display_name'] == 'Unarmed Strike (Iron Fist)'))
    setup['source_definition_id'] += ':test_prepare'
    setup['display_name'] = 'Test prepare Opened target'
    setup['parameters']['typed']['effects'] = [{'type': 'mark', 'mark': 'Opened', 'applies_to': 'target',
                                               'duration': {'kind': 'until_removed'}}]
    mine['action_catalog'].append(setup)
    mine['actor_template']['action_ids'].append(setup['source_definition_id'])
    theirs = compile_character(_iron_sheet(list(enemy_talents), cl=enemy_cl, dc=16), actor_id=ENEMY)
    if source_category:
        action = next(a for a in theirs['action_catalog'] if a['display_name'] == 'Sovereign Iron-Body Incarnation')
        typed = action['parameters']['typed']
        typed['source_category'] = source_category
        if source_category == 'unclassified ordinary magic':
            for effect in typed['effects']:
                effect.pop('bodily_martial_effect', None)
        if source_category == 'permanent transformation':
            typed['duration'] = {'kind': 'permanent'}
        if source_category == 'unknown source':
            typed['source'] = 'fixture:unknown'
    theirs['actor_template']['maximum_hp'] = 400  # the strike lands; the save is the point
    for action in mine['action_catalog']:  # a real strike, not a fixture attack roll
        if action['display_name'].startswith('Unarmed Strike') and action['parameters'].get('typed'):
            action['parameters']['typed']['numbers']['attack_bonus'] = 100
    service = CombatService(ROOT, tmp_path)
    session = service.persistence.create_match(
        match_seed='HAMMER', maximum_rounds=20,
        typed_bundles=(mine, theirs),
        roster_setup={'primary_actor_ids': [ME, ENEMY], 'team_by_actor': {ME: 'team:a', ENEMY: 'team:b'},
                      'starting_positions': {ME: {'x': 3, 'y': 6}, ENEMY: {'x': 4, 'y': 6}}})
    metadata = {'participant_control_modes': {ME: 'MANUAL', ENEMY: 'MANUAL'}}
    return service, session, metadata


def _advance_to(service, session, metadata, who):
    """Commit real "End turn" Actions until ``who`` is the creature whose turn it is."""
    from tests.test_riders_c8_review import service_commit

    for _ in range(12):
        if session.engine.state.current_actor_id == who:
            return
        service_commit(service, session, metadata, 'End turn')
    raise AssertionError(f'{who} never came up')


def _prepare_hammer(service, session, metadata):
    """Persist setup through a typed action, never an out-of-transaction event."""
    from tests.test_riders_c8_review import service_commit
    _advance_to(service, session, metadata, ME)
    service_commit(service, session, metadata, 'Test prepare Opened target', ENEMY)
    service_commit(service, session, metadata, 'End turn')
    _advance_to(service, session, metadata, ME)
    assert session.engine.state.actors[ME].resources['resource:core.martial_focus'] == 1


@pytest.mark.parametrize('control', ['MANUAL', 'LOCAL_AUTO'])
def test_internal_hammer_suppresses_a_real_temporary_martial_effect_through_a_commit_and_reload(tmp_path, control, monkeypatch):
    """Failed Save: choose one ongoing physical or martial effect and suppress it until the end of its next turn."""
    from combat import typed_reactions
    from combat.ext.end_effect import SUPPRESSED_FLAG
    from tests.test_riders_c8_review import service_commit

    service, session, metadata = _hammer_table(tmp_path, control)
    me = session.engine.state.actors[ME]
    foe = session.engine.state.actors[ENEMY]

    # The foe really maintains Sovereign Iron-Body Incarnation for one minute before it is ever struck.
    _advance_to(service, session, metadata, ENEMY)
    service_commit(service, session, metadata, 'Sovereign Iron-Body Incarnation')
    resistances = [k for k, m in foe.modifiers.items() if m.target_field == 'damage_resistance']
    assert len(resistances) > 1, 'the foe must really bear a Resistance for this test to mean anything'
    assert typed_reactions.resists(session.engine, foe, 'BLUDGEONING', None)
    service_commit(service, session, metadata, 'End turn')

    _prepare_hammer(service, session, metadata)

    def choose(context):
        if context.reaction_source_id.endswith('end_effect'):
            assert context.reactor_id == ME, context.reactor_id
            assert 'Internal Hammer' in context.choice_trigger['prompt']
            assert foe.display_name in context.choice_trigger['prompt']
            # "Choose one ongoing physical or martial effect affecting the target": pick the Resistance.
            options = [option for option in context.extension_choice.option_ids if option in resistances]
            return options[:1] or context.extension_choice.option_ids[:1]
        spec = context.extension_choice
        return spec.option_ids[:spec.minimum_selections] if spec and not spec.allow_decline else ()

    metadata['participant_control_modes'][ME] = control
    _scripted_dice(monkeypatch, session, [20, 1])  # the strike lands, then the target's Constitution save fails
    events, prompts, _ = service_commit(service, session, metadata, 'Unarmed Strike (Iron Fist) + Internal Hammer', ENEMY, choose=choose)
    save = [e for e in events if e.event_type == 'SAVE_ROLLED' and e.actor_id == ENEMY]
    assert save and not save[-1].payload['success'], [(e.event_type, str(e.payload)[:160]) for e in events]
    # The printed choice is asked of a manual player; an AI actor decides it with no prompt.
    assert bool(prompts) is (control == 'MANUAL'), (control, [p.reaction_source_id for p in prompts])
    # "Choose one": exactly one of the enhancements stops working, and it is the one chosen.
    row = foe.turn_flags[SUPPRESSED_FLAG][0]
    assert row['kind'] in ('modifier', 'condition'), row
    chosen = row['key']
    if row['kind'] == 'modifier':
        item = foe.modifiers[chosen]
        assert item.target_field.startswith('suppressed:'), item.target_field
        assert not typed_reactions.resists(session.engine, foe, str(item.value).upper(), None), 'the chosen benefit still works'
    else:
        assert foe.conditions[chosen].condition_id.startswith('condition:typed.suppressed.')
    if control == 'MANUAL':  # the fixture asked for the Bludgeoning Resistance by name
        assert chosen in resistances and str(foe.modifiers[chosen].value).upper() == 'BLUDGEONING', chosen
        assert typed_reactions.resists(session.engine, foe, 'FORCE', None), 'only the chosen one is suppressed'

    session = service.persistence.load_match(session.match_id)
    assert session.verify()['status'] == 'PASS'
    foe = session.engine.state.actors[ENEMY]
    live = foe.modifiers if row['kind'] == 'modifier' else foe.conditions
    assert 'suppressed' in (live[chosen].target_field if row['kind'] == 'modifier' else live[chosen].condition_id), \
        'the suppression must survive a commit and a reload'
    if row['kind'] == 'modifier':
        assert not typed_reactions.resists(session.engine, foe, str(live[chosen].value).upper(), None)

    _advance_to(service, session, metadata, ENEMY)
    assert 'suppressed' in (live[chosen].target_field if row['kind'] == 'modifier' else live[chosen].condition_id), \
        'its next turn has not ended yet'
    service_commit(service, session, metadata, 'End turn')
    session = service.persistence.load_match(session.match_id)
    assert session.verify()['status'] == 'PASS'
    foe = session.engine.state.actors[ENEMY]
    live = foe.modifiers if row['kind'] == 'modifier' else foe.conditions
    assert (live[chosen].target_field if row['kind'] == 'modifier' else live[chosen].condition_id) == row['original'], \
        'the original benefit returns at the end of its next turn'
    assert not foe.turn_flags.get(SUPPRESSED_FLAG)
    if row['kind'] == 'modifier':
        assert typed_reactions.resists(session.engine, foe, str(live[chosen].value).upper(), None), 'and it works again'


@pytest.mark.parametrize('source', ['unknown source', 'permanent transformation'])
def test_internal_hammer_leaves_an_unreadable_or_permanent_effect_to_the_gm(tmp_path, source, monkeypatch):
    """Its own rider: no Domains, Secret Inheritances, permanent transformations or unattributable effects."""
    from combat.ext.end_effect import SUPPRESSED_FLAG

    service, session, metadata = _hammer_table(tmp_path, 'MANUAL', source_category=source)
    me = session.engine.state.actors[ME]
    foe = session.engine.state.actors[ENEMY]
    _advance_to(service, session, metadata, ENEMY)
    from tests.test_riders_c8_review import service_commit
    service_commit(service, session, metadata, 'Sovereign Iron-Body Incarnation')
    service_commit(service, session, metadata, 'End turn')
    _prepare_hammer(service, session, metadata)
    _scripted_dice(monkeypatch, session, [20, 1])  # the strike lands, then the target's Constitution save fails
    events, prompts, _ = service_commit(service, session, metadata, 'Unarmed Strike (Iron Fist) + Internal Hammer', ENEMY)
    assert [e for e in events if e.event_type == 'SAVE_ROLLED' and e.actor_id == ENEMY]
    # Nothing the table can read is eligible, so nothing is suppressed and the GM is asked instead.
    assert all('suppressed' not in m.target_field for m in foe.modifiers.values())
    assert not foe.turn_flags.get(SUPPRESSED_FLAG)
    riders = [e.payload['rider'] for e in events if e.event_type == 'GM_RIDER']
    if source == 'permanent transformation':
        assert any('it needs one that is an ongoing physical or martial effect' in rider for rider in riders), riders
    else:  # a source the table cannot read stays the GM's decision
        assert any('ongoing physical or martial effect of that creature' in rider for rider in riders), riders
    assert service.persistence.load_match(session.match_id).verify()['status'] == 'PASS'
