"""Turn-flow checkpoint: the owner is asked at the bearer's turn, not skipped.

The owner answers the scene only; the character's own choice stays in their
ordinary action menu. No live models, private inputs or GUI.
"""

from combat.ext.foundation_combat import held
from combat.ext.glass_heart_refraction import CHOICE, SOURCE
from tests.glass_refraction_support import _asked, _glass_fight, _to_next_owner_turn, available
from tests.worker2_support import OWNER, ALLY, FOE, settle, reload
import pytest


def _offered(engine):
    return [c for c in engine.legal_candidates() if SOURCE in c.source_definition_id]


def test_automatic_play_asks_the_owner_at_the_bearers_turn(tmp_path):
    combat, table, mid = _glass_fight(tmp_path)
    assert not _offered(reload(tmp_path, mid))  # undeclared: the state is not silently offered
    prompts = _to_next_owner_turn(table, mid, {CHOICE: ['Major combat']})
    asked = _asked(prompts)
    assert asked, 'the owner was never asked at the bearer turn'
    assert asked[0]['reaction'] == 'Glass Heart Refraction'
    assert {option['id'] for option in asked[0]['choice']['options']} == {'Major combat', 'Emotionally decisive scene', 'Neither'}
    assert any('Glass Heart Refraction' in str(asked[0].get(key, '')) for key in ('moment', 'summary', 'rules'))
    # The owner answered only the scene; the character's own choice is now offered.
    assert _offered(reload(tmp_path, mid))


def test_bearer_who_starts_the_fight_is_asked_at_the_next_turn_start(tmp_path):
    # Fight setup starts the first creature's turn before any table decision can
    # pause, so the first bearer turn cannot ask. It must leave the scene
    # undeclared rather than record the setup fallback as the owner's "Neither".
    combat, table, mid = _glass_fight(tmp_path, match_seed='GLASS-TURN-2')  # bearer first
    engine = reload(tmp_path, mid)
    assert engine.state.current_actor_id == OWNER
    assert not [e for e in engine.events if e.event_type == 'TABLE_FACT_RECORDED']
    assert not available(engine)
    prompts = _to_next_owner_turn(table, mid, {CHOICE: ['Major combat']})
    assert _asked(prompts), 'setup silently declined the scene; the owner was never asked'
    assert available(reload(tmp_path, mid))


def test_owner_can_rule_the_scene_out_at_the_bearers_turn(tmp_path):
    combat, table, mid = _glass_fight(tmp_path)
    before = reload(tmp_path, mid).state.actors[OWNER]
    prompts = _to_next_owner_turn(table, mid, {CHOICE: ['Neither']})
    assert _asked(prompts)
    engine = reload(tmp_path, mid)
    assert not _offered(engine)
    assert held(engine.state.actors[OWNER], 'glass_refraction') is None
    assert engine.state.actors[OWNER].resources == before.resources


def test_plugin_is_inert_without_the_talent(tmp_path):
    """No form, no question, no fact and no offered action for other characters."""
    from combat.tabletop_service import TabletopError
    from tests.worker2_support import fixture as plain_fight

    combat, table, mid = plain_fight(tmp_path, [])
    version = table.source_inputs(mid)['state_version']
    assert table.source_inputs(mid)['forms'] == []
    assert not [c for c in reload(tmp_path, mid).legal_candidates() if SOURCE in c.source_definition_id]
    prompts = []
    for _ in range(4):
        if combat._load_session(mid).engine.state.terminal_result is not None:
            break
        prompts += settle(table, mid, table.state(mid)['menu']['end_turn'])
    assert not _asked(prompts), 'a character without the talent must never be asked about the scene'
    assert not [e for e in reload(tmp_path, mid).events if e.event_type == 'TABLE_FACT_RECORDED']
    with pytest.raises(TabletopError):
        table.record_source_input(mid, SOURCE, OWNER, {'scene': 'Major combat', 'reason': 'Not mine'}, version)
