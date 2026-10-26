"""Alchemy fix round r1: the review's numbered findings, each with a service regression.

Every case runs a real saved CombatService/Table transaction, commits through the session and
reloads cold (verify + mechanical replay), so persistence, expiry and decision routing are proved
at the boundary a player actually uses -- not at a helper's return value.
"""
import pytest

from combat.gate5_service import CombatService
from combat.gate2_runtime_models import ActionIntent
from combat.tabletop import ButtonStore
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.test_hidden_targeting import turn
from tests.test_lock2_persistence import act
from tests.r10_fixup_support import cast_sender, commit
from tests.test_a2_alchemy import (ALLY, ANTIDOTE, BASE, CALM, CP, FOE, HEAL, OWNER, POISONED, SAINT,
                                   SAINT_SAVE, STOMACH, fight, poison_setup, reload_checked, source_sender)

SAVE_AGAINST = 'condition:typed.save_against'
BENEFITS = 'condition:typed.healing_pill_benefits'


def wound(engine, who, amount=30, source='test:wound'):
    engine._commit_damage(engine.state.actors[who], amount, 'FIRE', source, FOE,
                          engine._active_intent, reaction_depth=0)


# ------------------------------------------------------------------ finding 1: opposed saves

def opposed_check(persistent, following, count=1):
    """Drive a real opposed check whose defender must make a Constitution saving throw.

    The subject carries two typed save_against grants at once: a persistent one that lasts the
    fight and a one-use "next save" one. The typed `save` hook settles both (and consumes the
    one-use grant) before the native bridge is consulted, so the two modes must cancel.
    """
    def prepare(engine, kind, record):
        if kind != 'HOLD_POSITION_COMMITTED' or record.get('actor_id') != OWNER:
            return
        defender = engine.state.actors.get(ALLY)
        if defender is None or defender.turn_flags.get('test_opposed_ready'):
            return
        defender.turn_flags['test_opposed_ready'] = True
        engine._apply_condition(defender, SAVE_AGAINST, 'test:persistent', FOE, expires_on='UNTIL_REMOVED',
                                data={'rule': {'save_against': {'mode': persistent, 'abilities': ['CON'],
                                                                'next': False}}})
        engine._apply_condition(defender, SAVE_AGAINST, 'test:one_use', FOE, expires_on='UNTIL_REMOVED',
                                data={'rule': {'save_against': {'mode': following, 'abilities': ['CON'],
                                                                'next': True}}})
        from combat.typed_executor import Context, resolve_opposed_check
        action = next(a for a in engine.action_catalog.values()
                      if a.owner_id == OWNER and a.display_name == 'Field Formula: Corrosive Dregs')
        for _ in range(count):
            ctx = Context(engine, engine.state.actors[OWNER], action, engine._active_intent,
                          action.parameters['typed'], [defender], defender, explicit_self_recipient=True)
            resolve_opposed_check(ctx, defender, {'kind': 'check', 'ability': 'STR'},
                                  {'kind': 'save', 'ability': 'CON'})
    return prepare


