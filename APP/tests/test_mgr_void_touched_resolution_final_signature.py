"""Void-Touched Void Step: the shared resolution_final callback must accept the dispatcher's five arguments.

The dispatcher calls every resolution_final hook as (engine, actor, action, candidate, intent). The Void Step
plug-in's callback once took one argument, so every resolved combat action raised TypeError. These tests pin the
signature and the inertness rule: only the owner's accepted Void Step records the per-turn use.
"""
import inspect
from types import SimpleNamespace as NS

from combat.ext import mgr_reserve_void_touched_cultivator_void_step as plugin

PREFIX = plugin.PREFIX


def _engine(round_number=1):
    return NS(state=NS(actors={}, current_actor_id=None, round_number=round_number, current_slot_index=0))


def _actor():
    return NS(entity_id='a', turn_flags={})


def _action(source, scar=True):
    return NS(parameters={'typed': {'source': source, 'void_scar': scar}})


def test_resolution_final_callback_accepts_dispatcher_arguments():
    params = inspect.signature(plugin.record_void_step_use).parameters
    assert list(params) == ['engine', 'actor', 'action', 'candidate', 'intent']


def test_resolution_final_callback_is_inert_for_unrelated_actions():
    actor = _actor()
    plugin.record_void_step_use(_engine(), actor, _action('tianxia.subpath.qi.void_touched_cultivator.feature.empty_palm'), None, None)
    plugin.record_void_step_use(_engine(), actor, _action(PREFIX + 'void_step', scar=False), None, None)
    assert '_round_void_step_turn' not in actor.turn_flags


def test_resolution_final_callback_records_owner_void_step_use():
    actor = _actor()
    engine = _engine(round_number=4)
    plugin.record_void_step_use(engine, actor, _action(PREFIX + 'void_step'), None, None)
    assert actor.turn_flags['_round_void_step_turn'] == plugin.turn_token(engine)
