"""RW172 batch (Sol review F2R findings 1-3), real-engine regressions.

Golden Sea Guard's next-save Advantage must reach a real save roll through the
table, be spent by that save, and expire at the owner's next turn. Every test
drives TabletopService/CombatService, answers the printed prompts and reloads
the committed fight; no fake engine stands in for the path under test.
"""
from __future__ import annotations

import json

from combat.gate2_rolls import DeterministicRollAuthority
from tests.h1_support import ROOT
from tests.test_a2_r11_foundations import (_condition, _fight, _strike, _typed_action)
from tests.worker2_support import FOE, OWNER, candidate, reload, settle, turn

GOLDEN = 'ancient_desolate_sacred_body_v0_2C'
GUARD = 'foundation.ancient_desolate_sacred_body_v0_2C.golden_sea_guard'
FOLLOW = 'condition:typed.golden_sea_guard_next_save'
CON_SAVE = {'type': 'save', 'ability': 'CON', 'dc': 30, 'applies_to': 'target', 'on_fail': [], 'on_success': []}
RULES = ROOT / 'authority' / 'typed_mechanics' / 'reviewed_final.d' / 'a2_foundations_2.json'


def _owner_save_modes(monkeypatch):
    """Record the mode of every save roll the owner makes; the roll itself is untouched."""
    modes = []
    original = DeterministicRollAuthority.raw_d20

    def record(self, *, modifier, actor_id, reason, mode='NORMAL'):
        if actor_id == OWNER and reason.startswith('SAVE:'):
            modes.append(str(mode))
        return original(self, modifier=modifier, actor_id=actor_id, reason=reason, mode=mode)

    monkeypatch.setattr(DeterministicRollAuthority, 'raw_d20', record)
    return modes


def _curse_fight(tmp_path, monkeypatch=None):
    return _fight(tmp_path, GOLDEN, 'Golden Sea Pulse', stage='Refined', held=1,
                  foe_actions=[_strike('Foe Curse', FOE, damage=20, damage_type='NECROTIC'),
                               _typed_action('Foe Curse Save', FOE, [CON_SAVE])])


def _guard_necrotic_strike(combat, table, mid):
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Foe Curse', target=OWNER).candidate_id,
           picks={'reaction:typed.' + GUARD: 'first'})


def test_golden_guard_advantage_reaches_the_owners_save_roll_and_is_spent(tmp_path, monkeypatch):
    modes = _owner_save_modes(monkeypatch)
    combat, table, mid = _curse_fight(tmp_path)
    _guard_necrotic_strike(combat, table, mid)
    engine = reload(tmp_path, mid)
    assert any(e.event_type == 'REACTION_RESOLVED' and e.source_definition_id == GUARD for e in engine.events), \
        'the Guard never resolved against the necrotic strike'
    held = _condition(engine, engine.state.actors[OWNER], FOLLOW)
    assert held is not None and held.data.get('against') == FOE, 'Guard recorded no next-save Advantage'
    settle(table, mid, candidate(combat, mid, 'Foe Curse Save', target=OWNER).candidate_id)
    engine = reload(tmp_path, mid)
    assert modes, 'the owner never rolled the save'
    assert 'ADVANTAGE' in modes[-1].upper(), modes
    assert _condition(engine, engine.state.actors[OWNER], FOLLOW) is None, 'Advantage was not spent by the save'
    assert any(e.event_type == 'CONDITION_REMOVED' and e.payload.get('reason') == 'CONSUMED'
               and e.payload.get('condition_id') == FOLLOW for e in engine.events)


def test_golden_guard_advantage_expires_at_the_owners_next_turn(tmp_path):
    combat, table, mid = _curse_fight(tmp_path)
    _guard_necrotic_strike(combat, table, mid)
    engine = reload(tmp_path, mid)
    assert _condition(engine, engine.state.actors[OWNER], FOLLOW) is not None
    turn(table, mid, OWNER)
    engine = reload(tmp_path, mid)
    assert _condition(engine, engine.state.actors[OWNER], FOLLOW) is None, 'Advantage outlived the owner\'s next turn'


def test_perfected_tyrant_declaration_and_womb_keep_rider_text_while_gaps_remain():
    """Finding 2: the gap-bearing riders must stay visible (GM-rider rule, NEEDS-SYSTEM backlog)."""
    mechanics = json.loads(RULES.read_text(encoding='utf-8'))['mechanics']
    for key in ('foundation.heaven_tyrant_body_v0_2D.perfected_heaven_tyrant_blood_declaration',
                'foundation.heaven_devouring_shedding_womb_v0_2B.perfected_imperishable_heaven_womb'):
        riders = mechanics[key].get('riders') or []
        assert riders and any('still need combat automation' in r for r in riders), (key, riders)