@pytest.mark.parametrize('persistent,following', [('ADVANTAGE', 'DISADVANTAGE'), ('DISADVANTAGE', 'ADVANTAGE')])
def test_opposed_save_keeps_mixed_persistent_and_next_grant_cancellation(monkeypatch, tmp_path, persistent, following):
    """Review finding 1: the native bridge must not resurrect one half of a cancelled pair.

    Both grants reach the defender, so the intended roll is a NORMAL one. Before the fix the
    opposed path passed only a collapsed mode, the surviving persistent grant was re-read on its
    own, and an unrelated creature's contested save silently rolled with Advantage (or
    Disadvantage).
    """
    combat, table, mid = fight(monkeypatch, tmp_path, prepare=opposed_check(persistent, following))
    assert act(table, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
    engine = reload_checked(tmp_path, mid)
    saves = [e for e in engine.events if e.event_type == 'SAVE_ROLLED' and e.actor_id == ALLY]
    assert len(saves) == 1, 'the opposed save must actually have been rolled'
    assert saves[0].payload['mode'] == 'NORMAL', 'Advantage and Disadvantage must cancel on an opposed save'
    held = [c for c in engine.state.actors[ALLY].conditions.values() if c.condition_id == SAVE_AGAINST]
    assert [c.source_definition_id for c in held] == ['test:persistent'], \
        'the one-use grant is spent, the persistent one survives for later saves'


def test_opposed_save_spends_exactly_one_use_grant_and_leaves_persistent(monkeypatch, tmp_path):
    """Two opposed saves in a row: the one-use grant is spent exactly once."""
    combat, table, mid = fight(monkeypatch, tmp_path,
                               prepare=opposed_check('ADVANTAGE', 'DISADVANTAGE', count=2))
    assert act(table, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
    engine = reload_checked(tmp_path, mid)
    saves = [e for e in engine.events if e.event_type == 'SAVE_ROLLED' and e.actor_id == ALLY]
    assert [s.payload['mode'] for s in saves] == ['NORMAL', 'ADVANTAGE'], \
        'the persistent grant alone applies to the second save; the one-use grant is gone'
    held = [c for c in engine.state.actors[ALLY].conditions.values() if c.condition_id == SAVE_AGAINST]
    assert [c.source_definition_id for c in held] == ['test:persistent']


# ------------------------------------------------------------------ finding 2: what the player is told

def equal_dc_poisons(monkeypatch, tmp_path):
    """Two poisons whose save is identical in every respect a player could act on."""
    def prepare(engine, kind, record):
        if kind != 'HOLD_POSITION_COMMITTED' or record.get('actor_id') != OWNER:
            return
        target = engine.state.actors[ALLY]
        if target.turn_flags.get('test_poisons_ready'):
            return
        target.turn_flags['test_poisons_ready'] = True
        clocks = (('Sleeping Dart', 'UNTIL_REMOVED'),
                  ('Bottled Rot', f'START_OF_TURN_AT:{FOE}:{engine.state.actors[FOE].turns_started + 1}'))
        for name, expires in clocks:
            engine._apply_condition(target, POISONED, f'test:poison:{name}', FOE, expires_on=expires,
                data={'label': name, 'origin_save': {'ability': 'CON', 'dc': 12},
                      'repeat_save': {'ability': 'CON', 'dc': 12, 'when': 'end'}})
    return prepare


def test_equal_dc_poison_options_are_distinguishable(monkeypatch, tmp_path):
    """Review finding 2 / checklist 13: equal-DC poisons must not be the same button.

    Both are Poisoned, both are Constitution, both DC 12. The label has to say which poison is on
    offer and how long it lasts, and must never leak an engine instance id.
    """
    combat, table, mid = fight(monkeypatch, tmp_path, prepare=equal_dc_poisons(monkeypatch, tmp_path))
    assert act(table, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
    prompts = commit(cast_sender(combat, table, mid, 'Field Formula: Medicinal Smoke', target=ALLY),
                     lambda p: (p['choice']['options'][0]['id'], True))
    assert len(prompts) == 1
    labels = [o['label'] for o in prompts[0]['choice']['options']]
    assert len(labels) == 2, 'both poisons are on offer'
    assert len(set(labels)) == 2, f'equal-DC poisons must not share a label: {labels}'
    assert all('Sleeping Dart' in l or 'Bottled Rot' in l for l in labels), labels
    assert any('Sleeping Dart' in l and 'until removed' in l for l in labels), labels
    bottled = next(l for l in labels if 'Bottled Rot' in l)
    assert "until the start of Enemy's next turn" in bottled, bottled
    for label in labels:
        assert not any(part in label for part in ('condition:', ':typed', FOE, 'START_OF_', 'TURN_AT', 'turns_started')), \
            f'internal id or clock leaked: {label}'
    assert ALLY in reload_checked(tmp_path, mid).typed_ask_reactors, \
        'a persisted poisoned beneficiary is enrolled for an AI-turn recheck prompt'


def medicine_saint_saving(engine, action_name='Field Formula: Corrosive Dregs', ability='CON', dc=50):
    """A real incoming save, caused by a real compiled action the recipient can be shown."""
    action = next(a for a in engine.action_catalog.values() if a.display_name == action_name)
    engine._roll_save(engine.state.actors[ALLY], ability, dc, action.source_definition_id,
                      roll_context={'source_actor_id': FOE, 'named': ['poisoned']})
    return action.source_definition_id


def test_medicine_saint_prompt_names_the_incoming_save_action(monkeypatch, tmp_path):
    """Review finding 2: the question must name the effect being saved against.

    The renderer derives its action only from explicit trigger metadata, so the choice has to
    carry the actual save source/actor (including for a nested reaction), not just the pill.
    """
    sources = []

    def incoming(engine, kind, record):
        if kind != 'HOLD_POSITION_COMMITTED' or record.get('actor_id') != OWNER:
            return
        if engine.state.actors[OWNER].turn_flags.get('test_prepared'):
            sources.append(medicine_saint_saving(engine))
        else:
            engine.state.actors[OWNER].turn_flags['test_prepared'] = True
            wound(engine, ALLY)
    combat, table, mid = fight(monkeypatch, tmp_path, talents=[HEAL], insights=[SAINT],
                               ally_at=(4, 4), prepare=incoming)
    assert act(table, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
    commit(cast_sender(combat, table, mid, 'Medicine Saint: Administer Healing Pill', target=ALLY), lambda p: ())
    assert ALLY in combat._load_session(mid).engine.typed_ask_reactors, \
        'the persisted Medicine Saint grant enrolls its beneficiary for a later AI-turn save'
    seen = []

    def choose(prompt):
        seen.append(prompt)
        return prompt['choice']['options'][0]['id'], True
    prompts = commit(source_sender(combat, table, mid, 'system:combat.hold_position'), choose)
    assert seen, 'the beneficiary must be asked about the save'
    said = str(seen[0].get('moment') or '') + ' ' + str(seen[0].get('trigger') or '')
    assert 'Constitution' in said and 'DC 50' in said, said
    assert seen[0]['context']['reactor_id'] == ALLY, seen[0]['context']
    # The named action is the one actually causing this save, not the outer turn's action.
    assert seen[0]['action'] == 'Field Formula: Corrosive Dregs', seen[0]['action']
    assert sources and sources[-1].startswith('action:typed.'), sources
    assert 'Field Formula: Corrosive Dregs' in said, said
    assert seen[0]['trigger_actor'] == 'Enemy', seen[0]
    reload_checked(tmp_path, mid)


# ------------------------------------------------------------------ finding 3: claimed contracts

def test_unused_medicine_saint_benefit_expires_at_the_beneficiary_next_turn(monkeypatch, tmp_path):
    """An administration whose benefit is never spent must not outlive the printed lifetime."""
    combat, table, mid = fight(monkeypatch, tmp_path, talents=[HEAL], insights=[SAINT], ally_at=(4, 4))
    assert act(table, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
    commit(cast_sender(combat, table, mid, 'Medicine Saint: Administer Healing Pill', target=ALLY), lambda p: ())
    assert any(c.condition_id == SAINT_SAVE for c in reload_checked(tmp_path, mid).state.actors[ALLY].conditions.values())
    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    turn(table, mid, ALLY)
    assert any(c.condition_id == SAINT_SAVE
               for c in reload_checked(tmp_path, mid).state.actors[ALLY].conditions.values()), \
        'it lasts through the beneficiary\'s own next turn'
    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    turn(table, mid, OWNER)
    assert not any(c.condition_id == SAINT_SAVE
                   for c in reload_checked(tmp_path, mid).state.actors[ALLY].conditions.values()), \
        'an unused benefit ends with the beneficiary\'s next turn'


def test_medicine_saint_keeps_the_optional_benefit_when_advantage_is_forbidden(monkeypatch, tmp_path):
    """A creature that cannot benefit from Advantage keeps the pill instead of losing it."""
    def incoming(engine, kind, record):
        if kind != 'HOLD_POSITION_COMMITTED' or record.get('actor_id') != OWNER:
            return
        owner = engine.state.actors[OWNER]
        if owner.turn_flags.get('test_prepared'):
            medicine_saint_saving(engine)
        else:
            owner.turn_flags['test_prepared'] = True
            engine._apply_condition(engine.state.actors[ALLY], 'condition:typed.test_save_limit',
                                    'test:no-advantage', FOE, expires_on='UNTIL_REMOVED',
                                    data={'rule': {'no_save_advantage': ['CON']}})
            wound(engine, ALLY)
    combat, table, mid = fight(monkeypatch, tmp_path, talents=[HEAL], insights=[SAINT],
                               ally_at=(4, 4), prepare=incoming)
    assert act(table, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
    commit(cast_sender(combat, table, mid, 'Medicine Saint: Administer Healing Pill', target=ALLY), lambda p: ())
    prompts = commit(source_sender(combat, table, mid, 'system:combat.hold_position'),
                     lambda p: (p['choice']['options'][0]['id'], True))
    assert not prompts, 'the beneficiary is not asked to spend what it cannot use'
    engine = reload_checked(tmp_path, mid)
    saves = [e for e in engine.events if e.event_type == 'SAVE_ROLLED'
             and e.actor_id == ALLY and e.source_definition_id.startswith('action:typed.')]
    assert len(saves) == 1 and saves[0].payload['mode'] == 'NORMAL'
    assert any(c.condition_id == SAINT_SAVE for c in engine.state.actors[ALLY].conditions.values()), \
        'the benefit is kept for a later save'


def test_healing_pill_cap_is_shared_across_administrators_and_ordinary_use(monkeypatch, tmp_path):
    """The printed benefits limit is one pool, counted on the recipient whoever administers."""
    def prepare(engine, kind, record):
        if kind != 'HOLD_POSITION_COMMITTED' or record.get('actor_id') != OWNER:
            return
        ally = engine.state.actors[ALLY]
        # The pool is stored on the recipient, so a second administrator's pill draws on the
        # same count rather than a private one. Seed it one short of the printed limit, once.
        if not any(c.condition_id == BENEFITS for c in ally.conditions.values()):
            engine._apply_condition(ally, BENEFITS, 'test:other-alchemist', FOE, expires_on='UNTIL_REMOVED',
                                    data={'amount': int(ally.proficiency_bonus) - 1,
                                          'label': 'Healing Pill benefits since Long Rest'})
        wound(engine, ALLY)
    combat, table, mid = fight(monkeypatch, tmp_path, talents=[HEAL], insights=[SAINT],
                               ally_at=(4, 4), prepare=prepare)
    assert act(table, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
    commit(cast_sender(combat, table, mid, 'Medicine Saint: Administer Healing Pill', target=ALLY), lambda p: ())
    # The last benefit of the allowance is spent, and the pool is replaced, not doubled.
    engine = reload_checked(tmp_path, mid)
    assert any(c.condition_id == BENEFITS for c in engine.state.actors[ALLY].conditions.values())
    healed = engine.state.actors[ALLY].current_hp
    assert healed > 370, f'the final allowed pill must still heal: {healed}'
    # The pool is now spent for everyone: a fresh administration restores nothing.
    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    turn(table, mid, OWNER)
    before = combat._load_session(mid).engine.state.actors[ALLY].current_hp
    commit(cast_sender(combat, table, mid, 'Medicine Saint: Administer Healing Pill', target=ALLY), lambda p: ())
    engine = reload_checked(tmp_path, mid)
    assert engine.state.actors[ALLY].current_hp == before, \
        'the shared benefits limit stops healing by a different administrator too'



def test_ai_administrator_can_target_a_manual_beneficiary(monkeypatch, tmp_path):
    """A computer-controlled administrator administers to a MANUAL ally, never to itself or the enemy.

    The automatic administrator's legal target set includes its ally and excludes enemies.
    """
    def prepare(engine, kind, record):
        if kind == 'HOLD_POSITION_COMMITTED' and record.get('actor_id') == OWNER:
            wound(engine, ALLY)
    combat, table, mid = fight(monkeypatch, tmp_path, talents=[HEAL], insights=[SAINT],
                               ally_at=(4, 4), ai=True, prepare=prepare)
    from combat.gate4_context import build_decision_context, build_reaction_context
    from combat.gate4_controller import LocalDeterministicController
    from combat.gate4_policy import PolicyLibrary
    controller, policies = LocalDeterministicController(), PolicyLibrary(ROOT)
    session = combat._load_session(mid)
    context = build_decision_context(session.engine, policies.for_actor(OWNER)[0], for_ai=True)
    offered = tuple(c for c in context.legal_candidates
                    if c.display_name == 'Medicine Saint: Administer Healing Pill')
    assert offered, 'the AI administration is offered'
    assert all(FOE not in c.target_ids for c in offered), 'the AI never administers to the enemy'
    candidates = tuple(c for c in offered if ALLY in c.target_ids)
    assert candidates, 'the MANUAL ally is an offered recipient'
    choice = controller.choose_primary_action(context.model_copy(update={'legal_candidates': candidates}))

    def react(request):
        policy, _ = policies.for_actor(str(request['reactor_id']))
        answered = controller.choose_reaction(build_reaction_context(session.engine, policy, request))
        return answered.decision, answered.record
    session.submit_intent(choice.intent, primary_decision_record=choice.record, reaction_provider=react)
    engine = reload_checked(tmp_path, mid)
    # The benefit belongs to the MANUAL recipient; the AI administrator and the enemy get nothing.
    assert any(c.condition_id == SAINT_SAVE for c in engine.state.actors[ALLY].conditions.values())
    assert not any(c.condition_id == SAINT_SAVE for c in engine.state.actors[OWNER].conditions.values()), \
        'the computer-controlled administrator never takes the benefit for itself'
    assert not any(c.condition_id == SAINT_SAVE for c in engine.state.actors[FOE].conditions.values())


def test_local_step_pauses_for_manual_medicine_saint_beneficiary(monkeypatch, tmp_path):
    """An AI turn must park at the beneficiary's live save decision, then commit and reload it."""
    def incoming(engine, kind, record):
        if kind == 'HOLD_POSITION_COMMITTED' and record.get('actor_id') == OWNER:
            medicine_saint_saving(engine)

    combat, table, mid = fight(monkeypatch, tmp_path, talents=[HEAL], insights=[SAINT],
                               ally_at=(4, 4), ai=True, prepare=incoming)
    session = combat._load_session(mid)
    candidates = combat._legal_candidates(session, knowledge_only=True)
    administer = next(c for c in candidates
                      if c.display_name == 'Medicine Saint: Administer Healing Pill' and ALLY in c.target_ids)
    session.submit_intent(ActionIntent(intent_id='r3-administer', decision_id=administer.decision_id,
        candidate_id=administer.candidate_id, state_version=administer.state_version,
        actor_id=OWNER, target_ids=administer.target_ids), primary_decision_record=None,
        reaction_provider=lambda request: None)
    assert any(c.condition_id == SAINT_SAVE for c in combat._load_session(mid).engine.state.actors[ALLY].conditions.values())
    from combat import ext
    held = next(c for c in combat._load_session(mid).engine.state.actors[ALLY].conditions.values()
                if c.condition_id == SAINT_SAVE)
    assert True in ext.run('condition_choice_owner', combat._load_session(mid).engine,
                           combat._load_session(mid).engine.state.actors[ALLY], held), \
        'the plug-in explicitly owns this persisted choice even if another feature enrolls the fighter'

    # The Bonus Action leaves the AI administrator's primary action available. Force its ordinary legal
    # Hold Position choice so the fixture raises the beneficiary's save during this Local Auto action.
    original_choose = combat.controller.choose_primary_action
    def choose_hold(context):
        hold = next(c for c in context.legal_candidates if c.display_name == 'Hold position')
        return original_choose(context.model_copy(update={'legal_candidates': (hold,)}))
    monkeypatch.setattr(combat.controller, 'choose_primary_action', choose_hold)

    paused = combat.local_step(mid)
    assert paused['status'] == 'AWAITING_REACTION', paused
    prompt = paused['reaction_context']
    assert prompt['reactor_id'] == ALLY, prompt
    from combat.gate4_context import build_reaction_context
    from combat.gate4_controller import LocalDeterministicController
    policy, _ = combat.policies.for_actor(ALLY)
    context = build_reaction_context(combat._load_session(mid).engine, policy, prompt)
    answer = LocalDeterministicController().choose_reaction(context)
    resumed = combat.local_step(mid, reactions=[answer.decision.model_dump(mode='json', by_alias=True)])
    assert resumed['status'] == 'COMMITTED', resumed
    engine = reload_checked(tmp_path, mid)
    assert not any(c.condition_id == SAINT_SAVE for c in engine.state.actors[ALLY].conditions.values())


def test_local_step_pauses_for_manual_poison_beneficiary(monkeypatch, tmp_path):
    """A poisoned MANUAL fighter is asked before an AI actor uses Medicinal Smoke."""
    def seed_poison(engine, kind, record):
        if kind != 'HOLD_POSITION_COMMITTED' or record.get('actor_id') != OWNER:
            return
        target = engine.state.actors[ALLY]
        if target.turn_flags.get('r3_poison_seeded'):
            return
        target.turn_flags['r3_poison_seeded'] = True
        engine._apply_condition(target, POISONED, 'test:r3:smoke-poison', FOE, expires_on='UNTIL_REMOVED',
            data={'label': 'Bitter Draft', 'origin_save': {'ability': 'CON', 'dc': 12},
                  'repeat_save': {'ability': 'CON', 'dc': 12, 'when': 'end'}})

    combat, table, mid = fight(monkeypatch, tmp_path, ai=True, prepare=seed_poison,
                               ally_at=(4, 4), foe_at=(6, 4))

    def submit(candidate, tag):
        session = combat._load_session(mid)
        session.submit_intent(ActionIntent(intent_id=tag, decision_id=candidate.decision_id,
            candidate_id=candidate.candidate_id, state_version=candidate.state_version,
            actor_id=candidate.actor_id, target_ids=candidate.target_ids),
            primary_decision_record=None, reaction_provider=lambda request: None)

    # Seed a real persisted poison by accepting a real action, then advance initiative using
    # session intent transport because the AI seat cannot be advanced by the human table buttons.
    session = combat._load_session(mid)
    current = combat._legal_candidates(session, knowledge_only=True)
    submit(next(c for c in current if c.display_name == 'Hold position'), 'r3-seed-poison')
    assert any(c.condition_id == POISONED for c in combat._load_session(mid).engine.state.actors[ALLY].conditions.values())
    engine = combat._load_session(mid).engine
    from combat.ext.alchemy_field_effects import poison_choice_reactors
    assert ALLY in poison_choice_reactors(engine), 'the Alchemy seam identifies this poison recheck beneficiary'
    first_turn = combat._load_session(mid).engine.state.actors[OWNER].turns_started
    for index in range(12):
        session = combat._load_session(mid)
        engine = session.engine
        if engine.state.actors[OWNER].turns_started > first_turn:
            break
        candidates = combat._legal_candidates(session, knowledge_only=True)
        end = next(c for c in candidates if c.display_name == 'End turn')
        submit(end, f'r3-end-{index}')
    assert combat._load_session(mid).engine.state.actors[OWNER].turns_started > first_turn

    original_choose = combat.controller.choose_primary_action
    def choose_smoke(context):
        smoke = tuple(c for c in context.legal_candidates
                      if c.display_name == 'Field Formula: Medicinal Smoke' and ALLY in c.target_ids)
        assert smoke, 'the AI must have a legal smoke recheck action against the poisoned ally'
        return original_choose(context.model_copy(update={'legal_candidates': smoke}))
    monkeypatch.setattr(combat.controller, 'choose_primary_action', choose_smoke)
    paused = combat.local_step(mid)
    assert paused['status'] == 'AWAITING_REACTION', paused
    assert paused['reaction_context']['reactor_id'] == ALLY, paused['reaction_context']
    from combat.gate4_context import build_reaction_context
    from combat.gate4_controller import LocalDeterministicController
    policy, _ = combat.policies.for_actor(ALLY)
    context = build_reaction_context(combat._load_session(mid).engine, policy, paused['reaction_context'])
    answer = LocalDeterministicController().choose_reaction(context)
    resumed = combat.local_step(mid, reactions=[answer.decision.model_dump(mode='json', by_alias=True)])
    assert resumed['status'] == 'COMMITTED', resumed
    engine = reload_checked(tmp_path, mid)
    assert any(e.event_type == 'SAVE_ROLLED' and e.actor_id == ALLY for e in engine.events), \
        'resuming the AI turn executes the selected beneficiary recheck'
