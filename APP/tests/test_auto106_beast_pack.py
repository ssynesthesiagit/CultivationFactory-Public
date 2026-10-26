"""Pack ownership unit controls; real behavior is in test_sph_beastmastery_r1.

The original AUTO106 probes assumed permanent immunity, automatic grants and
global Disengage suppression. Those assumptions contradict the printed rules.
"""
from types import SimpleNamespace

import pytest

from combat.ext import beastmastery_pack as pack
from combat.factory_compiler import compile_character
from tests.h1_support import sheet


@pytest.mark.parametrize('feature,name', [(pack.PROCESSION, 'Ten-Thousand-Beast Procession'),
                                         (pack.PACK_MIND, 'Sovereign Pack Mind')])
def test_ownership_block_keeps_paid_action_compiling(feature, name):
    bundle = compile_character(sheet([feature]), actor_id='actor:test.pack')
    actions = [a for a in bundle['action_catalog'] if a['display_name'] == name]
    assert len(actions) == 1
    assert actions[0]['costs']


@pytest.mark.parametrize('changes,eligible', [({}, True), ({'active': False}, False),
    ({'team_id': 'enemy'}, False), ({'summon': {'owner': 'owner', 'source': 'spirit_bond'}}, False),
    ({'summon': {'owner': 'owner', 'source': 'tamer', 'status': 'absent'}}, False),
    ({'summon': {'owner': 'someone_else', 'source': 'tamer'}}, False)])
def test_shared_beast_recipient_predicate(changes, eligible):
    owner = SimpleNamespace(entity_id='owner', team_id='ours')
    beast = SimpleNamespace(entity_id='beast', active=True, team_id='ours',
                            summon={'owner': 'owner', 'source': 'tamer', 'status': 'present'})
    beast.__dict__.update(changes)
    engine = SimpleNamespace(state=SimpleNamespace(actors={'owner': owner, 'beast': beast}))
    # Owner needs the same ActorState fields, but never counts as its own beast.
    owner.active = True
    owner.summon = None
    assert (beast in pack.beast_allies(engine, owner)) == eligible
