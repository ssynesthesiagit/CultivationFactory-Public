"""Combined condition readers retain scoped checks and suppressed saved state."""
from combat import typed_executor
from combat.ext.scoped_checks import escape_modes
from combat.stealth import search_modes
from tests import test_tabletop_hunt6 as H
from tests.test_lock18_conditions import apply, commit


def test_table_suppressed_condition_projection_keeps_core_dodge(monkeypatch, tmp_path):
    def trigger(engine):
        actor, target = engine.state.actors[H.LEFT], engine.state.actors[H.RIGHT]
        apply(engine, H.RIGHT, 'suppressed.test_penalty', rule={'attacked_with': 'ADVANTAGE'})
        apply(engine, H.RIGHT, 'condition:core.dodge')
        assert engine._attack_mode(actor, target) == 'DISADVANTAGE'
        assert not any(row.get('attacked_with') == 'ADVANTAGE'
                       for row in typed_executor.condition_rules(target, engine=engine))
    commit(monkeypatch, tmp_path, trigger)


def test_table_visible_fear_composes_with_scoped_escape_and_search(monkeypatch, tmp_path):
    def trigger(engine):
        actor = engine.state.actors[H.LEFT]
        apply(engine, H.LEFT, 'frightened', source=H.RIGHT)
        apply(engine, H.LEFT, 'check_against', rule={'check_against': {
            'abilities': ['STR'], 'against': ['grappled'], 'mode': 'ADVANTAGE'}})
        effect = {'check_ability': 'STR', 'check_skill': 'Athletics'}
        assert escape_modes(actor, effect, ('grappled',), engine=engine) == set()
        assert search_modes(engine, actor) == {'DISADVANTAGE'}
        engine._remove_condition(actor, 'condition:typed.frightened', H.HOLD)
        assert escape_modes(actor, effect, ('grappled',), engine=engine) == {'ADVANTAGE'}
        assert search_modes(engine, actor) == set()
    commit(monkeypatch, tmp_path, trigger)
