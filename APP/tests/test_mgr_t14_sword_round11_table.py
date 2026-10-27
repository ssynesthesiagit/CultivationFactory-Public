"""Sol seam review round 11: the printed sword-family behaviours through real service commits and cold reload.

Finding 1: a lent real sword is one physical item. The borrower's own catalog holds its held copy, the lender loses
           simultaneous use, and the borrower makes the ordinary wielded attack printed by "Wielded Sword".
Finding 2: the once-during-each-turn controls are offered on another creature's turn for BOTH twin swords and
           without requiring a field.
Finding 3: Sword-Qi Origin classifies a compiled sword technique from its native delivery.
Finding 4: Call the Seed Sword is offered as part of activating a sword-delivered technique through the floating
           sword, at no extra action cost.

No browser, no live model transport, no repository history: every assertion reads the service's own committed state,
the engine's catalog or a cold reload of the saved fight.
"""
import json

import pytest

from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.ext import ten_thousand_swords as swords
from tests.h1_support import ROOT, sheet
from tests.worker2_support import candidate, settle, reload, turn

A = 'actor:factory.sword-owner'
B = 'actor:factory.sword-lender'
JIAN = 'tianxia.mortal.weapon.jian'
SWORD_IN_HAND = 'SWORD_BASE_SWORD_IN_HAND'


def _sword_record():
    """One real treasure jian, exactly as the owner item store resolves it."""
    from factory_authoring import treasure_weapons
    rules = treasure_weapons.authority()
    groups = json.loads((ROOT / 'combat/rules/weapon_specials.json').read_text())['proficiency']['groups']['sword']
    chassis = next(c for c in rules['chassis'] if c['item_id'].rsplit('.', 1)[-1] in groups)
    grade = rules['grade_order'][0]
    material = treasure_weapons.material_options(grade)[0]
    return {'kind': 'weapon', 'chassis_id': chassis['item_id'], 'grade': grade,
            'material_id': material['material_id'], 'enchantment_ids': []}


def native(tmp_path, monkeypatch, *, cl=18, talents=(), seeds=1, real_sword_owner=None):
    """Two native characters on a journey; the real sword belongs to whoever ``real_sword_owner`` names."""
    sheets = {'sword-owner': sheet(list(talents), cl=cl, name='sword-owner'),
              'sword-lender': sheet([], cl=6, name='sword-lender')}
    monkeypatch.setattr(CombatService, '_factory_owner_sheet', lambda self, pid: sheets[pid])
    arena = {'stable_id': 'battlefield:sword-round11', 'display_name': 'Sword court',
             'width_squares': 14, 'height_squares': 12, 'square_size_ft': 5,
             'starting_positions': {}, 'terrain_regions': []}
    monkeypatch.setattr(CombatService, 'factory_arenas', lambda self, **kw: {'court': arena})
    def cold():
        return CombatService(ROOT, tmp_path)
    if real_sword_owner:
        from factory_authoring.owner_items import OwnerItemStore
        row = OwnerItemStore(tmp_path / 'owner_items')
        uid = row.give(real_sword_owner, _sword_record())['item_uid']
    else:
        uid = None
    initial = cold().create_journey(project_ids=['sword-owner', 'sword-lender'], arena_id='court',
                                    positions={A: {'x': 2, 'y': 2}, B: {'x': 3, 'y': 2}}, base_paces={A: 5, B: 5})
    jid = initial['journey_id']
    def acquisition(source, payload, actor=A):
        before = cold().journey_state(jid)
        after = cold().journey_acquire_source(jid, before['revision'], actor, source, payload)
        assert cold().journey_state(jid) == after
        return after
    cold().journey_world_fact(jid, 0, {'source': swords.FAMILY, 'subject': A,
        'kind': 'scripture_access', 'scope': 'sect-instruction', 'value': {
            'source_rule': swords.FAMILY, 'instruction': 'Instruction in the complete Restricted Scripture',
            'access_category': 'Restricted Scripture',
            'instructor_authority': 'The sect custodian grants actual instruction'},
        'expires_at': 86400, 'readers': [A]})
    acquisition(swords.FAMILY, {'access_scope': 'sect-instruction'})
    for slot in range(seeds):
        acquisition(swords.SEED if slot == 0 else swords.TWIN,
                    {'slot': slot, 'form': 'projected', 'damage_type': 'force'})
    return cold, jid, uid, acquisition


def _admission(cold, jid, uid, *, subject=A, scope='real-sword'):
    s = cold().journey_state(jid)
    return cold().journey_world_fact(jid, s['revision'], {'source': swords.FAMILY, 'subject': subject,
        'kind': 'binding_admission', 'scope': scope, 'expires_at': s['seconds'] + 86400, 'readers': [subject],
        'value': {'item_uid': uid, 'source_rule': 'The actual native sword chassis',
                  'sword_classification': 'sword', 'touching': 1, 'external_bonds_clear': 1,
                  'prerequisites_met': 1, 'sentient': 0, 'sentient_consent': 1, 'restraint_clear': 1}})


