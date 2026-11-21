"""Table-driving helpers shared by the Void Sphere test suites.

Used by test_auto91_void and test_auto133_void. Extracted from the Stars,
Metal and Destruction suites without changing their behavior; the internal
prompt resolver is renamed. Keep this module helper-only so borrowing a table
driver does not import unrelated runnable tests and ability dependencies.
"""
from combat.gate4_adapters import ManualControllerAdapter
from tests.auto_worker1_support import act, reload


def turn(table, mid, actor_id):
    """Advance the table's turn order until actor_id is the one to act."""
    for _ in range(4):
        if table.state(mid)['menu']['actor_id'] == actor_id:
            return
        _resolve_choices(lambda answers: act(table, mid, 'end', answers))
    raise AssertionError('turn did not advance')


def _resolve_choices(send, picks=None):
    """Use the first offered option, or accept a reaction without a choice."""
    answers, prompts = [], []
    for _ in range(12):
        result = send(answers)
        if result['status'] != 'REACTION_REQUIRED':
            assert result['status'] == 'COMMITTED', result
            return result, prompts
        p = result['reaction']
        prompts.append(p)
        ids = [o['id'] for o in (p.get('choice') or {}).get('options', [])]
        chosen = (picks or {}).get(p['context']['reaction_source_id'], ids[:1])
        answers.append({**p['context'], 'selection': 'USE' if chosen or not p.get('choice') else 'DECLINE',
                        'option_ids': chosen})
    raise AssertionError('too many choices')


def cell_send(table, mid, label, xy):
    """A send callable that uses the named action aimed at one board cell."""
    def send(answers):
        state = table.state(mid)
        menu = state['menu']
        cid = next(o['candidate_id'] for g in menu['actions'] if g['label'] == label for o in g['options']
            if o.get('destination') == {'x': xy[0], 'y': xy[1]})
        return table.act(mid, cid, menu['decision_id'], menu['state_version'], state['last_sequence'], answers)
    return send


def cell_sender(c, t, m, label, xy, ai):
    """cell_send, or the same move made by the AI when ai is true."""
    if not ai:
        return cell_send(t, m, label, xy)
    menu = t.state(m)['menu']
    cid = next(o['candidate_id'] for g in menu['actions'] if g['label'] == label for o in g['options']
               if o.get('destination') == dict(x=xy[0], y=xy[1]))
    real = c.controller
    class Controller:
        def choose_primary_action(self, context):
            return ManualControllerAdapter(lambda _: (cid, ())).choose_primary_action(context)
        def __getattr__(self, name):
            return getattr(real, name)
    c.controller = Controller()
    c.set_controller_mode(m, actor_id=menu['actor_id'], controller_mode='LOCAL_AUTO')
    return lambda answers: t.auto_step(m, t.state(m)['last_sequence'], answers)


def ascend(combat, table, mid, actor_id):
    """Take the printed step up onto a flying creature's own square (z 1)."""
    state = table.state(mid)
    actor = reload(combat, mid).state.actors[actor_id]
    candidate = next(c for c in combat._load_session(mid).engine.legal_candidates()
        if c.destination is not None and c.metadata.get('movement_mode') == 'fly'
        and (c.destination.x, c.destination.y, c.destination.z) == (actor.position.x, actor.position.y, 1))
    menu = state['menu']
    return table.act(mid, candidate.candidate_id, menu['decision_id'], menu['state_version'], state['last_sequence'], [])


def settle(send, picker=None):
    """Answer a prompt chain with the option a test names, or the first offered."""
    answers, prompts = ([], [])
    for _ in range(20):
        result = send(answers)
        if result['status'] != 'REACTION_REQUIRED':
            assert result['status'] == 'COMMITTED', result
            return (result, prompts)
        p = result['reaction']
        prompts.append(p)
        choice = p.get('choice') or {}
        ids = [o['id'] for o in choice.get('options', [])]
        chosen = picker(p) if picker else ids[:max(1, choice.get('minimum', 1))]
        decline = not chosen and choice.get('allow_decline', True)
        answers.append({**p['context'], 'selection': 'DECLINE' if decline else 'USE', 'option_ids': chosen})
    raise AssertionError('too many choices')
