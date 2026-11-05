"""Shared table-step helpers for the ported AUTO42 Stars regression (worker 1's AUTO44 Poison work imports them).

Only the reusable stepping helpers are kept here. The Stars assertions themselves are another lane's work: ten of them fail
against this branch's Stars plug-in, identically with and without this lane's changes (verified by running the ported file
against the committed Poison plug-in), so they are not carried onto the Poison branch.
"""
import pytest
from combat import flight
from combat.ext import placed, stars
from tests.auto_worker1_support import LEFT, RIGHT, fight, act, reload, action_sender


def resolve(send, picks=None):
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
        answers.append({**p['context'], 'selection': 'USE' if chosen or not p.get('choice') else 'DECLINE', 'option_ids': chosen})
    raise AssertionError('too many choices')


def turn(table, mid, actor_id):
    for _ in range(4):
        if table.state(mid)['menu']['actor_id'] == actor_id:
            return
        resolve(lambda answers: act(table, mid, 'end', answers))
    raise AssertionError('turn did not advance')


def cell_send(table, mid, label, xy):
    def send(answers):
        state = table.state(mid)
        menu = state['menu']
        cid = next(o['candidate_id'] for g in menu['actions'] if g['label'] == label for o in g['options']
            if o.get('destination') == {'x': xy[0], 'y': xy[1]})
        return table.act(mid, cid, menu['decision_id'], menu['state_version'], state['last_sequence'], answers)
    return send


def ascend(combat, table, mid, actor_id):
    state = table.state(mid)
    actor = reload(combat, mid).state.actors[actor_id]
    candidate = next(c for c in combat._load_session(mid).engine.legal_candidates()
        if c.destination is not None and c.metadata.get('movement_mode') == 'fly'
        and (c.destination.x, c.destination.y, c.destination.z) == (actor.position.x, actor.position.y, 1))
    menu = state['menu']
    return table.act(mid, candidate.candidate_id, menu['decision_id'], menu['state_version'], state['last_sequence'], [])

