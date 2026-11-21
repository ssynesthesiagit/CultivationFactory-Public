"""Native acquisition, table choices, cold reload and mechanical replay for Listen.

Runtime inputs: authority/typed_mechanics/rules_text.json,
authority/Tianxia_Typed_Mechanics_Authority_R1.json,
authority/typed_mechanics/reviewed_final.d/review_sw-thread.json.
"""

import json
import pytest
from tests.mgr_t15_listen_fixture import *  # noqa: F401,F403 shared fixture

def test_listen_requires_actual_owned_line(tmp_path):
    _, table, mid = fight(tmp_path)
    assert 'Listen Through Tension' not in names(cold(tmp_path, mid))


@pytest.mark.parametrize('skill', ['Insight', 'Perception', 'Sleight of Hand'])
def test_one_chosen_check_consumes_only_after_eligible_roll(tmp_path, skill):
    _, table, mid = fight(tmp_path)
    draw(table, mid)
    before = cold(tmp_path, mid).state.actors[P].resources[QI]
    prompts = choose(table, mid, candidate(table, mid, 'Listen Through Tension'), ('check', F))
    assert not any(set(('motion', 'handling', 'check', 'space')) == set(opts) for opts in prompts)
    e = cold(tmp_path, mid)
    assert len(grants(e)) == 1
    assert e.state.actors[P].resources[QI] == before
    assert not e.state.actors[P].bonus_action_available
    assert grants(e)[0].expires_on == 'END_OF_MARKER_NEXT_TURN'
    own_context = table.combat.decision(mid)['context']
    assert own_context['private_information'][0]['check_available'] == 1
    assert 'thread_motion' not in json.dumps(own_context['recent_events'])
    assert 'thread_handling' not in json.dumps(own_context['recent_events'])
    from combat.typed_executor import check_modes
    assert 'ADVANTAGE' not in check_modes(e.state.actors[P], 'WIS', 'Perception', engine=e)
    reach(table, mid, F)
    reach(table, mid, P)
    assert grants(cold(tmp_path, mid))
    choose(table, mid, candidate(table, mid, 'Check involving your Thread Line'), (skill, F))
    e = cold(tmp_path, mid)
    rows = [x for x in e.events if x.event_type == 'CHECK_ROLLED' and x.actor_id == P]
    assert rows[-1].payload['actor']['mode'] == 'ADVANTAGE'
    assert rows[-1].payload['skill'] == skill
    assert len(grants(e)) == 1
    assert grants(e)[0].data['benefit'] == 'space_eligible'
    assert grants(e)[0].expires_on == 'UNTIL_REMOVED'
    from combat.typed_executor import check_modes
    assert 'ADVANTAGE' not in check_modes(e.state.actors[P], 'WIS', 'Perception', engine=e)


def test_unused_grant_expires_at_next_end(tmp_path):
    _, table, mid = fight(tmp_path)
    draw(table, mid)
    choose(table, mid, candidate(table, mid, 'Listen Through Tension'), ('check', F))
    reach(table, mid, F)
    reach(table, mid, P)
    assert grants(cold(tmp_path, mid))
    send(table, mid, table.state(mid)['menu']['end_turn'])
    assert not grants(cold(tmp_path, mid))


def test_native_movement_facts_are_private_and_reset_on_stopping(tmp_path):
    combat, table, mid = fight(tmp_path)
    draw(table, mid)
    choose(table, mid, candidate(table, mid, 'Listen Through Tension'), ('motion',))
    assert private(table, mid)[0]['motion'] == 'still'
    assert table.state(mid)['private_information'] == {}
    assert private(table, mid, S) == []
    reach(table, mid, F)
    assert not combat.decision(mid)['context'].get('private_information')
    for x, expected in ((6, 'closer'), (7, 'farther')):
        e = cold(tmp_path, mid)
        step = next(c for c in e.legal_candidates() if c.kind == 'MOVE' and c.destination
                    and (c.destination.x, c.destination.y, c.destination.z) == (x, 6, 0))
        choose(table, mid, step.candidate_id)
        assert private(table, mid)[0]['motion'] == expected
        assert private(table, mid, S) == []
    send(table, mid, table.state(mid)['menu']['end_turn'])
    assert private(table, mid)[0]['motion'] == 'still'
    cold(tmp_path, mid)


