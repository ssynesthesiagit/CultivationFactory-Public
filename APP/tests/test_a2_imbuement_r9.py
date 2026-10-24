"""Counter ownership and caster exits through accepted intents, cold reload and replay."""
import pytest

from combat import concentration
from combat.ext import persist_augment as P
from combat.ext.concentration_duration import DEADLINE
from combat.gate2_rolls import DeterministicRollAuthority
from tests.test_a2_imbuement import fixture, cold, turn, M, S
from tests.test_a2_imbuement_r5 import probes, resolve, candidate


def fixed_dice(monkeypatch, natural):
    def fixed(self, sides):
        count = self.counter
        self.counter += 1
        return min(natural, sides), count
    monkeypatch.setattr(DeterministicRollAuthority, '_die', fixed)


def recipient_rows(actor, source):
    return [r for r in (*actor.conditions.values(), *actor.modifiers.values())
            if r.source_definition_id == source
            and getattr(r, 'condition_id', '') not in (M.MASS_LOAD, P.RECORD, concentration.HELD, DEADLINE)]


@pytest.mark.parametrize('copy_kind', ['live_mass', 'two_live', 'set_and_live'])
def test_counter_ends_only_selected_mass_recipient_and_activation(monkeypatch, tmp_path, copy_kind):
    combat, table, mid, send, commit = fixture(monkeypatch, tmp_path,
        talents=['mass_mandate', 'layered_mandate'], extra=True,
        foe_talents=['quicken_and_slow'])
    fixed_dice(monkeypatch, 20)
    label = next(g['label'] for g in table.state(mid)['menu']['actions']
                 if g['label'].startswith('Mass Place Mandate: Quicken'))
    prompts = resolve(send, candidate(table, mid, label, S.SECOND), [S.SECOND, S.THIRD])
    assert any(p['context']['reaction_source_id'] == 'choice:needle.mass_mandate'
               and p['context']['reactor_id'] == S.OWNER for p in prompts)
    engine = cold(tmp_path, mid)
    owner = engine.state.actors[S.OWNER]
    source, started = owner.concentration.source_definition_id, owner.concentration.started_sequence
    assert recipient_rows(engine.state.actors[S.SECOND], source)
    assert recipient_rows(engine.state.actors[S.THIRD], source)
    if copy_kind == 'set_and_live':
        commit(S.candidate(table, mid, 'Set Mandate:'))
        engine = cold(tmp_path, mid)
        assert P.persisted(engine, engine.state.actors[S.OWNER], P.MANDATE)
    if copy_kind != 'live_mass':
        turn(table, mid, commit)
        resolve(send, candidate(table, mid, label, S.OWNER), [S.OWNER])
        engine = cold(tmp_path, mid)
        newest = engine.state.actors[S.OWNER].concentration.started_sequence
        assert newest > started
        assert recipient_rows(engine.state.actors[S.OWNER], source)
    for _ in range(12):
        commit(table.state(mid)['menu']['end_turn'])
        if table.state(mid)['menu']['actor_id'] == S.FOE:
            break
    assert table.state(mid)['menu']['actor_id'] == S.FOE
    engine = cold(tmp_path, mid)
    # Set replaces rows with detached instances; anchor to the current recipient
    # instances immediately before the Counter transaction.
    old_second = {r.instance_id if hasattr(r, 'instance_id') else r.modifier_id
                  for r in recipient_rows(engine.state.actors[S.SECOND], source)}
    assert old_second
    commit(S.candidate(table, mid, 'Counter-Mandate: strip a foe', S.SECOND))
    # Reload a fresh CombatService and replay before checking the repaired interaction.
    engine = cold(tmp_path, mid)
    owner = engine.state.actors[S.OWNER]
    checks = [e for e in engine.events if e.event_type == 'CHECK_ROLLED' and e.actor_id == S.FOE]
    assert checks[-1].payload['success'] is True
    assert not recipient_rows(engine.state.actors[S.SECOND], source)
    assert recipient_rows(engine.state.actors[S.THIRD], source), 'the live/persisted sibling must survive'
    assert M._mandate_weight(engine, owner, source, started) == 1
    if copy_kind != 'set_and_live':
        assert started in concentration.copies(owner, source)
    else:
        assert P.persisted(engine, owner, P.MANDATE)
    if copy_kind != 'live_mass':
        assert recipient_rows(owner, source), 'the newer identical activation must survive'
        assert newest in concentration.copies(owner, source)
    removed = [e for e in engine.events if e.event_type in ('CONDITION_REMOVED', 'MODIFIER_REMOVED')
               and (e.payload.get('instance_id') or e.payload.get('modifier_id')) in old_second]
    assert len(removed) == len(old_second)
    assert all(e.payload.get('reason') == 'COUNTERED' for e in removed)
    # The last recipient releases only the selected old activation/Set tracking.
    turn(table, mid, commit)
    for _ in range(12):
        commit(table.state(mid)['menu']['end_turn'])
        if table.state(mid)['menu']['actor_id'] == S.FOE:
            break
    commit(S.candidate(table, mid, 'Counter-Mandate: strip a foe', S.THIRD))
    engine = cold(tmp_path, mid)
    owner = engine.state.actors[S.OWNER]
    assert not recipient_rows(engine.state.actors[S.THIRD], source)
    assert started not in concentration.copies(owner, source)
    assert not P.persisted(engine, owner, P.MANDATE)
    if copy_kind != 'live_mass':
        assert concentration.copies(owner, source) == [newest]
        assert recipient_rows(owner, source)


