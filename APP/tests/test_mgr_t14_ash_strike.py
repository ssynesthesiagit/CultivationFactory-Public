"""Whole Strike parent through compiled ownership, table consent, cold replay."""
import pytest

from combat.factory_compiler import compile_character
from combat.canonical import canonical_sha256
from tests.h1_support import sheet
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, turn, reload
from tests.test_a2_foundations3 import add_action

PREFIX = 'foundation.red_lotus_ash_returning_v0_2B.'
STRIKE = PREFIX + 'ash_returning_strike'
POOL = 'resource:foundation.funeral_ash'


def setup(tmp_path, *, initial=1, owned=True, wounded=True, modifier=-1, cl=1,
          stage='Awakened', healer_cl=1, protection=None, wound_amount=30,
          foe_talents=(), foe_position=None, attack_bonus=100, owner_talents=(), foe_ac=None, owner_kit=None, healer_authority=None, friendly_fire=False):
    doc = sheet([*([STRIKE] if owned else []), 'FIRE_BASE_IGNITE', *owner_talents], cl=cl, name='Wren',
                score=10 + 2 * modifier, kit=owner_kit,
                foundation={'foundation_id': 'red_lotus_ash_returning_v0_2B', 'stage': stage,
                            'resource': {'name': 'Funeral Ash', 'resource_id': 'tianxia.resource.test',
                                         'maximum': 1, 'current': initial}})
    doc['identity']['proficiency_bonus'] = 2
    doc['ability_scores_and_statistics']['technique_attack_bonus'] = attack_bonus
    bundle = compile_character(doc, actor_id=OWNER, reaction_plan={'ask': True})
    def controls(bundles):
        if healer_authority is not None:
            bundles[2] = compile_character(
                sheet(['LIFE_BASE_MEND_THE_PULSE', *foe_talents], cl=healer_cl, name='Mara'),
                actor_id=FOE, typed_authority=healer_authority, reaction_plan={'ask': True})
        add_action(bundles[1], 'Wound target', [{'type':'damage', 'flat':wound_amount,
                   'damage_types':['force'], 'applies_to':'target'}], economy='NONE')
        add_action(bundles[0], 'Unaligned hit', [{'type':'attack', 'attack_kind':'weapon',
                   'on_hit':[{'type':'damage', 'flat':1, 'damage_types':['force']}]}], bonus=100)
        add_action(bundles[2], 'Unknown-authority recovery', [{'type':'healing', 'flat':5,
                   'applies_to':'self'}], target_kind='SELF', economy='NONE')
        if protection:
            add_action(bundles[1], 'Protect target', [protection], target_kind='ANY_CREATURE', economy='NONE')
        if friendly_fire:
            # Broaden only this fixture's target domain so a real native hit
            # exercises the Foundation's hostility guard, not the menu's gate.
            for action in bundles[0]['action_catalog']:
                if (action.get('parameters', {}).get('typed') or {}).get('source') == 'FIRE_BASE_IGNITE':
                    action['target_kind'] = 'ANY_CREATURE'
            bundles[0].pop('bundle_sha256', None)
            bundles[0]['bundle_sha256'] = canonical_sha256(bundles[0])
        if foe_ac is not None:
            bundles[2]['actor_template']['armor_class'] = foe_ac
            bundles[2].pop('bundle_sha256', None)
            bundles[2]['bundle_sha256'] = canonical_sha256(bundles[2])
    combat, table, mid = fixture(tmp_path, [], cl=cl, owner_bundle=bundle,
                                bundle_transform=controls, named=True, seed='MGR-T14-STRIKE',
                                foe_sheet=sheet(['LIFE_BASE_MEND_THE_PULSE', *foe_talents], cl=healer_cl, name='Mara'),
                                foe_position=foe_position)
    if wounded:
        turn(table, mid, ALLY)
        settle(table, mid, candidate(combat, mid, 'Wound target', target=FOE).candidate_id)
        if protection:
            settle(table, mid, candidate(combat, mid, 'Protect target', target=FOE).candidate_id)
        turn(table, mid, OWNER)
    return combat, table, mid


