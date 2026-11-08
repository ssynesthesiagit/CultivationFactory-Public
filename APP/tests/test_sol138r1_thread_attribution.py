"""Thread save choices identify the caster separately from the saving creature."""
from dataclasses import replace

import pytest

from combat.ext import thread_correction
from combat.gate4_engine import Gate4ControllerEngine
from combat.gate5_service import CombatService
from combat.typed_executor import mark_condition_id
from tests.h1_support import ROOT
from tests.r1i_service_support import fixture, OWNER, FOE, SECOND
from tests.r10_fixup_support import cast_sender, commit, fixed_dice


@pytest.mark.parametrize('known_source', [True, False])
def test_thread_save_table_names_caster_or_leaves_unknown_source_unattributed(
        tmp_path, monkeypatch, known_source):
    combat, table, mid, send, decline = fixture(
        tmp_path, [thread_correction.PUPPET],
        foe_talents=['FIRE_BASE_CONFLAGRATION'], allies=[SECOND])
    # Persist a pre-existing physical line through the same evented setup used
    # by the earlier Thread table regression. No production hook is replaced.
    original = Gate4ControllerEngine.execute_intent
    def connected(engine, *args, **kwargs):
        result = original(engine, *args, **kwargs)
        engine._apply_condition(engine.state.actors[SECOND],
            mark_condition_id('Thread Line', OWNER), 'fixture:thread-line', OWNER,
            expires_on='UNTIL_REMOVED')
        return result
    with monkeypatch.context() as setup:
        setup.setattr(Gate4ControllerEngine, 'execute_intent', connected)
        decline(table.state(mid)['menu']['end_turn'])
    while table.state(mid)['menu']['actor_id'] != FOE:
        decline(table.state(mid)['menu']['end_turn'])
    if not known_source:
        # Some native saves have no source actor. Retain their action and roll
        # metadata, but model that missing provenance at the public reader.
        context_of = thread_correction.context_of
        def unknown_source(engine, roll):
            rc = context_of(engine, roll)
            return replace(rc, source_actor=None) if rc and rc.kind == 'save' else rc
        monkeypatch.setattr(thread_correction, 'context_of', unknown_source)
    fixed_dice(monkeypatch, [1] * 50)
    cast = cast_sender(combat, table, mid, 'Conflagration', at=(5, 6))
    result = cast()
    assert result['status'] == 'REACTION_REQUIRED', result
    prompt = result['reaction']
    assert prompt['reaction'] == 'Puppet-Line Correction'
    assert prompt['action'] == 'Conflagration'
    assert prompt['affected'] == prompt['by'] == 'Second'
    assert prompt['trigger_actor'] == ('Foe' if known_source else '')
    assert 'Second uses Conflagration' not in prompt['moment']
    assert ('Foe uses Conflagration on Second.' in prompt['moment']) is known_source
    if not known_source:
        assert ' uses Conflagration' not in prompt['moment']
    assert 'Second' in prompt['moment'] and 'Dexterity saving throw' in prompt['moment']
    # The table quotes the actual resource pool for newcomers, rather than
    # the generic printed CP alias. Attribution and the exact price both matter.
    assert 'Reaction' in prompt['moment']
    assert '2 Qi' in prompt['moment'] and '2 CP' not in prompt['moment']
    assert prompt['cost'] == 'your Reaction and 2 Qi (cultivation points from your Qi, Stamina or other pool)'
    assert cast()['reaction'] == prompt
    # Declining commits the real caster action and keeps the price unspent.
    commit(cast)
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.actors[OWNER].resources['resource:core.qi'] == 30
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'
