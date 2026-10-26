"""Alchemy second pass at the saved CombatService/Table transaction boundary."""
import json
import zipfile

import pytest

from combat import ext
from combat.gate5_service import CombatService
from combat.tabletop import ButtonStore
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.test_hidden_targeting import turn
from tests.test_lock2_persistence import act
from tests.r10_fixup_support import cast_sender, commit

OWNER = 'actor:factory.aaaaaaaa'
ALLY = 'actor:factory.bbbbbbbb'
FOE = 'actor:factory.ffffffff'
BASE = 'ALCHEMY_BASE_FIELD_FORMULA'
ANTIDOTE = 'TAL_ALCHEMY_ANTIDOTE_PILL'
RESIDUE = 'condition:typed.alchemy_corrosive_residue'
POISONED = 'condition:typed.poisoned'
STOCK = 'resource:named.reagent_stock'
CP = 'resource:core.stamina'


def fight(monkeypatch, tmp_path, *, dc=50, talents=(), insights=(), prepare=None,
          ally_at=(6, 5), foe_at=(6, 4), ai=False):
    for pid in ('aaaaaaaa', 'bbbbbbbb', 'ffffffff'):
        doc = sheet([BASE, *talents] if pid == 'aaaaaaaa' else [BASE], primary='Stamina', dc=dc,
                    cl=15 if insights else 10)
        doc['identity']['display_name'] = {'aaaaaaaa': 'Alchemist', 'bbbbbbbb': 'Ally', 'ffffffff': 'Enemy'}[pid]
        doc['spheres_and_talents']['cultivation_insight_record_ids'] = list(insights) if pid == 'aaaaaaaa' else []
        doc['ability_scores_and_statistics']['hit_points']['maximum'] = 400
        folder = tmp_path / 'portable_characters' / pid
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / 'current.zip', 'w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(doc))
        ButtonStore(tmp_path / 'tabletop_buttons').save_reactions(pid, {'mode': 'ask'}, {BASE, ANTIDOTE, 'insight.medicine-saint'})
    if prepare:
        ext.effects()
        monkeypatch.setitem(ext._HOOKS, 'event', [*ext._HOOKS.get('event', []), prepare])
    combat = CombatService(ROOT, tmp_path)
    combat.tabletop_maps.save({'display_name': 'Alchemy second pass', 'width_squares': 10, 'height_squares': 8,
        'walls': [], 'starts': {'team1': [[3, 4], list(ally_at)], 'team2': [list(foe_at)]}})
    mid = combat.create_factory_match(project_ids=['aaaaaaaa', 'bbbbbbbb'], opponent_actor_ids=[FOE],
        control_modes={OWNER: 'LOCAL_AUTO' if ai else 'MANUAL', ALLY: 'MANUAL', FOE: 'MANUAL'},
        arena_id='battlefield:map.alchemy-second-pass', match_seed='A2ALCHEMY')['match_id']
    table = TabletopService(combat, tmp_path)
    turn(table, mid, OWNER)
    return combat, table, mid


def reload_checked(tmp_path, mid):
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    assert session.verify()['status'] == session.mechanical.replay()['status'] == 'PASS'
    return session.engine


def poison_setup(recipient, *, dc=-40, repeated=True, count=1):
    def prepare(engine, kind, record):
        if kind != 'HOLD_POSITION_COMMITTED' or record.get('actor_id') != OWNER:
            return
        target = engine.state.actors[recipient]
        if engine.state.actors[OWNER].turn_flags.get('test_poison_ready'):
            return
        engine.state.actors[OWNER].turn_flags['test_poison_ready'] = True
        for n in range(count):
            data = {'origin_save': {'ability': 'CON', 'dc': dc + n}, 'label': f'Test poison {n}'}
            if repeated:
                data['repeat_save'] = {'ability': 'CON', 'dc': dc + n, 'when': 'end'}
            engine._apply_condition(target, POISONED, f'test:poison:{n}', FOE,
                                    expires_on='UNTIL_REMOVED', data=data)
    return prepare