def strike(combat, table, mid, dtype='fire'):
    return settle(table, mid, candidate(combat, mid, 'Ignite: Increase Burn Damage', target=FOE).candidate_id,
                  # Unspecified GM facts stay unknown; do not silently certify
                  # battlefield residue and regenerate the Ash just spent.
                  choices={'choice:needle.ash_strike': dtype,
                         'choice:needle.attack_modifier': ('first', 'first', dtype)})


def packets(engine):
    return [e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED'
            and (e.payload.get('display_source_id') or e.source_definition_id) == STRIKE]


@pytest.mark.parametrize('dtype', ['fire', 'necrotic', 'poison', 'slashing'])
def test_signed_total_player_palette_payment_and_reload(tmp_path, dtype):
    combat, table, mid = setup(tmp_path)
    prompts = strike(combat, table, mid, dtype)
    engine = reload(tmp_path, mid)
    delivered = packets(engine)
    assert len(delivered) == 1
    assert delivered[0].payload['hp_damage'] == 1
    assert delivered[0].payload['damage_type'].lower() == dtype
    assert engine.state.actors[OWNER].resources[POOL] == 0
    assert any('Ash-Returning Strike' in str(p) for p in prompts)
    assert len([e for e in engine.events if e.event_type == 'RESOURCE_SPENT'
                and e.source_definition_id == STRIKE]) == 1


@pytest.mark.parametrize('owned,initial,wounded', [(False,1,True), (True,0,True), (True,1,False)])
def test_negative_ownership_cost_and_full_hp(tmp_path, owned, initial, wounded):
    combat, table, mid = setup(tmp_path, owned=owned, initial=initial, wounded=wounded)
    prompts = strike(combat, table, mid)
    engine = reload(tmp_path, mid)
    assert not packets(engine)
    assert not any('choice:needle.ash_strike' in str(p) for p in prompts)


def test_decline_and_repeat_preview_are_pure(tmp_path):
    combat, table, mid = setup(tmp_path)
    before = canonical_sha256(reload(tmp_path, mid).state.model_dump(mode='json'))
    for _ in range(2):
        candidate(combat, mid, 'Ignite: Increase Burn Damage', target=FOE)
    assert canonical_sha256(reload(tmp_path, mid).state.model_dump(mode='json')) == before
    strike(combat, table, mid, None)
    engine = reload(tmp_path, mid)
    assert not packets(engine)
    assert engine.state.actors[OWNER].resources[POOL] == 1


def test_healing_denied_until_source_next_start(tmp_path):
    combat, table, mid = setup(tmp_path)
    strike(combat, table, mid, 'slashing')
    engine = reload(tmp_path, mid)
    assert any(c.condition_id == 'condition:typed.foundations3_ash_healing_denied'
               for c in engine.state.actors[FOE].conditions.values())
    turn(table, mid, FOE)
    before = reload(tmp_path, mid).state.actors[FOE].current_hp
    settle(table, mid, candidate(combat, mid, 'Mend the Pulse', target=FOE).candidate_id)
    assert reload(tmp_path, mid).state.actors[FOE].current_hp == before
    turn(table, mid, OWNER)
    assert not any(c.condition_id == 'condition:typed.foundations3_ash_healing_denied'
                   for c in reload(tmp_path, mid).state.actors[FOE].conditions.values())
    turn(table, mid, FOE)
    before = reload(tmp_path, mid).state.actors[FOE].current_hp
    settle(table, mid, candidate(combat, mid, 'Mend the Pulse', target=FOE).candidate_id)
    assert reload(tmp_path, mid).state.actors[FOE].current_hp > before


@pytest.mark.parametrize('exception', ['higher_realm', 'explicit_immunity'])
def test_native_healing_exception(tmp_path, exception):
    protection = ({'type': 'immunity', 'applies_to': 'target',
                   'conditions': ['foundations3_ash_healing_denied'], 'duration': 'one_minute'}
                  if exception == 'explicit_immunity' else None)
    combat, table, mid = setup(tmp_path, healer_cl=5 if exception == 'higher_realm' else 1,
                               protection=protection)
    strike(combat, table, mid, 'slashing')
    if exception == 'explicit_immunity':
        assert not any(c.condition_id == 'condition:typed.foundations3_ash_healing_denied'
                       for c in reload(tmp_path, mid).state.actors[FOE].conditions.values())
    turn(table, mid, FOE)
    before = reload(tmp_path, mid).state.actors[FOE].current_hp
    settle(table, mid, candidate(combat, mid, 'Mend the Pulse', target=FOE).candidate_id)
    assert reload(tmp_path, mid).state.actors[FOE].current_hp > before


