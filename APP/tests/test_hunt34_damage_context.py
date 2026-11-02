"""Public synthetic H34-30 regression: thrown inscription plus Demon Mark.

The private captured fight remains external evidence, never a repository fixture.
"""
import pytest

from combat.gate5_service import CombatService
from tests.h1_support import ROOT
from tests.r1i_service_support import OWNER, FOE, fixture, candidate, force_ai_candidate
from tests.test_lock_choices import install

MARK = 'TAL_DAEMONIC_CULTIVATION_DEMON_MARK'
KIT = {'starting_kit': {'items': [], 'resolved_treasure_weapon': {
    'chassis': {'item_id': 'tianxia.mortal.weapon.bi_shou', 'name': 'Treasure dagger',
                'damage': '1d4 Piercing', 'properties': 'Finesse, Light, Thrown 20/60',
                'weapon_class': 'Simple Melee'},
    'refinement_bonus': 0,
    'enchantments': [{'name': 'Mountain-Weight Inscription',
        'text': 'Whenever you hit with the weapon, the target takes an additional 1d4 force damage.'}]}}}


@pytest.mark.parametrize('auto', [False, True])
@pytest.mark.parametrize('marked', [False, True])
def test_thrown_inscription_and_mark_packets_commit_reload_replay(tmp_path, monkeypatch, auto, marked):
    seen = []

    def observe(engine, target, amount, kind, source, actor, intent):
        if actor == OWNER and target.entity_id == FOE:
            provenance = engine.damage_context()
            seen.append((source, provenance))
            if provenance is not None:
                assert (provenance.source_id, provenance.attacker_id, provenance.target_id) == (source, actor, FOE)

    install(monkeypatch, 'final_damage', observe)
    combat, table, mid, send, commit = fixture(tmp_path, [MARK] if marked else [],
        owner_kit=KIT, foe_ac=0, seed='H34-MARK-DAMAGE-CONTEXT')
    if marked:
        commit(candidate(table, mid, 'Demon Mark', FOE))
    state = table.state(mid)
    action = next(g['source_definition_id'] for g in state['menu']['actions']
                  if '.weapon.' in g['source_definition_id'] and '#thrown' in g['source_definition_id'])
    chosen = next(o['candidate_id'] for g in state['menu']['actions'] if g['source_definition_id'] == action
                  for o in g['options'] if FOE in o.get('target_ids', []))
    before = state['last_sequence']
    if auto:
        force_ai_candidate(combat, mid, OWNER, chosen)
    assert send(chosen, auto=auto)['status'] == 'COMMITTED'
    fresh = CombatService(ROOT, tmp_path)._load_session(mid)
    events = [e for e in fresh.engine.events if e.sequence > before]
    damage = [e for e in events if e.event_type == 'DAMAGE_COMMITTED' and FOE in e.target_ids]
    # The primary hit and its inscription retain the thrown attack's identity.
    assert len([e for e in damage if e.source_definition_id == action]) == 2
    bonus = [e for e in damage if MARK in e.source_definition_id]
    # MMX119: the mark reads "add Proficiency Bonus to THE damage", so it rides the thrown
    # attack's own printed roll instead of committing a second packet. This test used to
    # assert that separate packet; the printed text requires the roll to carry it.
    assert bonus == []
    if marked:
        rolls = [e for e in events if e.event_type == 'DAMAGE_ROLLED' and action in e.source_definition_id]
        assert any(int(e.payload['modifier'] or 0) >= 4 for e in rolls), {
            'why': 'the marked creature is damaged, so the Proficiency Bonus is a modifier on that '
                   'printed roll', 'rolls': [e.payload for e in rolls]}
        assert any(key.startswith('_round_typed_on_hit:') and MARK in key
                   for key in fresh.engine.state.actors[OWNER].turn_flags)
    assert any(source == action and provenance is not None for source, provenance in seen)
    assert fresh.verify()['status'] == fresh.mechanical.replay()['status'] == 'PASS'