def _permission(cold, jid, uid):
    """The lender's own consent to the borrower binding this exact sword (his own subjective fact)."""
    s = cold().journey_state(jid)
    return cold().journey_act(jid, s['revision'], B, 'declare_fact', {
        'source': swords.FAMILY, 'subject': B, 'kind': 'item_permission', 'scope': A + '|' + uid,
        'value': 1, 'expires_at': s['seconds'] + 86400, 'readers': [A]})


def combat(cold, jid, tmp_path):
    before = cold().journey_state(jid)
    mid = cold().journey_start_combat(jid, before['revision'], {A: 'team:a', B: 'team:b'},
                                      maximum_rounds=30)['match_id']
    table = TabletopService(cold(), tmp_path)
    turn(table, mid, A)
    return cold(), table, mid


def use(game, name, **kw):
    service, table, mid = game
    picks = kw.pop('picks', None)
    c = candidate(service, mid, name, **kw)
    assert c is not None, name
    prompts = settle(table, mid, c.candidate_id, picks=picks)
    reload(service.userdata_root, mid)
    return prompts


def scripted_outcomes(monkeypatch, *, save_success=True):
    from combat.gate2_rolls import DeterministicRollAuthority
    original = DeterministicRollAuthority.d20
    def roll(self, **kwargs):
        record = original(self, **kwargs)
        natural = (20 if save_success else 1) if 'SAVE' in kwargs['reason'].upper() else 19
        return record.model_copy(update={'natural_result': natural, 'total': natural + record.modifier,
            'dice': tuple(natural for _ in record.dice),
            'discarded': tuple(natural for _ in record.discarded)})
    monkeypatch.setattr(DeterministicRollAuthority, 'd20', roll)


def _held_copy(engine, borrower):
    """The borrower's own compiled copy of the lent sword (requires_held_weapon names the owner's action)."""
    rows = [row for row in engine.action_catalog.values()
            if row.owner_id == borrower and (row.parameters or {}).get('requires_held_weapon')
            and '#' not in row.source_definition_id and '.weapon.' in row.source_definition_id]
    assert len(rows) == 1, [row.source_definition_id for row in rows]
    return rows[0]


# ------------------------------------------------------------------ Finding 1: borrowed possession
def test_lent_real_sword_is_one_item_the_borrower_wields_and_the_lender_loses(tmp_path, monkeypatch):
    scripted_outcomes(monkeypatch)
    cold, jid, uid, acquire = native(tmp_path, monkeypatch, cl=18, seeds=0, real_sword_owner='sword-lender')
    _admission(cold, jid, uid)
    _permission(cold, jid, uid)
    after = acquire(swords.SEED, {'slot': 0, 'form': 'real', 'damage_type': 'force', 'item_uid': uid,
                                  'owner_id': B, 'admission_scope': 'real-sword'})
    from factory_authoring.owner_items import OwnerItemStore
    assert len(OwnerItemStore(tmp_path / 'owner_items').items('sword-lender')) == 1
    assert OwnerItemStore(tmp_path / 'owner_items').items('sword-owner') == []
    sword = after['actors'][A]['source_states'][swords.FAMILY]['swords'][0]
    assert sword['owner_id'] == B and sword['item_uid'] == uid
    borrowed = [a for a in after['actors'][A]['bundle']['action_catalog']
                if (a.get('parameters') or {}).get('requires_held_weapon') == sword['weapon_action']]
    assert len(borrowed) == 1, 'the borrower must hold the actual sword as its own compiled weapon'

    game = combat(cold, jid, tmp_path)
    engine = reload(tmp_path, game[2])
    borrowed_action = _held_copy(engine, A)
    custody = [c for c in engine.state.actors[B].conditions.values()
               if (c.data or {}).get('disables_action') == sword['weapon_action']]
    assert custody and custody[0].data['held_by'] == A
    from combat.weapon_delivery import available_weapons
    assert sword['weapon_action'] not in available_weapons(engine, engine.state.actors[B])
    assert borrowed_action.source_definition_id in available_weapons(engine, engine.state.actors[A])

    use(game, 'Release the Seed Sword')
    turn(game[1], game[2], B)
    turn(game[1], game[2], A)
    use(game, 'Call the Seed Sword')
    engine = reload(tmp_path, game[2])
    assert swords.state(engine.state.actors[A])['swords'][0]['location'] == 'wielded'
    before = len(engine.events)
    use(game, borrowed_action.display_name, target=B,
        picks={'choice:needle.sword_array.intent:' + B: None})
    engine = reload(tmp_path, game[2])
    hits = [e for e in engine.events[before:] if e.event_type == 'DAMAGE_COMMITTED' and e.actor_id == A]
    assert hits, 'the borrower makes the printed ordinary wielding attack with the actual sword'
    assert swords.state(engine.state.actors[A])['swords'][0]['item_uid'] == uid
    assert engine.state.actors[A].position.x == 2  # an actual weapon attack, not a remote origin
    assert engine.state.model_dump(mode='json') == reload(tmp_path, game[2]).state.model_dump(mode='json')