def test_immunity_requires_actual_additional_damage_for_denial(tmp_path):
    combat, table, mid = setup(tmp_path, protection={'type':'immunity', 'applies_to':'target',
                                 'damage_types':['fire'], 'duration':'one_minute'})
    strike(combat, table, mid, 'fire')
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[POOL] == 0
    assert all(e.payload['hp_damage'] == 0 for e in packets(engine))
    assert not any(c.condition_id == 'condition:typed.foundations3_ash_healing_denied'
                   for c in engine.state.actors[FOE].conditions.values())


def test_refined_heart_ash_one_paid_numeric_value(tmp_path):
    combat, table, mid = setup(tmp_path, stage='Refined')
    strike(combat, table, mid, 'poison')
    engine = reload(tmp_path, mid)
    assert len(packets(engine)) == 1
    assert packets(engine)[0].payload['hp_damage'] == 3
    assert len([e for e in engine.events if e.event_type == 'RESOURCE_SPENT'
                and e.source_definition_id == STRIKE]) == 1


def test_negative_total_clamps_once_and_cannot_deny_healing(tmp_path):
    combat, table, mid = setup(tmp_path, modifier=-4)
    strike(combat, table, mid, 'necrotic')
    engine = reload(tmp_path, mid)
    assert all(e.payload['hp_damage'] == 0 for e in packets(engine))
    assert not any(c.condition_id == 'condition:typed.foundations3_ash_healing_denied'
                   for c in engine.state.actors[FOE].conditions.values())


def test_automatic_actor_resolves_paid_choice_without_model_or_prompt(tmp_path):
    from tests.hunt36_support import send
    combat, table, mid = setup(tmp_path)
    cid = candidate(combat, mid, 'Ignite: Increase Burn Damage', target=FOE).candidate_id
    prompts = send(combat, table, mid, cid, ai=True)
    engine = reload(tmp_path, mid)
    assert len(packets(engine)) == 1
    assert packets(engine)[0].payload['hp_damage'] == 1
    assert not any('choice:needle.ash_strike' in str(p) for p in prompts)


def test_native_pending_choice_cannot_pay_or_damage_before_commit(tmp_path):
    from tests.test_r9i_karma_persistence import act
    combat, table, mid = setup(tmp_path)
    cid = candidate(combat, mid, 'Ignite: Increase Burn Damage', target=FOE).candidate_id
    before = canonical_sha256(reload(tmp_path, mid).state.model_dump(mode='json'))
    for _ in range(2):
        result = act(table, mid, cid)
        assert result['status'] == 'REACTION_REQUIRED'
        assert canonical_sha256(reload(tmp_path, mid).state.model_dump(mode='json')) == before
        assert [o['id'] for o in result['reaction']['choice']['options']] == [
            'fire', 'necrotic', 'poison', 'slashing']
    strike(combat, table, mid, None)
    assert reload(tmp_path, mid).state.actors[OWNER].resources[POOL] == 1


def test_unreviewed_hit_source_cannot_spend_or_deny_healing(tmp_path):
    combat, table, mid = setup(tmp_path)
    settle(table, mid, candidate(combat, mid, 'Unaligned hit', target=FOE).candidate_id)
    engine = reload(tmp_path, mid)
    assert any(e.event_type == 'ATTACK_ROLLED' and e.payload['provisional_hit'] for e in engine.events)
    assert not packets(engine)
    assert engine.state.actors[OWNER].resources[POOL] == 1
    receipt = next(e for e in reversed(engine.events)
                   if e.payload.get('trigger') == 'foundation_hit_settled')
    assert receipt.payload['alignment'] == 'unknown'


def test_exact_half_hp_after_actual_additional_damage_does_not_deny_healing(tmp_path):
    combat, table, mid = setup(tmp_path, wound_amount=29,
        protection={'type':'immunity', 'applies_to':'target', 'damage_types':['fire'], 'duration':'one_minute'})
    strike(combat, table, mid, 'slashing')
    engine = reload(tmp_path, mid)
    assert len(packets(engine)) == 1 and packets(engine)[0].payload['hp_damage'] == 1
    assert engine.state.actors[FOE].current_hp * 2 == engine.state.actors[FOE].maximum_hp
    assert not any(c.condition_id == 'condition:typed.foundations3_ash_healing_denied'
                   for c in engine.state.actors[FOE].conditions.values())


