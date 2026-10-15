"""Native acquisition -> journey -> table commit -> cold replay for this cohort.

No browsers or live model transport. External Scripture access is collected by
the real GM input; feature ownership is produced by journey_acquire_source.
"""
import hashlib
import zipfile
import pytest
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.ext import ten_thousand_swords as swords
from tests.h1_support import ROOT, sheet
from tests.worker2_support import candidate, settle, reload, turn

A = 'actor:factory.sword-owner'
B = 'actor:factory.sword-foe'


def native(tmp_path, monkeypatch, *, cl=18, learn=True, seeds=1):
    monkeypatch.setattr(CombatService, '_factory_owner_sheet',
        lambda self, pid: sheet([], cl=cl, name=pid))
    arena = {'stable_id': 'battlefield:sword-native', 'display_name': 'Sword court',
             'width_squares': 14, 'height_squares': 12, 'square_size_ft': 5,
             'starting_positions': {}, 'terrain_regions': []}
    monkeypatch.setattr(CombatService, 'factory_arenas', lambda self, **kw: {'court': arena})
    def cold():
        return CombatService(ROOT, tmp_path)
    initial = cold().create_journey(project_ids=['sword-owner', 'sword-foe'], arena_id='court',
        positions={A: {'x': 2, 'y': 2}, B: {'x': 5, 'y': 2}}, base_paces={A: 5, B: 5})
    jid = initial['journey_id']
    def acquisition(source, payload, actor=A):
        before = cold().journey_state(jid)
        after = cold().journey_acquire_source(jid, before['revision'], actor, source, payload)
        assert cold().journey_state(jid) == after
        return after
    if learn:
        cold().journey_world_fact(jid, 0, {'source': swords.FAMILY, 'subject': A,
            'kind': 'scripture_access', 'scope': 'sect-instruction', 'value': {
                'source_rule': swords.FAMILY, 'instruction': 'Instruction in the complete Restricted Scripture',
                'access_category': 'Restricted Scripture', 'instructor_authority': 'The sect custodian grants actual instruction'},
            'expires_at': 86400, 'readers': [A]})
        acquisition(swords.FAMILY, {'access_scope': 'sect-instruction'})
        for slot in range(seeds):
            acquisition(swords.SEED if slot == 0 else swords.TWIN,
                        {'slot': slot, 'form': 'projected', 'damage_type': 'force'})
    return cold, jid, acquisition


def combat(cold, jid, tmp_path):
    before = cold().journey_state(jid)
    mid = cold().journey_start_combat(jid, before['revision'],
        {A: 'team:a', B: 'team:b'}, maximum_rounds=30)['match_id']
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


def test_source_zip_and_five_controlling_text_hashes():
    archive = ROOT / 'BundledContent/Tianxia_Factory_HF05ZVK_R1H_Phase2I_HF2.zip'
    with zipfile.ZipFile(archive) as z:
        name = next(n for n in z.namelist() if n.endswith('Tianxia_Qi_Cultivation_Subpath_Compendium_R19.md'))
        assert hashlib.sha256(z.read(name)).hexdigest() == 'ca25b88915a2d83324a23feed94a54409d359369dbd0452fb29d28b938262584'
    import json
    texts = json.loads((ROOT / 'authority/typed_mechanics/rules_text.json').read_text())
    assert all(mid in texts for mid in [swords.SEED, swords.INTENT, swords.ARRAY, swords.TWIN, swords.RETURN])


@pytest.mark.parametrize('cl, expected', [(2, 0), (3, 1), (6, 2), (10, 3), (14, 4), (18, 5)])
def test_native_restricted_scripture_progression_is_exact_and_cold(tmp_path, monkeypatch, cl, expected):
    if cl == 2:
        cold, jid, acquire = native(tmp_path, monkeypatch, cl=cl, learn=False, seeds=0)
        with pytest.raises(ValueError):
            acquire(swords.FAMILY, {'access_scope': 'missing'})
        assert not cold().journey_state(jid)['actors'][A].get('source_states')
        return
    cold, jid, _ = native(tmp_path, monkeypatch, cl=cl, seeds=0)
    s = cold().journey_state(jid)
    learned = s['actors'][A]['source_states'][swords.FAMILY]['learned']
    assert learned == [swords.PREFIX+k for k, level in swords.LEVELS.items() if cl >= level]
    assert len(learned) == expected
    assert not s['actors'][B].get('source_states')
    assert s['actors'][A]['resources'][swords.QI] == 30