def test_real_holding_and_ignoring_have_no_inferred_default(tmp_path):
    _, table, mid = fight(tmp_path)
    draw(table, mid)
    choose(table, mid, candidate(table, mid, 'Listen Through Tension'), ('handling',))
    assert private(table, mid)[0]['handling'] == 'unknown'
    assert private(table, mid)[0]['text'] == (
        'You cannot yet tell whether a1150002 is holding, cutting, or ignoring the line.')
    reach(table, mid, F)
    e = cold(tmp_path, mid)
    before = (e.state.actors[F].action_available, dict(e.state.actors[F].resources))
    choose(table, mid, candidate(table, mid, 'Thread Line: holding'))
    assert private(table, mid)[0]['handling'] == 'holding'
    e = cold(tmp_path, mid)
    assert (e.state.actors[F].action_available, dict(e.state.actors[F].resources)) == before
    from combat.ext.hand_occupancy import occupancy
    assert any(any('condition:' in occupant for occupant in owners) for owners in occupancy(e, e.state.actors[F]).values())
    choose(table, mid, candidate(table, mid, 'Thread Line: ignoring'))
    assert private(table, mid)[0]['handling'] == 'ignoring'
    assert private(table, mid, S) == []
    cold(tmp_path, mid)


def test_invisible_connection_gives_only_listener_current_space_and_ends_with_line(tmp_path):
    combat, table, mid = fight(tmp_path, foe_mids=['tianxia.talent.illusion.greater_invisibility'])
    draw(table, mid)
    reach(table, mid, F)
    choose(table, mid, candidate(table, mid, 'Greater Invisibility', F))
    reach(table, mid, P)
    e = cold(tmp_path, mid)
    from combat.target_knowledge import located, can_see
    assert not can_see(e, e.state.actors[P], e.state.actors[F])
    # Space is not a menu choice: the Invisible connection adds it automatically.
    choose(table, mid, candidate(table, mid, 'Listen Through Tension'), ('motion',))
    e = cold(tmp_path, mid)
    assert located(e, e.state.actors[P], e.state.actors[F], personal=True)
    assert not located(e, e.state.actors[P], e.state.actors[F])
    assert not can_see(e, e.state.actors[P], e.state.actors[F])
    assert not located(e, e.state.actors[S], e.state.actors[F])
    space_info = next(row for row in private(table, mid) if 'position' in row)
    assert space_info['position'] == e.state.actors[F].position.model_dump(mode='json')
    assert private(table, mid, S) == []
    context = combat.decision(mid)['context']
    context_space = next(row for row in context['private_information'] if 'position' in row)
    assert context_space['position'] == space_info['position']
    assert any(c.data['benefit'] == 'space' and c.expires_on == 'UNTIL_REMOVED' for c in grants(e))
    send(table, mid, table.state(mid)['menu']['end_turn'])
    e = cold(tmp_path, mid)
    assert not grants(e)
    assert not located(e, e.state.actors[P], e.state.actors[F])


def test_scoped_line_check_uses_generic_bonus_and_floor_hooks(monkeypatch):
    from contextlib import nullcontext
    from types import SimpleNamespace
    import combat.ext as ext
    from combat.ext import scoped_checks

    class Roller:
        def d20(self, **kwargs):
            self.modifier = kwargs['modifier']
            return SimpleNamespace(natural_result=4, total=4 + self.modifier, reason='CHECK:test',
                model_copy=lambda update: SimpleNamespace(natural_result=4, total=update['total'], reason='CHECK:test', model_dump=lambda mode='json': {'natural_result': 4, 'total': update['total'], 'reason': 'CHECK:test'}),
                model_dump=lambda mode='json': {'natural_result': 4, 'total': 4 + self.modifier, 'reason': 'CHECK:test'})

    actor = SimpleNamespace(entity_id='actor:test')
    engine = SimpleNamespace(state=SimpleNamespace(event_sequence=0), roller=Roller(), d20_scope=lambda _: nullcontext(),
        _record_roll=lambda roll: None, _append_event=lambda *a, **k: None)
    ctx = SimpleNamespace(engine=engine, actor=actor, source='test:line', intent=None,
        action=SimpleNamespace(display_name='Listen check'))
    monkeypatch.setattr(ext, 'run_strict', lambda *args: [{'line': {'label': 'Connected line'}}])
    monkeypatch.setattr(ext, 'run', lambda name, *args: [-2] if name == 'check_bonus' else [])
    floored = []
    def floor(engine_arg, actor_arg, roll, dc):
        floored.append(dc)
        return roll.model_copy({'total': 10})
    monkeypatch.setattr(ext, 'floored', floor)
    from combat import typed_executor
    monkeypatch.setattr(typed_executor, 'check_modes', lambda *args, **kwargs: set())
    from combat.ext import needle
    monkeypatch.setattr(needle, 'ask', lambda *args, **kwargs: ['line'] if 'contextual_check_subject' in args[4] else ['Perception'])
    scoped_checks.contextual_check(ctx, {'scope': 'line', 'checks': {'Perception': {'ability': 'WIS', 'bonus': 5}}})
    assert engine.roller.modifier == 3
    assert floored == [None]