def test_ash_from_native_retaliation_cannot_pay_the_generating_hit(tmp_path):
    import copy
    import json
    from combat.factory_compiler import TYPED_AUTHORITY
    ward = 'tianxia.talent.fire.fire_ward'
    authority = copy.deepcopy(json.loads(TYPED_AUTHORITY.read_text()))
    # Exercise the printed self-protection branch with a short, synthetic
    # trigger. Public CI transforms long trigger prose, not mechanical rows.
    authority['mechanics'][ward]['activation']['trigger'] = 'You take damage'
    combat, table, mid = setup(tmp_path, initial=0, foe_talents=[ward],
                               foe_position={'x':3, 'y':5}, healer_authority=authority)
    prompts = settle(table, mid, candidate(combat, mid, 'Ignite: Increase Burn Damage', target=FOE).candidate_id,
        picks={'reaction:typed.' + ward: 'first'})
    engine = reload(tmp_path, mid)
    assert any(e.event_type == 'DAMAGE_COMMITTED' and OWNER in e.target_ids
               and e.actor_id == FOE for e in engine.events), prompts
    assert engine.state.actors[OWNER].resources[POOL] == 1
    assert not packets(engine)
    assert not any(e.event_type == 'RESOURCE_SPENT' and e.source_definition_id == STRIKE
                   for e in engine.events)


def test_public_source_and_paid_receipts_have_native_provenance(tmp_path):
    from combat.ext.foundation_paid import settled_hit_receipt
    combat, table, mid = setup(tmp_path)
    strike(combat, table, mid, 'slashing')
    engine = reload(tmp_path, mid)
    attack = next(e for e in reversed(engine.events) if e.event_type == 'ATTACK_ROLLED')
    receipt = settled_hit_receipt(engine, OWNER, attack.payload['roll_id'], 'ash')
    assert receipt and receipt.source_definition_id == attack.source_definition_id
    assert receipt.target_ids == (FOE,)
    assert receipt.payload['qualifies'] == receipt.payload['prior_ash'] == 1
    assert receipt.payload['alignment'] == 'ash'
    paid = next(e for e in engine.events if e.source_definition_id == STRIKE
                and e.payload.get('trigger') == 'paid Foundation hit')
    payment = next(e for e in engine.events if e.sequence == paid.payload['payment_sequence'])
    assert payment.event_type == 'RESOURCE_SPENT'
    assert payment.payload['resource_id'] == POOL and payment.payload['amount'] == 1
    assert paid.payload['roll_id'] == attack.payload['roll_id']
    assert paid.payload['actual_damage'] == 1
    assert attack.sequence < receipt.sequence < payment.sequence < paid.sequence


@pytest.mark.parametrize('relation', ['ALLY', 'NEUTRAL'])
def test_native_diplomacy_is_not_guessed_from_different_teams(tmp_path, relation):
    combat, table, mid = setup(tmp_path, friendly_fire=True)
    engine = reload(tmp_path, mid)
    combat.change_relations(mid, change={'kind':'ACTOR_RELATION', 'subject':OWNER,
                           'other':FOE, 'relation':relation},
                           expected_state_version=engine.state.state_version)
    engine = reload(tmp_path, mid)
    hits = [c for c in engine.legal_candidates()
            if engine.action_catalog.get(c.source_definition_id)
            and engine.action_catalog[c.source_definition_id].display_name == 'Ignite: Increase Burn Damage'
            and c.target_ids == (FOE,)]
    assert hits, 'The native target domain must admit the tested friendly-fire hit'
    settle(table, mid, hits[0].candidate_id)
    assert any(e.event_type == 'ATTACK_ROLLED' and e.payload['provisional_hit']
               for e in reload(tmp_path, mid).events)
    engine = reload(tmp_path, mid)
    assert not packets(engine)
    assert engine.state.actors[OWNER].resources[POOL] == 1