@pytest.mark.parametrize('guard', ['missing-access', 'wrong-subject', 'no-seed', 'second-before-first'])
def test_acquisition_guards_reject_atomically(tmp_path, monkeypatch, guard):
    cold, jid, acquire = native(tmp_path, monkeypatch, learn=guard == 'second-before-first', seeds=0)
    before = cold().journey_state(jid)
    if guard in ('missing-access', 'wrong-subject'):
        source, payload, actor = swords.FAMILY, {'access_scope': 'sect-instruction'}, B if guard == 'wrong-subject' else A
    else:
        source, payload, actor = swords.SEED, {'slot': 1 if guard == 'second-before-first' else 0, 'form': 'projected', 'damage_type': 'force'}, A
    with pytest.raises(ValueError):
        acquire(source, payload, actor)
    assert cold().journey_state(jid) == before


def test_ritual_replaces_one_bond_and_pays_actual_time_and_qi(tmp_path, monkeypatch):
    cold, jid, acquire = native(tmp_path, monkeypatch, cl=3)
    first = cold().journey_state(jid)
    assert first['seconds'] == 600
    assert first['actors'][A]['resources'][swords.QI] == 29
    after = acquire(swords.SEED, {'slot': 0, 'form': 'projected', 'damage_type': 'slashing'})
    assert after['seconds'] == 1200
    assert after['actors'][A]['resources'][swords.QI] == 28
    assert len(after['actors'][A]['source_states'][swords.FAMILY]['swords']) == 1
    assert after['actors'][A]['source_states'][swords.FAMILY]['swords'][0]['damage_type'] == 'slashing'


def test_ritual_bond_reaches_native_combat_but_cannot_attack_before_release(tmp_path, monkeypatch):
    cold, jid, _ = native(tmp_path, monkeypatch, cl=3)
    game = combat(cold, jid, tmp_path)
    engine = reload(tmp_path, game[2])
    assert len(swords.state(engine.state.actors[A])['swords']) == 1
    assert not [c for c in engine.legal_candidates() if c.display_name == 'Sword Seed']
    use(game, 'Release the Seed Sword')
    engine = reload(tmp_path, game[2])
    assert swords.state(engine.state.actors[A])['swords'][0]['location'] == 'floating'
    assert engine.state.actors[A].position.x == 2


def test_wrong_owner_has_no_sword_commands(tmp_path, monkeypatch):
    cold, jid, _ = native(tmp_path, monkeypatch, learn=False)
    game = combat(cold, jid, tmp_path)
    assert not [a for a in reload(tmp_path, game[2]).action_catalog.values() if a.parameters.get('sword_array')]


def test_array_is_paid_one_concentrated_cylinder_without_creation_damage(tmp_path, monkeypatch):
    cold, jid, _ = native(tmp_path, monkeypatch, cl=10)
    game = combat(cold, jid, tmp_path)
    before = reload(tmp_path, game[2])
    hp = before.state.actors[B].current_hp
    qi = before.state.actors[A].resources[swords.QI]
    use(game, 'Sword Array Field', at=(5, 2))
    after = reload(tmp_path, game[2])
    zones = swords.fields(after, after.state.actors[A])
    assert len(zones) == 1 and zones[0].trigger_profile['height_ft'] == 20
    assert after.state.actors[A].concentration is not None
    assert after.state.actors[A].resources[swords.QI] == qi - 5
    assert after.state.actors[B].current_hp == hp


def test_twin_manifestation_requires_two_native_bonds_and_pays_once(tmp_path, monkeypatch):
    cold, jid, _ = native(tmp_path, monkeypatch, cl=14, seeds=2)
    game = combat(cold, jid, tmp_path)
    before = reload(tmp_path, game[2]).state.actors[A].resources[swords.QI]
    use(game, 'Manifest Twin Swords')
    engine = reload(tmp_path, game[2])
    s = swords.state(engine.state.actors[A])['swords']
    assert len(s) == 2 and all(w['location'] == 'floating' for w in s)
    assert engine.state.actors[A].resources[swords.QI] == before - 2


def test_return_to_origin_one_scene_limit_and_no_spawned_sword_actors(tmp_path, monkeypatch):
    cold, jid, _ = native(tmp_path, monkeypatch, cl=18)
    game = combat(cold, jid, tmp_path)
    use(game, 'Ten Thousand Swords Return to Origin', at=(5, 2))
    engine = reload(tmp_path, game[2])
    assert set(engine.state.actors) == {A, B}
    assert swords.perfected(engine, engine.state.actors[A])
    assert swords.state(engine.state.actors[A])['origin_used'] == 1
    assert len(swords.fields(engine, engine.state.actors[A])) == 1


def scripted_outcomes(monkeypatch, *, save_success=False):
    from combat.gate2_rolls import DeterministicRollAuthority
    original = DeterministicRollAuthority.d20
    def roll(self, **kwargs):
        record = original(self, **kwargs)
        natural = (20 if save_success else 1) if 'SAVE' in kwargs['reason'].upper() else 19
        return record.model_copy(update={'natural_result': natural, 'total': natural + record.modifier,
            'dice': tuple(natural for _ in record.dice),
            'discarded': tuple(natural for _ in record.discarded)})
    monkeypatch.setattr(DeterministicRollAuthority, 'd20', roll)