def test_lent_sword_binding_still_requires_the_owners_permission(tmp_path, monkeypatch):
    cold, jid, uid, acquire = native(tmp_path, monkeypatch, cl=18, seeds=0, real_sword_owner='sword-lender')
    _admission(cold, jid, uid)
    before = cold().journey_state(jid)
    with pytest.raises(ValueError):
        acquire(swords.SEED, {'slot': 0, 'form': 'real', 'damage_type': 'force', 'item_uid': uid,
                              'owner_id': B, 'admission_scope': 'real-sword'})
    assert cold().journey_state(jid) == before


# ------------------------------------------------------------------ Finding 4: technique-time Call
def test_technique_time_call_brings_the_floating_seed_sword_to_hand(tmp_path, monkeypatch):
    scripted_outcomes(monkeypatch)
    cold, jid, uid, acquire = native(tmp_path, monkeypatch, cl=18, talents=[SWORD_IN_HAND], seeds=0,
                                     real_sword_owner='sword-owner')
    _admission(cold, jid, uid)
    acquire(swords.SEED, {'slot': 0, 'form': 'real', 'damage_type': 'force', 'item_uid': uid,
                          'owner_id': A, 'admission_scope': 'real-sword'})
    game = combat(cold, jid, tmp_path)
    use(game, 'Release the Seed Sword')
    turn(game[1], game[2], B)
    turn(game[1], game[2], A)
    engine = reload(tmp_path, game[2])
    technique = next(row for row in engine.action_catalog.values()
                     if row.owner_id == A and row.source_definition_id.endswith(SWORD_IN_HAND))
    assert swords.sword_technique(engine, engine.state.actors[A], technique) is True
    assert swords.weapon_hit_technique(technique) is True
    before = len(engine.events)
    prompts = use(game, technique.display_name, target=B,
                  picks={'choice:needle.sword_array.technique-call': ['0'],
                         'choice:needle.sword_array.intent:' + B: None})
    assert any(p['context']['reaction_source_id'] == 'choice:needle.sword_array.technique-call' for p in prompts)
    engine = reload(tmp_path, game[2])
    actor = engine.state.actors[A]
    assert swords.state(actor)['swords'][0]['location'] == 'wielded'
    assert actor.bonus_action_available is True, 'the Call is part of the activation, not a second Bonus Action'
    assert [e for e in engine.events[before:] if e.event_type == 'ATTACK_ROLLED' and e.actor_id == A]
    assert engine.state.model_dump(mode='json') == reload(tmp_path, game[2]).state.model_dump(mode='json')


# ------------------------------------------------------------------ Finding 2: complete off-turn controls
def test_off_turn_controls_move_both_twin_swords_without_a_field(tmp_path, monkeypatch):
    scripted_outcomes(monkeypatch)
    cold, jid, _uid, _ = native(tmp_path, monkeypatch, cl=18, seeds=2)
    game = combat(cold, jid, tmp_path)
    use(game, 'Manifest Twin Swords')
    engine = reload(tmp_path, game[2])
    before = [(w['x'], w['y']) for w in swords.state(engine.state.actors[A])['swords']]
    assert all(w['location'] == 'floating' for w in swords.state(engine.state.actors[A])['swords'])
    assert not swords.fields(engine, engine.state.actors[A])  # no field: Twin's own each-turn allowance
    table = game[1]
    end_turn = table.state(game[2])['menu']['end_turn']
    # The destination menu's first legal point can be the sword's current cell, so take each sword's
    # second legal point: both moves must really relocate their own sword.
    prompts = settle(table, game[2], end_turn,
                     picks={'choice:needle.sword_array.offturn': ['move:0', 'move:1'],
                            'choice:needle.sword_array.point:0:True:False': ['1'],
                            'choice:needle.sword_array.point:1:True:False': ['1']})
    off_turn = [p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.sword_array.offturn']
    assert off_turn, 'the owner is asked at the start of the other creature\'s turn'
    offered = {option['id'] for option in off_turn[0]['choice']['options']}
    assert {'move:0', 'move:1'} <= offered, 'each floating sword keeps its own move'
    engine = reload(tmp_path, game[2])
    after = [(w['x'], w['y']) for w in swords.state(engine.state.actors[A])['swords']]
    assert after[0] != before[0] and after[1] != before[1]
    tag = f'{engine.state.round_number}:{B}'
    flags = engine.state.actors[A].turn_flags
    assert flags.get(f'sword_offturn:move:0:{tag}') and flags.get(f'sword_offturn:move:1:{tag}')
    assert not flags.get('sword_move:0') and not flags.get('sword_move:1')
    assert engine.state.model_dump(mode='json') == reload(tmp_path, game[2]).state.model_dump(mode='json')