def test_object_line_subject_name_is_the_connected_object(tmp_path):
    objects = [{'id': 1, 'kind': 'custom', 'name': 'Bell', 'x': 7, 'y': 5, 'blocks': False, 'ac': 10, 'hp': 30}]
    _, table, mid = fight(tmp_path, objects=objects, owner_talents=[HUNDRED])
    choose(table, mid, candidate(table, mid, 'Draw the Line: Guide (Qi Thread) (at an object)', 'object:map.1'))
    e = cold(tmp_path, mid)
    from combat.ext.thread_base_line import maintained_lines
    from combat.ext.thread_weaving import _subject_name
    rows = maintained_lines(e, e.state.actors[P])
    assert len(rows) == 1
    assert _subject_name(e, rows[0][1]) == 'Bell'


def test_object_connection_is_created_by_actual_non_damaging_thread_hit(tmp_path):
    _, table, mid = fight(tmp_path, objects=[{'id': 1, 'kind': 'custom', 'name': 'Bell',
        'x': 7, 'y': 5, 'blocks': False, 'ac': 10, 'hp': 30}])
    before = cold(tmp_path, mid).state.objects['object:map.1'].current_hp
    choose(table, mid, candidate(table, mid, 'Draw the Line: Guide (Qi Thread) (at an object)', 'object:map.1'))
    e = cold(tmp_path, mid)
    assert e.state.objects['object:map.1'].current_hp == before
    from combat.ext.thread_base_line import maintained_lines
    assert maintained_lines(e, e.state.actors[P])[0][1].object_id == 'object:map.1'
    from combat.ext.thread_common import thread_line_cells
    assert (7, 5, 0) in thread_line_cells(e, e.state.actors[P])
    choose(table, mid, candidate(table, mid, 'Listen Through Tension'), ('motion',))
    assert private(table, mid)[0]['motion'] == 'still'
    e = cold(tmp_path, mid)
    assert len(grants(e)) == 1


def test_automatic_owner_can_choose_a_source_reading_without_other_seats_facts(tmp_path):
    combat, table, mid = fight(tmp_path)
    draw(table, mid)
    cid = candidate(table, mid, 'Listen Through Tension')
    from tests.test_r4_integration import auto_candidate
    auto_candidate(combat, mid, P, cid)
    assert table.auto_step(mid, 0)['status'] == 'COMMITTED'
    e = cold(tmp_path, mid)
    assert len(grants(e)) == 1
    # The automatic default is the first printed reading offered (motion).
    assert grants(e)[0].data['benefit'] == 'motion'
    assert private(table, mid)[0]['motion'] == 'still'
    assert private(table, mid, S) == []