@pytest.mark.parametrize('hit', [True, False])
def test_explicit_variant_defers_payment_and_preserves_the_option(tmp_path, hit):
    combat, table, mid = setup(tmp_path, attack_bonus=100 if hit else -100)
    source = candidate(combat, mid, 'Ignite: Increase Burn Damage', target=FOE).source_definition_id
    engine = reload(tmp_path, mid)
    toggle = next(a for a in engine.action_catalog.values()
                  if (s := a.parameters.get('attack_modifier_setting') or {}).get('family') == source
                  and s.get('modifier') == STRIKE and s.get('field') == 'on')
    # Human variants obey their persistent toggle. Enable via the public menu,
    # then verify the full variant route rather than bypassing its setting.
    settle(table, mid, next(c.candidate_id for c in engine.legal_candidates()
                           if c.source_definition_id == toggle.source_definition_id))
    engine = reload(tmp_path, mid)
    variants = [c for c in engine.legal_candidates() if c.target_ids == (FOE,)
                and engine.action_catalog.get(c.source_definition_id)
                and engine.action_catalog[c.source_definition_id].parameters.get('typed', {}).get('ash_strike_declared')
                and engine.action_catalog[c.source_definition_id].display_name.startswith('Ignite: Increase Burn Damage +')]
    assert variants, 'The complete-menu modifier variant remains reachable'
    settle(table, mid, variants[0].candidate_id, choices={'choice:needle.ash_strike':'poison'})
    engine = reload(tmp_path, mid)
    spends = [e for e in engine.events if e.event_type == 'RESOURCE_SPENT'
              and e.payload['resource_id'] == POOL]
    if hit:
        assert len(packets(engine)) == len(spends) == 1
        assert packets(engine)[0].payload['damage_type'] == 'POISON'
        roll = next(e for e in engine.events if e.event_type == 'ATTACK_ROLLED')
        assert roll.sequence < spends[0].sequence
    else:
        assert not packets(engine) and not spends
        assert engine.state.actors[OWNER].resources[POOL] == 1


def test_positive_key_is_one_packet_not_two_fragments(tmp_path):
    combat, table, mid = setup(tmp_path, modifier=2)
    strike(combat, table, mid, 'necrotic')
    delivered = packets(reload(tmp_path, mid))
    assert len(delivered) == 1
    assert delivered[0].payload['hp_damage'] == 4


@pytest.mark.parametrize('enabled,ask', [(False,False), (True,False), (True,True)])
def test_native_persistent_modifier_settings_and_ask_me(tmp_path, enabled, ask):
    combat, table, mid = setup(tmp_path)
    source = candidate(combat, mid, 'Ignite: Increase Burn Damage', target=FOE).source_definition_id
    choices = [('option','0'), ('payment','0'), ('damage','ask' if ask else 'poison')]
    if enabled:
        choices.insert(0, ('on','toggle'))
    for field, value in choices:
        engine = reload(tmp_path, mid)
        action = next(a for a in engine.action_catalog.values()
                      if (a.parameters.get('attack_modifier_setting') or {}).get('family') == source
                      and (a.parameters.get('attack_modifier_setting') or {}).get('modifier') == STRIKE
                      and (a.parameters.get('attack_modifier_setting') or {}).get('field') == field
                      and (a.parameters.get('attack_modifier_setting') or {}).get('value') == value)
        cid = next(c.candidate_id for c in engine.legal_candidates()
                   if c.source_definition_id == action.source_definition_id)
        settle(table, mid, cid)
        assert reload(tmp_path, mid).state.actors[OWNER].resources[POOL] == 1
    prompts = settle(table, mid, candidate(combat, mid, 'Ignite: Increase Burn Damage', target=FOE).candidate_id,
                      choices={'choice:needle.attack_modifier':'slashing'})
    engine = reload(tmp_path, mid)
    if enabled:
        assert len(packets(engine)) == 1
        assert packets(engine)[0].payload['damage_type'] == ('SLASHING' if ask else 'POISON')
        modifier_prompts = [p for p in prompts
                            if p['context']['reaction_source_id'] == 'choice:needle.attack_modifier']
        assert bool(modifier_prompts) == ask
        assert engine.state.actors[OWNER].resources[POOL] == 0
    else:
        assert not packets(engine) and not prompts
        assert engine.state.actors[OWNER].resources[POOL] == 1