def use_first_recheck(prompt):
    return (prompt['choice']['options'][0]['id'], 'saving throw against Poisoned' in prompt.get('trigger', '')
            or 'saving throw against Poisoned' in str(prompt))


@pytest.mark.parametrize('recipient', [OWNER, ALLY])
@pytest.mark.parametrize('accept', [True, False])
def test_medicinal_smoke_beneficiary_chooses_one_poison_save_and_reloads(monkeypatch, tmp_path, recipient, accept):
    combat, table, mid = fight(monkeypatch, tmp_path,
        prepare=poison_setup(recipient, repeated=False, count=2))
    assert act(table, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
    before = reload_checked(tmp_path, mid)
    held = {iid for iid, c in before.state.actors[recipient].conditions.items() if c.condition_id == POISONED}
    resources = dict(before.state.actors[OWNER].resources)
    prompts = commit(cast_sender(combat, table, mid, 'Field Formula: Medicinal Smoke', target=recipient),
        lambda p: (p['choice']['options'][0]['id'], accept))
    engine = reload_checked(tmp_path, mid)
    actor = engine.state.actors[recipient]
    remaining = {iid for iid, c in actor.conditions.items() if c.condition_id == POISONED}
    assert len(prompts) == 1
    assert prompts[0]['context']['reactor_id'] == recipient
    assert len(prompts[0]['choice']['options']) == 2
    assert len(held - remaining) == int(accept) and remaining <= held
    assert actor.temporary_hp > 0
    assert engine.state.actors[FOE].temporary_hp == 0
    assert engine.state.actors[OWNER].resources[STOCK] == resources[STOCK] - 1
    assert engine.state.actors[OWNER].resources[CP] == resources[CP] - 1
    assert len([e for e in engine.events if e.event_type == 'SAVE_ROLLED'
                and e.source_definition_id.startswith('action:typed.')]) == int(accept)


@pytest.mark.parametrize('dc,success', [(-40, True), (50, False)])
def test_medicinal_poison_recheck_retains_original_dc_and_failure(monkeypatch, tmp_path, dc, success):
    combat, table, mid = fight(monkeypatch, tmp_path, prepare=poison_setup(ALLY, dc=dc))
    assert act(table, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
    commit(cast_sender(combat, table, mid, 'Field Formula: Medicinal Smoke', target=ALLY), use_first_recheck)
    engine = reload_checked(tmp_path, mid)
    saves = [e for e in engine.events if e.event_type == 'SAVE_ROLLED' and e.actor_id == ALLY]
    assert len(saves) == 1 and saves[0].payload['dc'] == dc
    assert any(c.condition_id == POISONED for c in engine.state.actors[ALLY].conditions.values()) is not success


@pytest.mark.parametrize('repeated,blocked', [(True, False), (False, False), (True, True)])
def test_antidote_repeats_only_repeatable_poison_and_consumes_next_save_advantage(monkeypatch, tmp_path, repeated, blocked):
    poison = poison_setup(OWNER, repeated=repeated)
    def prepare(engine, kind, record):
        poison(engine, kind, record)
        if blocked and kind == 'HOLD_POSITION_COMMITTED' and record.get('actor_id') == OWNER:
            engine._apply_condition(engine.state.actors[OWNER], 'condition:typed.test_save_limit',
                'test:no-advantage', FOE, expires_on='UNTIL_REMOVED',
                data={'rule': {'no_save_advantage': ['CON']}})
    combat, table, mid = fight(monkeypatch, tmp_path, talents=[ANTIDOTE],
                               prepare=prepare)
    assert act(table, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
    commit(cast_sender(combat, table, mid, 'Antidote Pill'), use_first_recheck)
    engine = reload_checked(tmp_path, mid)
    saves = [e for e in engine.events if e.event_type == 'SAVE_ROLLED' and e.actor_id == OWNER]
    assert len(saves) == int(repeated)
    if repeated:
        assert saves[0].payload['mode'] == ('NORMAL' if blocked else 'ADVANTAGE')
    assert any(c.condition_id == POISONED for c in engine.state.actors[OWNER].conditions.values()) is not repeated
    modes = [c for c in engine.state.actors[OWNER].conditions.values()
             if c.condition_id == 'condition:typed.save_against']
    assert bool(modes) is not repeated
    if modes:
        assert modes[0].expires_on == 'UNTIL_REMOVED'


@pytest.mark.parametrize('dc,saved', [(50, False), (-40, True)])
@pytest.mark.parametrize('temporary_hp', [False, True])
def test_corrosive_residue_waits_for_next_actual_damage_then_spends_once(monkeypatch, tmp_path, dc, saved, temporary_hp):
    def followup(engine, kind, record):
        if kind != 'HOLD_POSITION_COMMITTED' or record.get('actor_id') != OWNER:
            return
        if temporary_hp:
            engine._grant_temp_hp(engine.state.actors[FOE], 25, 'test:temporary-hp', FOE)
        for amount in (0, 7, 9):
            engine._commit_damage(engine.state.actors[FOE], amount, source_definition_id='test:followup',
                source_actor_id=OWNER, damage_type='FIRE', intent=engine._active_intent, reaction_depth=0)
    combat, table, mid = fight(monkeypatch, tmp_path, dc=dc, prepare=followup)
    resources = dict(combat._load_session(mid).engine.state.actors[OWNER].resources)
    commit(cast_sender(combat, table, mid, 'Field Formula: Corrosive Dregs', target=FOE))
    initial = reload_checked(tmp_path, mid)
    damage = [e for e in initial.events if e.event_type == 'DAMAGE_COMMITTED' and FOE in e.target_ids]
    assert len(damage) == 1, 'Residue must not deal damage during the initial failed save'
    assert any(c.condition_id == RESIDUE for c in initial.state.actors[FOE].conditions.values()) is not saved
    assert act(table, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
    engine = reload_checked(tmp_path, mid)
    damage = [e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED' and FOE in e.target_ids]
    assert [e.payload['damage_type'] for e in damage[1:]] == (['FIRE', 'FIRE', 'FIRE'] if saved
                                                           else ['FIRE', 'FIRE', 'ACID', 'FIRE'])
    if not saved:
        assert damage[3].payload['rolled_or_pending_damage'] == 4
    if temporary_hp:
        assert all(e.payload['hp_damage'] == 0 for e in damage[1:])
    assert not any(c.condition_id == RESIDUE for c in engine.state.actors[FOE].conditions.values())
    assert engine.state.actors[OWNER].resources[STOCK] == resources[STOCK] - 1


def test_corrosive_residue_expires_without_damage_at_source_next_turn(monkeypatch, tmp_path):
    combat, table, mid = fight(monkeypatch, tmp_path)
    commit(cast_sender(combat, table, mid, 'Field Formula: Corrosive Dregs', target=FOE))
    assert any(c.condition_id == RESIDUE for c in reload_checked(tmp_path, mid).state.actors[FOE].conditions.values())
    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    turn(table, mid, OWNER)
    engine = reload_checked(tmp_path, mid)
    assert not any(c.condition_id == RESIDUE for c in engine.state.actors[FOE].conditions.values())


def test_corrosive_space_hits_enemy_only_and_single_creature_can_target_an_ally(monkeypatch, tmp_path):
    combat, table, mid = fight(monkeypatch, tmp_path)
    engine = combat._load_session(mid).engine
    action = next(a for a in engine.action_catalog.values() if a.owner_id == OWNER
                  and a.display_name == 'Field Formula: Corrosive Dregs')
    assert action.target_kind == 'ANY_CREATURE'
    assert any(ALLY in c.target_ids and c.source_definition_id == action.source_definition_id
               for c in engine.legal_candidates())
    commit(cast_sender(combat, table, mid, 'Field Formula: Corrosive Dregs (5-foot space)', at=(6, 4)))
    engine = reload_checked(tmp_path, mid)
    assert engine.state.actors[FOE].current_hp < 400
    assert engine.state.actors[ALLY].current_hp == engine.state.actors[OWNER].current_hp == 400


@pytest.mark.parametrize('name,at', [('Numbing Smoke', (6, 4)), ('Corrosive Dregs', None)])
def test_ai_formula_in_mixed_range_harms_enemies_only(monkeypatch, tmp_path, name, at):
    from combat.gate4_context import build_decision_context, build_reaction_context
    from combat.gate4_controller import LocalDeterministicController
    from combat.gate4_policy import PolicyLibrary
    combat, table, mid = fight(monkeypatch, tmp_path, ai=True)
    session = combat._load_session(mid)
    controller, policies = LocalDeterministicController(), PolicyLibrary(ROOT)
    policy, _ = policies.for_actor(OWNER)
    context = build_decision_context(session.engine, policy, for_ai=True)
    # Restrict the offered primary action to the printed formula; the real AI
    # still chooses its aim/recipients, and answers any effect choices itself.
    action = next(a for a in session.engine.action_catalog.values() if a.owner_id == OWNER
                  and a.display_name == 'Field Formula: ' + name)
    candidates = [c for c in session.engine.legal_candidates()
                  if c.source_definition_id == action.source_definition_id
                  and (at is None or c.destination and (c.destination.x, c.destination.y) == at)]
    assert candidates
    context = context.model_copy(update={'legal_candidates': tuple(candidates)})
    choice = controller.choose_primary_action(context)
    def react(request):
        rp, _ = policies.for_actor(request['reactor_id'])
        chosen = controller.choose_reaction(build_reaction_context(session.engine, rp, request))
        return chosen.decision, chosen.record
    session.submit_intent(choice.intent, primary_decision_record=choice.record, reaction_provider=react)
    engine = reload_checked(tmp_path, mid)
    assert engine.state.actors[FOE].current_hp < 400
    assert engine.state.actors[ALLY].current_hp == engine.state.actors[OWNER].current_hp == 400
    assert any(c.condition_id == ('condition:typed.reaction_denied' if name == 'Numbing Smoke' else RESIDUE)
               for c in engine.state.actors[FOE].conditions.values())


STOMACH = 'insight.furnace-tyrant-s-stomach'
BITTER = 'TAL_ALCHEMY_BITTER_DREGS'


@pytest.mark.parametrize('has_insight', [True, False])
def test_stomach_reduces_real_owned_bitter_backlash_after_resistance(monkeypatch, tmp_path, has_insight):
    def prepare(engine, kind, record):
        if kind == 'HOLD_POSITION_COMMITTED' and record.get('actor_id') == OWNER:
            engine._gain_resource(engine.state.actors[OWNER], 'resource:named.bitter_dreg', 1, 'test:prepared')
    combat, table, mid = fight(monkeypatch, tmp_path, dc=-40, talents=[BITTER],
                               insights=[STOMACH] if has_insight else [], prepare=prepare)
    assert act(table, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
    commit(cast_sender(combat, table, mid, 'Field Formula: Numbing Smoke + Bitter Dregs', at=(6, 4)))
    engine = reload_checked(tmp_path, mid)
    damage = [e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED' and OWNER in e.target_ids]
    assert len(damage) == 1
    assert damage[0].payload['rolled_or_pending_damage'] == 4
    assert damage[0].payload['reduced_to'] == (0 if has_insight else 4)
    assert engine.state.actors[OWNER].current_hp == (400 if has_insight else 396)


@pytest.mark.parametrize('source_owner,damage_type,expected', [
    (OWNER, 'POISON', 6), (FOE, 'POISON', 10), (OWNER, 'FIRE', 20)])
def test_stomach_large_poison_packet_checks_owner_sphere_and_type(monkeypatch, tmp_path, source_owner, damage_type, expected):
    def incoming(engine, kind, record):
        if kind != 'HOLD_POSITION_COMMITTED' or record.get('actor_id') != OWNER:
            return
        from combat.typed_executor import Context, block_damage
        # The accepted service action supplies an incoming product packet using
        # the retained real compiled Alchemy source, just as Insight probes do.
        action = next(a for a in engine.action_catalog.values() if a.owner_id == source_owner
                      and a.display_name == 'Field Formula: Corrosive Dregs')
        target = engine.state.actors[OWNER]
        ctx = Context(engine, engine.state.actors[source_owner], action, engine._active_intent,
                      action.parameters['typed'], [target], target, explicit_self_recipient=True)
        block_damage(ctx, {'type': 'damage', 'applies_to': 'target', 'flat': 20, 'damage_types': [damage_type]})
    combat, table, mid = fight(monkeypatch, tmp_path, insights=[STOMACH], prepare=incoming)
    assert act(table, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
    engine = reload_checked(tmp_path, mid)
    damage = [e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED' and OWNER in e.target_ids]
    assert len(damage) == 1 and damage[0].payload['reduced_to'] == expected
    assert engine.state.actors[OWNER].current_hp == 400 - expected


@pytest.mark.parametrize('ward,expected_mode', [(None, 'NORMAL'), ('resistance', 'ADVANTAGE'),
                                              ('immunity', 'NORMAL'), ('resistance_next', 'NORMAL')])
def test_stomach_needs_another_standing_poison_resistance_for_save_advantage(monkeypatch, tmp_path, ward, expected_mode):
    def incoming(engine, kind, record):
        if kind != 'HOLD_POSITION_COMMITTED' or record.get('actor_id') != OWNER:
            return
        target = engine.state.actors[OWNER]
        if ward:
            engine._add_modifier(target, 'test:other-poison-defense', 'damage_' + ward,
                                  'ADD', 'POISON', 'ALWAYS', expires_on='UNTIL_REMOVED')
        engine._roll_save(target, 'CON', 50, 'test:poison-save',
                          roll_context={'source_actor_id': FOE, 'named': ['poisoned']})
    combat, table, mid = fight(monkeypatch, tmp_path, insights=[STOMACH], prepare=incoming)
    assert act(table, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
    engine = reload_checked(tmp_path, mid)
    saves = [e for e in engine.events if e.event_type == 'SAVE_ROLLED' and e.actor_id == OWNER]
    assert len(saves) == 1 and saves[0].payload['mode'] == expected_mode


SAINT = 'insight.medicine-saint'
SAINT_SAVE = 'condition:typed.medicine_saint_con_save'
HEAL = 'TAL_ALCHEMY_HEALING_PILL'
CALM = 'TAL_ALCHEMY_CALMING_HEART_PILL'


def source_sender(combat, table, mid, source):
    state = table.state(mid)
    c = next(c for c in combat._load_session(mid).engine.legal_candidates() if c.source_definition_id == source)
    return lambda answers=(): table.act(mid, c.candidate_id, c.decision_id, c.state_version,
                                        state['last_sequence'], list(answers))


@pytest.mark.parametrize('recipe,name', [(HEAL, 'Healing Pill'), (ANTIDOTE, 'Antidote Pill'),
                                       (CALM, 'Calming Heart Pill')])
def test_medicine_saint_administers_to_actual_consumer_and_consumer_chooses_con_save(monkeypatch, tmp_path, recipe, name):
    def incoming(engine, kind, record):
        if kind != 'HOLD_POSITION_COMMITTED' or record.get('actor_id') != OWNER:
            return
        owner = engine.state.actors[OWNER]
        ally = engine.state.actors[ALLY]
        if not owner.turn_flags.get('test_prepared'):
            owner.turn_flags['test_prepared'] = True
            engine._commit_damage(ally, 30, 'FIRE', 'test:wound', FOE, engine._active_intent, reaction_depth=0)
        elif any(c.condition_id == SAINT_SAVE for c in ally.conditions.values()):
            for source in ('test:save-one', 'test:save-two'):
                engine._roll_save(ally, 'CON', 50, source, roll_context={'source_actor_id': FOE})
    combat, table, mid = fight(monkeypatch, tmp_path, talents=[recipe], insights=[SAINT],
                               ally_at=(4, 4), prepare=incoming)
    assert act(table, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
    commit(cast_sender(combat, table, mid, 'Medicine Saint: Administer ' + name, target=ALLY))
    engine = reload_checked(tmp_path, mid)
    owner, ally, foe = (engine.state.actors[who] for who in (OWNER, ALLY, FOE))
    assert owner.current_hp == foe.current_hp == 400
    assert not owner.bonus_action_available
    assert any(c.condition_id == SAINT_SAVE for c in ally.conditions.values())
    assert not any(c.condition_id == SAINT_SAVE for c in owner.conditions.values())
    if recipe == HEAL:
        heal = next(e for e in engine.events if e.event_type == 'HEALING_APPLIED')
        assert heal.target_ids == (ALLY,) and heal.payload['offered'] >= 6
        rolls = [r for r in engine.rolls if r.reason.startswith('HEALING:')]
        assert rolls and rolls[-1].expression == '2d4+4'
        counts = [c.data['amount'] for c in ally.conditions.values()
                  if c.condition_id == 'condition:typed.healing_pill_benefits']
        assert counts == [1]
    responses = 0
    def choose(prompt):
        nonlocal responses
        responses += 1
        assert prompt['context']['reactor_id'] == ALLY
        return prompt['choice']['options'][0]['id'], responses == 2
    prompts = commit(source_sender(combat, table, mid, 'system:combat.hold_position'), choose)
    assert len(prompts) == 2
    engine = reload_checked(tmp_path, mid)
    modes = [e.payload['mode'] for e in engine.events if e.event_type == 'SAVE_ROLLED'
             and e.source_definition_id.startswith('test:save-')]
    assert modes == ['NORMAL', 'ADVANTAGE']
    assert not any(c.condition_id == SAINT_SAVE for c in engine.state.actors[ALLY].conditions.values())


def test_medicine_saint_ai_benefit_does_not_go_to_enemy_in_reach(monkeypatch, tmp_path):
    from combat.gate4_context import build_decision_context, build_reaction_context
    from combat.gate4_controller import LocalDeterministicController
    from combat.gate4_policy import PolicyLibrary
    combat, table, mid = fight(monkeypatch, tmp_path, talents=[ANTIDOTE], insights=[SAINT],
                               ally_at=(4, 4), foe_at=(3, 5), ai=True)
    session = combat._load_session(mid)
    controller, policies = LocalDeterministicController(), PolicyLibrary(ROOT)
    policy, _ = policies.for_actor(OWNER)
    context = build_decision_context(session.engine, policy, for_ai=True)
    candidates = tuple(c for c in context.legal_candidates if c.display_name.startswith('Medicine Saint: Administer'))
    assert candidates and all(FOE not in c.target_ids for c in candidates)
    assert {who for c in candidates for who in c.target_ids} == {OWNER, ALLY}
    choice = controller.choose_primary_action(context.model_copy(update={'legal_candidates': candidates}))
    def react(request):
        rp, _ = policies.for_actor(request['reactor_id'])
        chosen = controller.choose_reaction(build_reaction_context(session.engine, rp, request))
        return chosen.decision, chosen.record
    session.submit_intent(choice.intent, primary_decision_record=choice.record, reaction_provider=react)
    engine = reload_checked(tmp_path, mid)
    assert not any(c.condition_id in {SAINT_SAVE, 'condition:typed.save_against'}
                   for c in engine.state.actors[FOE].conditions.values())
    assert any(c.condition_id == SAINT_SAVE for who in (OWNER, ALLY)
               for c in engine.state.actors[who].conditions.values())