@pytest.mark.parametrize('ask_reactions', [False, True])
def test_off_turn_reactions_receive_only_their_own_private_readings(tmp_path, ask_reactions):
    # Draw at its legal range, then genuinely approach both reactors. The native
    # Auto plan resolves OAs without a controller; Ask creates real suggestions.
    combat, table, mid = fight(tmp_path, ask_reactions=ask_reactions)
    draw(table, mid)
    choose(table, mid, candidate(table, mid, 'Listen Through Tension'), ('motion',))
    reach(table, mid, F)
    e = cold(tmp_path, mid)
    approach = next(c for c in e.legal_candidates() if c.kind == 'MOVE' and c.destination
                    and (c.destination.x, c.destination.y, c.destination.z) == (3, 6, 0))
    choose(table, mid, approach.candidate_id)
    from combat.gate4_adapters import ManualControllerAdapter
    from combat.gate2_runtime_models import ReactionDecision
    contexts = []

    def decline(context):
        contexts.append(context)
        return ReactionDecision(checkpoint=context.checkpoint, reactor_id=context.reactor_id,
            reaction_source_id=context.reaction_source_id, selection='DECLINE')

    combat.controller = ManualControllerAdapter(lambda _: ('unexpected-primary', ()), decline)
    e = cold(tmp_path, mid)
    sequence = e.state.event_sequence
    step = next(c for c in e.legal_candidates() if c.kind == 'MOVE' and c.destination
                and (c.destination.x, c.destination.y, c.destination.z) == (4, 6, 0))
    # Actual movement provokes both adjacent enemies while F is taking its turn.
    answers = []
    for _ in range(4):
        result = send(table, mid, step.candidate_id, answers)
        if result['status'] == 'COMMITTED':
            break
        assert ask_reactions and result['status'] == 'REACTION_REQUIRED'
        cold(tmp_path, mid)
        answers.append({**result['reaction']['context'], 'selection': 'DECLINE', 'option_ids': []})
    else:
        raise AssertionError('off-turn reaction choices did not settle')
    assert {c.reactor_id for c in contexts} == ({P, S} if ask_reactions else set())
    for context in contexts:
        if context.reactor_id == P:
            assert context.private_information[0]['motion'] == 'closer'  # actual approach, before leaving reach
        else:
            assert not context.private_information
        assert 'thread_motion' not in json.dumps(context.model_dump(mode='json')['recent_events'])
    assert private(table, mid)[0]['motion'] == 'farther'
    e = cold(tmp_path, mid)
    if not ask_reactions:
        reactors = {ev.actor_id for ev in e.events if ev.sequence > sequence
                    and ev.event_type == 'ATTACK_ROLLED' and F in ev.target_ids}
        assert {P, S} <= reactors


_SOURCE_RECEIPT = False


@pytest.fixture(autouse=True)
def exact_native_source_receipt(capsys):
    """Print source bytes once, including on locally routed delayed execution."""
    global _SOURCE_RECEIPT
    if not _SOURCE_RECEIPT:
        import hashlib
        paths = ('combat/ext/__init__.py', 'combat/ext/thread_base_line.py', 'combat/ext/thread_common.py', 'combat/ext/thread_weaving.py',
                 'combat/ext/scoped_checks.py', 'combat/ext/objects.py',
                 'combat/target_knowledge.py', 'combat/private_information.py',
                 'combat/gate4_models.py', 'combat/gate4_context.py', 'combat/tabletop_service.py',
                 'tests/test_mgr_t15_listen_tension.py', 'static/play/play-client.js',
                 'static/play/play.html', 'static/tabletop/tabletop.js')
        with capsys.disabled():
            print('LISTEN_NATIVE_SOURCE_SHA256=' + json.dumps({p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() if (ROOT/p).is_file() else 'ABSENT' for p in paths}, sort_keys=True), flush=True)
        _SOURCE_RECEIPT = True


def test_foreign_line_never_satisfies_your_listen_range(tmp_path):
    _, table, mid = fight(tmp_path, peer=True)
    reach(table, mid, S)
    draw(table, mid)
    reach(table, mid, P)
    e = cold(tmp_path, mid)
    from combat.ext.thread_common import maintained_lines
    assert maintained_lines(e, e.state.actors[S])
    assert not maintained_lines(e, e.state.actors[P])
    assert 'Listen Through Tension' not in names(e)


def test_native_cutting_attempt_is_known_only_from_a_real_line_attack(tmp_path):
    _, table, mid = fight(tmp_path, foe_x=5, arm_foe=True, foe_score=2, owner_dc=50)
    mundane(table, mid)
    choose(table, mid, candidate(table, mid, 'Listen Through Tension'), ('handling',))
    e = cold(tmp_path, mid)
    obj = physical_line(e)
    assert obj.ac == 50 and obj.maximum_hp == 6
    assert not obj.flammable  # no native material fact authorizes ignition
    assert private(table, mid)[0]['handling'] == 'unknown'
    advance(table, mid, F)
    choose(table, mid, candidate(table, mid, 'Thread Line: holding'))
    assert private(table, mid)[0]['handling'] == 'holding'
    choose(table, mid, candidate(table, mid, 'Attack an object', obj.object_id))
    e = cold(tmp_path, mid)
    roll = next(x for x in reversed(e.events) if x.event_type == 'ATTACK_ROLLED' and x.actor_id == F)
    assert roll.target_ids == (obj.object_id,)
    assert not roll.payload['provisional_hit']
    assert private(table, mid)[0]['handling'] == 'cutting'
    assert private(table, mid, S) == []
    assert not e.state.objects[obj.object_id].destroyed
    choose(table, mid, table.state(mid)['menu']['end_turn'])
    assert private(table, mid)[0]['handling'] == 'holding'