@pytest.mark.parametrize('intent', swords.INTENTS)
@pytest.mark.parametrize('success', [False, True])
def test_each_paid_intent_follows_real_hit_commit_and_cold_reload(tmp_path, monkeypatch, intent, success):
    scripted_outcomes(monkeypatch, save_success=success)
    cold, jid, _ = native(tmp_path, monkeypatch, cl=6)
    game = combat(cold, jid, tmp_path)
    use(game, 'Release the Seed Sword')
    turn(game[1], game[2], B)
    turn(game[1], game[2], A)
    before = reload(tmp_path, game[2])
    qi = before.state.actors[A].resources[swords.QI]
    position = before.state.actors[B].position
    use(game, 'Sword Seed', target=B,
        picks={'choice:needle.sword_array.intent:' + B: [intent]})
    after = reload(tmp_path, game[2])
    actor, foe = after.state.actors[A], after.state.actors[B]
    mark = next(c for c in foe.conditions.values() if c.condition_id == swords.MARK)
    assert mark.source_actor_id == A and mark.data['intent'] == intent
    assert actor.resources[swords.QI] == qi - 1
    assert actor.turn_flags['array_sword_intent']
    if intent == 'Dread':
        assert any(c.condition_id == ('condition:typed.reaction_denied' if success else 'condition:typed.frightened')
                   for c in foe.conditions.values())
    elif intent == 'Severing':
        assert any(c.condition_id == 'condition:typed.reaction_denied' for c in foe.conditions.values())
        assert bool(any(c.condition_id == 'condition:typed.concentration_mode' for c in foe.conditions.values())) == (not success)
    elif intent == 'Arresting':
        assert any(m.target_field == 'speed_ft' and m.value == (-5 if success else -15) for m in foe.modifiers.values())
    elif intent == 'Displacing':
        assert after.grid.distance_ft(position, foe.position) <= (5 if success else 10)
        assert position != foe.position
    else:
        exposed = next(c for c in foe.conditions.values() if c.condition_id == 'condition:typed.array_exposing')
        assert exposed.data['next_sword'] == int(not success)


@pytest.mark.parametrize('cl, dice', [(10, 3), (17, 4)])
def test_array_start_cadence_uses_native_zone_once_and_holder_expiry(tmp_path, monkeypatch, cl, dice):
    scripted_outcomes(monkeypatch)
    cold, jid, _ = native(tmp_path, monkeypatch, cl=cl)
    game = combat(cold, jid, tmp_path)
    use(game, 'Sword Array Field', at=(5, 2))
    initial = reload(tmp_path, game[2])
    before = initial.state.actors[B].current_hp
    turn(game[1], game[2], B)
    after = reload(tmp_path, game[2])
    assert after.state.actors[B].current_hp < before
    packets = [r for r in after.rolls if 'd8' in r.expression]
    assert any(r.expression.startswith(str(dice) + 'd8') for r in packets)
    denial = next(c for c in after.state.actors[B].conditions.values() if c.condition_id == 'condition:typed.reaction_denied')
    assert B in denial.expires_on
    stable = after.state.model_dump(mode='json')
    assert reload(tmp_path, game[2]).state.model_dump(mode='json') == stable


@pytest.mark.parametrize('cl', [14, 17])
def test_twin_command_declares_two_separate_attacks_without_second_key_modifier(tmp_path, monkeypatch, cl):
    scripted_outcomes(monkeypatch)
    cold, jid, _ = native(tmp_path, monkeypatch, cl=cl, seeds=1)
    game = combat(cold, jid, tmp_path)
    use(game, 'Manifest Twin Swords')
    turn(game[1], game[2], B)
    turn(game[1], game[2], A)
    before = reload(tmp_path, game[2])
    first = len(before.events)
    use(game, 'Twin-Sword Command', picks={'choice:needle.sword_array.intent:' + B: None})
    after = reload(tmp_path, game[2])
    rolled = [e for e in after.events[first:] if e.event_type == 'ATTACK_ROLLED' and e.actor_id == A]
    assert len(rolled) == 2
    assert after.state.actors[A].turn_flags['twin_commanded']
    attacks = [e for e in after.events[first:] if e.event_type == 'DAMAGE_COMMITTED' and e.actor_id == A]
    assert len(attacks) == 2
    damage_rolls = [r for r in after.rolls[len(before.rolls):] if 'd8' in r.expression]
    assert len(damage_rolls) == 2
    assert damage_rolls[0].modifier - damage_rolls[1].modifier == 2


def test_projected_sword_never_enters_native_item_inventory(tmp_path, monkeypatch):
    cold, jid, _ = native(tmp_path, monkeypatch)
    state = cold().journey_state(jid)
    assert not state['actors'][A]['bundle'].get('acquisition_inventory')
    assert state['actors'][A]['source_states'][swords.FAMILY]['swords'][0]['item_uid'] == ''