def caster_probe(bundles):
    # Exercise the caster's Wisdom check against another creature. A self
    # contest has no opponent and intentionally does not roll a check.
    from combat.canonical import canonical_sha256
    from tests.test_a2_imbuement_r5 import PROBE
    probes(bundles)
    owner = next(b for b in bundles if b['actor_id'] == S.OWNER)
    probe = next(a for a in owner['action_catalog'] if a['source_definition_id'] == PROBE)
    contest = probe['parameters']['typed']['effects'][0]
    contest['actor_check'] = {'kind': 'check', 'ability': 'WIS', 'skill': 'Insight'}
    contest['target_check'] = {'kind': 'check', 'ability': 'DEX', 'skill': 'Sleight of Hand'}
    owner.pop('bundle_sha256', None)
    owner['bundle_sha256'] = canonical_sha256(owner)


def test_caster_clarify_exit_reduces_load_and_admits_next_cast(monkeypatch, tmp_path):
    combat, table, mid, send, commit = fixture(monkeypatch, tmp_path,
        talents=['mass_mandate', 'layered_mandate', 'clarify_and_cloud'],
        extra=True, bundle_transform=caster_probe)
    fixed_dice(monkeypatch, 1)
    label = next(g['label'] for g in table.state(mid)['menu']['actions']
                 if g['label'].startswith('Mass Place Mandate: Clarify'))
    resolve(send, candidate(table, mid, label, S.OWNER), [S.OWNER, S.SECOND, S.THIRD], 'WIS')
    engine = cold(tmp_path, mid)
    owner = engine.state.actors[S.OWNER]
    source, started = owner.concentration.source_definition_id, owner.concentration.started_sequence
    assert M._mandate_weight(engine, owner, source, started) == 2
    prompts = resolve(send, candidate(table, mid, 'Table recipient probe', S.SECOND))
    engine = cold(tmp_path, mid)
    owner = engine.state.actors[S.OWNER]
    keep = [p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.d20_floor_keep']
    assert len(keep) == 1 and keep[0]['context']['reactor_id'] == S.OWNER
    assert not recipient_rows(owner, source)
    assert any(c.condition_id == DEADLINE and c.data['started_sequence'] == started
               for c in owner.conditions.values()), 'the sibling activation still needs its deadline'
    assert M._mandate_weight(engine, owner, source, started) == 1, 'bookkeeping is not a recipient'
    turn(table, mid, commit)
    quicken = next(g['label'] for g in table.state(mid)['menu']['actions']
                   if g['label'].startswith('Place Mandate: Quicken'))
    commit(candidate(table, mid, quicken, S.OWNER))
    engine = cold(tmp_path, mid)
    owner = engine.state.actors[S.OWNER]
    assert started in concentration.copies(owner, source), 'one remaining load slot admits Quicken without eviction'
    assert all(recipient_rows(engine.state.actors[aid], source) for aid in [S.SECOND, S.THIRD])
    assert not any(e.event_type == 'CONDITION_REMOVED' and e.payload.get('reason') == 'MANDATE_LOAD'
                   for e in engine.events)
