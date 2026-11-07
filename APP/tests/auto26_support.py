"""Table-driving helpers for the AUTO26 Chains lane.

These are generic table helpers (answer a prompt loop, advance a turn, ascend a
flying creature one level). They live here because this lane's test module must
not depend on another Sphere's test file.
"""
from tests.auto_worker1_support import act, reload


def resolve(send, picks=None):
    """Answer every prompt a single table action raises, then return the commit."""
    answers, prompts = [], []
    for _ in range(12):
        result = send(answers)
        if result['status'] != 'REACTION_REQUIRED':
            assert result['status'] == 'COMMITTED', result
            return result, prompts
        prompt = result['reaction']
        prompts.append(prompt)
        ids = [o['id'] for o in (prompt.get('choice') or {}).get('options', [])]
        chosen = (picks or {}).get(prompt['context']['reaction_source_id'], ids[:1])
        answers.append({**prompt['context'], 'selection': 'USE' if chosen or not prompt.get('choice') else 'DECLINE',
                        'option_ids': chosen})
    raise AssertionError('too many choices')


def turn(table, mid, aid):
    """Advance to `aid`'s turn, answering any prompts the table raises on the way."""
    for _ in range(4):
        if table.state(mid)['menu']['actor_id'] == aid:
            return
        resolve(lambda answers: act(table, mid, 'end', answers))
    raise AssertionError('turn did not advance')


def ascend(combat, table, mid, actor_id):
    """Move a flying actor one level straight up through the ordinary menu."""
    state = table.state(mid)
    actor = reload(combat, mid).state.actors[actor_id]
    candidate = next(c for c in combat._load_session(mid).engine.legal_candidates()
        if c.destination is not None and c.metadata.get('movement_mode') == 'fly'
        and (c.destination.x, c.destination.y, c.destination.z) == (actor.position.x, actor.position.y, 1))
    menu = state['menu']
    return table.act(mid, candidate.candidate_id, menu['decision_id'], menu['state_version'], state['last_sequence'], [])