def test_space_survives_native_upkeep_then_actual_line_destruction_ends_it(tmp_path):
    _, table, mid = fight(tmp_path, foe_x=5, arm_foe=True, foe_score=30,
        foe_mids=['tianxia.talent.illusion.greater_invisibility'], owner_talents=[HUNDRED])
    mundane(table, mid)
    choose(table, mid, candidate(table, mid, 'Listen Through Tension'), ('check',))
    original = physical_line(cold(tmp_path, mid)).object_id
    grant_line = grants(cold(tmp_path, mid))[0].data['line_id']
    advance(table, mid, F)
    choose(table, mid, candidate(table, mid, 'Greater Invisibility', F))
    # P's Action refreshes next turn; the printed Listen check still lasts to
    # the end of that turn, so using it there is a legal sequence.
    advance(table, mid, P, keep=True)
    assert checks(cold(tmp_path, mid))
    choose(table, mid, candidate(table, mid, 'Check involving your Thread Line'), ('Perception', F))
    e = cold(tmp_path, mid)
    assert not checks(e)  # the printed check benefit is spent
    assert [c.data['line_id'] for c in receipts(e)] == [grant_line]
    assert receipts(e)[0].expires_on == 'UNTIL_REMOVED'
    assert any(c.data['benefit'] == 'space' and c.data['line_id'] == grant_line for c in grants(e))
    assert not e.state.objects[original].destroyed
    choose(table, mid, table.state(mid)['menu']['end_turn'])
    e = cold(tmp_path, mid)
    assert grants(e)
    assert not e.state.objects[original].destroyed
    from combat.target_knowledge import located, can_see
    assert located(e, e.state.actors[P], e.state.actors[F], personal=True)
    assert not located(e, e.state.actors[P], e.state.actors[F])
    assert not can_see(e, e.state.actors[P], e.state.actors[F])
    space_info = next(row for row in private(table, mid) if 'position' in row)
    assert space_info['position'] == e.state.actors[F].position.model_dump(mode='json')
    advance(table, mid, F)
    choose(table, mid, candidate(table, mid, 'Attack an object', original))
    e = cold(tmp_path, mid)
    assert e.state.objects[original].destroyed
    assert e.state.objects[original].current_hp == 0
    assert not grants(e)
    assert not located(e, e.state.actors[P], e.state.actors[F])
    assert not can_see(e, e.state.actors[P], e.state.actors[F])
    assert private(table, mid) == []


@pytest.mark.parametrize('benefit', ['motion', 'handling', 'check'])
def test_reading_clock_expires_while_natively_maintained_line_still_exists(tmp_path, benefit):
    _, table, mid = fight(tmp_path, owner_talents=[HUNDRED])
    draw(table, mid)
    choose(table, mid, candidate(table, mid, 'Listen Through Tension'), (benefit,))
    from combat.ext.thread_common import maintained_lines
    original = maintained_lines(cold(tmp_path, mid), cold(tmp_path, mid).state.actors[P])[0][0]
    advance(table, mid, F)
    advance(table, mid, P, keep=True)
    e = cold(tmp_path, mid)
    assert grants(e)
    assert maintained_lines(e, e.state.actors[P])[0][0] == original
    choose(table, mid, table.state(mid)['menu']['end_turn'])
    e = cold(tmp_path, mid)
    assert maintained_lines(e, e.state.actors[P])[0][0] == original
    assert not grants(e)  # own recognized deadline, not loss of the line


def test_later_listen_use_does_not_end_an_earlier_printed_reading(tmp_path):
    _, table, mid = fight(tmp_path, owner_talents=[HUNDRED])
    draw(table, mid)
    choose(table, mid, candidate(table, mid, 'Listen Through Tension'), ('handling',))
    first = grants(cold(tmp_path, mid))[0].instance_id
    advance(table, mid, F)
    advance(table, mid, P, keep=True)
    choose(table, mid, candidate(table, mid, 'Listen Through Tension'), ('motion',))
    e = cold(tmp_path, mid)
    assert [c.data['benefit'] for c in grants(e)] == ['handling', 'motion']
    assert any(c.instance_id == first for c in grants(e))
    # A later use grants its selected reading without cancelling the
    # earlier handling reading.
    assert not e.state.actors[P].bonus_action_available