@pytest.mark.parametrize('configured', [False, True])
def test_triggering_hit_that_knocks_target_down_still_has_paid_choice(tmp_path, configured):
    combat, table, mid = setup(tmp_path, wound_amount=54, foe_position={'x':5,'y':5})
    source = candidate(combat, mid, 'Ignite: Increase Burn Damage', target=FOE).source_definition_id
    if configured:
        for field, value in [('on','toggle'), ('option','0'), ('payment','0'), ('damage','poison')]:
            engine = reload(tmp_path, mid)
            action = next(a for a in engine.action_catalog.values()
                if (s := a.parameters.get('attack_modifier_setting') or {}).get('family') == source
                and s.get('modifier') == STRIKE and s.get('field') == field and s.get('value') == value)
            cid = next(c.candidate_id for c in engine.legal_candidates() if c.source_definition_id == action.source_definition_id)
            settle(table, mid, cid)
    strike(combat, table, mid, 'poison')
    engine = reload(tmp_path, mid)
    assert engine.state.actors[FOE].current_hp == 0
    assert len(packets(engine)) == 1
    assert packets(engine)[0].payload['hp_before'] == 0
    assert engine.state.actors[OWNER].resources[POOL] == 0
    assert any(c.condition_id == 'condition:typed.foundations3_ash_healing_denied'
               for c in engine.state.actors[FOE].conditions.values())


def test_prompt_names_the_actual_ability_action_creature_and_cost(tmp_path):
    combat, table, mid = setup(tmp_path)
    prompts = strike(combat, table, mid, 'slashing')
    prompt = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.ash_strike')
    text = prompt['moment']
    assert 'Ash-Returning Strike' in text and 'Ignite: Increase Burn Damage' in text
    assert 'Mara' in text and '1 Funeral Ash' in text
    assert 'next turn' in text and 'half' in text


def test_unknown_healing_source_does_not_borrow_the_healers_realm(tmp_path):
    combat, table, mid = setup(tmp_path, healer_cl=5)
    strike(combat, table, mid, 'slashing')
    turn(table, mid, FOE)
    before = reload(tmp_path, mid).state.actors[FOE].current_hp
    settle(table, mid, candidate(combat, mid, 'Unknown-authority recovery', target=FOE).candidate_id)
    assert reload(tmp_path, mid).state.actors[FOE].current_hp == before


@pytest.mark.parametrize('owner_auto', [False, True])
def test_real_coated_opportunity_hit_on_automatic_enemy_turn(tmp_path, owner_auto):
    from tests.hunt36_support import send
    coated = 'tianxia.talent.poison.coated_weapon'
    combat, table, mid = setup(tmp_path, owner_talents=[coated],
        foe_position={'x':2,'y':6}, foe_ac=1,
        owner_kit={'starting_kit':{'items':[{'item_id':'tianxia.mortal.weapon.bi_shou','quantity':1}]}})
    engine = reload(tmp_path, mid)
    dagger = next(a.source_definition_id for a in engine.action_catalog.values()
                  if (a.parameters.get('typed') or {}).get('source') == 'tianxia.mortal.weapon.bi_shou'
                  and '.weapon.' in a.source_definition_id and '#' not in a.source_definition_id)
    settle(table, mid, candidate(combat, mid, 'Coat a Weapon', target=OWNER).candidate_id,
           picks={'choice:needle.poison_coated_weapon':dagger})
    turn(table, mid, FOE)
    if owner_auto:
        combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    engine = reload(tmp_path, mid)
    move = next(c for c in engine.legal_candidates()
                if c.destination is not None and (c.destination.x,c.destination.y) == (1,6))
    prompts = send(combat, table, mid, move.candidate_id, ai=True,
                   pick=lambda option: option['id'] == 'poison')
    engine = reload(tmp_path, mid)
    assert len(packets(engine)) == 1
    assert packets(engine)[0].payload['hp_damage'] == 1
    assert engine.state.actors[OWNER].resources[POOL] == 0
    asks = [p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.ash_strike']
    assert bool(asks) == (not owner_auto)
    if asks:
        assert 'Ash-Returning Strike' in asks[0]['moment'] and 'Mara' in asks[0]['moment']
    receipt = next(e for e in reversed(engine.events) if e.payload.get('trigger') == 'foundation_hit_settled')
    assert receipt.payload['qualifies'] == 1
    assert 'poison_coat_weapon' in receipt.payload['method_sources']
