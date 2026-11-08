"""Keep non-aligned Fire options/costs independent of Palace activation.

Select by the semantic source, never the first hash-sorted candidate: candidate
hashes include event_sequence, so a different activation transcript reorders them.

Scope: variant, position and cost parity only. This file does not compare damage
or saving-throw dice with the historical capture; that divergence is not closed here.
"""
import copy

import pytest

from combat import factory_compiler
from combat.ext.taiyin_palace import SOURCE, USED
from tests.palace_support import game, activate
from tests.worker2_support import OWNER, FOE, settle, reload


def fire_candidates(engine):
    return {c.source_definition_id: c for c in engine.legal_candidates()
            if c.target_ids == (FOE,)
            and 'FIRE_BASE_IGNITE#' in c.source_definition_id}


@pytest.mark.parametrize('variant,cost', [('opt0+overheat', 1), ('opt2', 0)])
def test_native_ignite_variant_and_payment_do_not_depend_on_palace(tmp_path, monkeypatch, variant, cost):
    real_read = factory_compiler._read_compilation_authority
    def legacy_read(path):
        authority, sha = real_read(path)
        authority = copy.deepcopy(authority)
        authority['mechanics'][SOURCE]['effects'] = [
            e for e in authority['mechanics'][SOURCE]['effects'] if e['type'] == 'temp_hp']
        return authority, sha

    contracts = []
    for arm in ('inactive', 'active', 'legacy'):
        with monkeypatch.context() as patch:
            if arm == 'legacy':
                patch.setattr(factory_compiler, '_read_compilation_authority', legacy_read)
            combat, table, mid = game(tmp_path / arm, native=True)
            if arm != 'inactive':
                activate(combat, table, mid)
            engine = combat._load_session(mid).engine
            options = fire_candidates(engine)
            assert options
            rows = {sid: engine.action_catalog[sid].model_dump(mode='json') for sid in options}
            # Every legal variant stays reachable, including Overheat.
            contracts.append(rows)
            sid = next(s for s in options if s.endswith('#' + variant))
            owner = engine.state.actors[OWNER]
            balances = dict(owner.resources)
            foe_hp = engine.state.actors[FOE].current_hp
            before = len(engine.events)
            settle(table, mid, options[sid].candidate_id)
            engine = reload(tmp_path / arm, mid)
            events = engine.events[before:]
            spends = [e for e in events if e.event_type == 'RESOURCE_SPENT' and e.actor_id == OWNER]
            assert sum(e.payload['amount'] for e in spends) == cost
            assert sum(balances.values()) - sum(engine.state.actors[OWNER].resources.values()) == cost
            assert not engine.state.actors[OWNER].turn_flags.get(USED)
            assert engine.state.actors[FOE].current_hp <= foe_hp
            assert any(e.event_type == 'ATTACK_ROLLED' and e.source_definition_id == sid for e in events)
    assert contracts[0] == contracts[1] == contracts[2]


def test_palace_does_not_damage_a_foe_before_ignite(tmp_path):
    combat, table, mid = game(tmp_path, native=True)
    engine = combat._load_session(mid).engine
    hp = engine.state.actors[FOE].current_hp
    before = len(engine.events)
    activate(combat, table, mid)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[FOE].current_hp == hp
    assert not [e for e in engine.events[before:]
                if e.event_type == 'DAMAGE_COMMITTED' and FOE in e.target_ids]