def test_object_motion_comes_from_actual_native_object_handling(tmp_path):
    from combat.ext.needle import cell_id
    from combat.gate2_runtime_models import Position
    _, table, mid = fight(tmp_path, foe_mids=['tianxia.talent.puppetry.little_servant_s_errand'],
        objects=[{'id': 1, 'kind': 'custom', 'name': 'Bell', 'x': 7, 'y': 5,
                  'weight_lb': 10, 'blocks': False, 'ac': 10, 'hp': 30}])
    choose(table, mid, candidate(table, mid, 'Draw the Line: Guide (Qi Thread) (at an object)', 'object:map.1'))
    choose(table, mid, candidate(table, mid, 'Listen Through Tension'), ('motion',))
    advance(table, mid, F)
    choose(table, mid, candidate(table, mid, 'Thread the Object: move object', 'object:map.1'),
           (cell_id(Position(x=6, y=5)),))
    e = cold(tmp_path, mid)
    assert e.state.objects['object:map.1'].position == Position(x=6, y=5)
    assert private(table, mid)[0]['motion'] == 'closer'
    assert private(table, mid, S) == []
    # Stop at the mover's actual end, before advancing past a possible listener
    # turn in initiative order and accidentally expiring the reading itself.
    choose(table, mid, table.state(mid)['menu']['end_turn'])
    assert private(table, mid)[0]['motion'] == 'still'
    advance(table, mid, S)
    context = table.combat.decision(mid)['context']
    assert not context.get('private_information')
    assert 'thread_object_position' not in json.dumps(context)
    assert 'thread_motion' not in json.dumps(context)


def test_choose_one_actual_line_when_creature_and_object_lines_are_both_maintained(tmp_path):
    _, table, mid = fight(tmp_path, owner_talents=[HUNDRED], objects=[
        {'id': 1, 'kind': 'custom', 'name': 'Bell', 'x': 7, 'y': 5, 'blocks': False, 'ac': 10, 'hp': 30}])
    draw(table, mid)
    advance(table, mid, F)
    advance(table, mid, P, keep=True)
    choose(table, mid, candidate(table, mid, 'Draw the Line: Guide (Qi Thread) (at an object)', 'object:map.1'))
    from combat.ext.thread_common import maintained_lines
    e = cold(tmp_path, mid)
    lines = maintained_lines(e, e.state.actors[P])
    assert len(lines) == 2
    creature_line = next(iid for iid, target, _, _ in lines if getattr(target, 'entity_id', None) == F)
    object_line = next(iid for iid, target, _, _ in lines if getattr(target, 'object_id', None) == 'object:map.1')
    # The object row is encountered first because its marker is on the owner;
    # deliberately choose the other line, not the first result in a query.
    assert lines[0][0] == object_line
    prompts = choose(table, mid, candidate(table, mid, 'Listen Through Tension'), (creature_line, 'motion'))
    assert any(set(opts) == {creature_line, object_line} for opts in prompts)
    assert len(grants(cold(tmp_path, mid))) == 1
    assert private(table, mid)[0]['line_id'] == creature_line
    advance(table, mid, F)
    e = cold(tmp_path, mid)
    step = next(c for c in e.legal_candidates() if c.kind == 'MOVE' and c.destination
                and (c.destination.x, c.destination.y, c.destination.z) == (6, 6, 0))
    choose(table, mid, step.candidate_id)
    assert private(table, mid)[0]['motion'] == 'closer'
    assert len(private(table, mid)) == 1
    cold(tmp_path, mid)


def test_requested_benefit_must_be_offered_not_silently_replaced(tmp_path):
    # Regression for the fixture fallback: an absent requested benefit used to
    # be replaced by the first option, so stale tests still passed.
    _, table, mid = fight(tmp_path)
    draw(table, mid)
    with pytest.raises(AssertionError, match='not offered'):
        choose(table, mid, candidate(table, mid, 'Listen Through Tension'), ('space',))


def test_consumed_listen_check_replays_its_receipt_expiry(tmp_path):
    # Regression: the consumed check used to change the receipt's expiry by
    # direct assignment, so the cold replay hash did not match the committed state.
    _, table, mid = fight(tmp_path)
    draw(table, mid)
    choose(table, mid, candidate(table, mid, 'Listen Through Tension'), ('check', F))
    reach(table, mid, F)
    reach(table, mid, P)
    choose(table, mid, candidate(table, mid, 'Check involving your Thread Line'), ('Insight', F))
    e = cold(tmp_path, mid)
    (receipt,) = receipts(e)
    assert receipt.expires_on == 'UNTIL_REMOVED'
    assert receipt.data['benefit'] == 'space_eligible'
    assert not checks(e)
