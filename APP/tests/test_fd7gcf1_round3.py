"""FD7GCF1 round 3: fight-to-sheet feature uses are declared by plug-ins, and the Grow tab explains each Form.

No live server, model or embedding service is used. Each test fails on the pre-fix tree.
"""
from types import SimpleNamespace
from pathlib import Path

import combat.ext as ext

ext.feature_use_flags()  # load every plug-in before any test swaps the registry copy, so no registration is lost
from combat.tabletop_service import TabletopService

ROOT = Path(__file__).resolve().parents[2]
OWNER = 'actor:factory.char-1'


def _engine(flags):
    actor = SimpleNamespace(entity_id=OWNER, turn_flags=dict(flags))
    return SimpleNamespace(state=SimpleNamespace(actors={OWNER: actor}))


def _service(calls):
    table = object.__new__(TabletopService)
    table.record_feature_use = lambda project, feature: calls.append((project, feature))
    return table


def test_a_second_plugin_declaration_is_persisted_without_a_core_change(monkeypatch):
    """Core iterates the declared (flag, feature) pairs; a new declaration is recorded with no change to core."""
    monkeypatch.setattr(ext, '_FEATURE_USE_FLAGS', dict(ext._FEATURE_USE_FLAGS))
    ext.register_feature_use_flag('fixture_round_flag', 'tianxia.test.feature.fixture_round')
    calls = []
    _service(calls)._record_fight_feature_uses(_engine({'fixture_round_flag': 1}))
    assert ('char-1', 'tianxia.test.feature.fixture_round') in calls


def test_an_unset_declared_flag_records_nothing(monkeypatch):
    monkeypatch.setattr(ext, '_FEATURE_USE_FLAGS', dict(ext._FEATURE_USE_FLAGS))
    ext.register_feature_use_flag('fixture_round_flag', 'tianxia.test.feature.fixture_round')
    calls = []
    _service(calls)._record_fight_feature_uses(_engine({}))
    assert calls == []


def test_a_flag_cannot_be_redeclared_for_another_feature(monkeypatch):
    monkeypatch.setattr(ext, '_FEATURE_USE_FLAGS', dict(ext._FEATURE_USE_FLAGS))
    ext.register_feature_use_flag('fixture_round_flag', 'tianxia.test.feature.a')
    try:
        ext.register_feature_use_flag('fixture_round_flag', 'tianxia.test.feature.b')
    except ValueError:
        return
    raise AssertionError('a conflicting declaration must be refused')


def test_nascent_continuity_is_declared_by_the_plugin_not_named_in_core():
    core = (ROOT / 'APP' / 'combat' / 'tabletop_service.py').read_text(encoding='utf-8')
    assert 'nascent_continuity_used_round_scene' not in core
    assert 'NASCENT_SOUL' not in core
    assert ('nascent_continuity_used_round_scene', 'tianxia.path.qi_cultivation.feature.nascent_soul') in ext.feature_use_flags()


def test_grow_no_longer_says_stable_is_used_by_default():
    js = (ROOT / 'APP' / 'static' / 'tabletop' / 'grow.js').read_text(encoding='utf-8')
    assert 'Stable Golden Core is used in combat until' not in js
    assert 'you hold no Golden Core Form in combat' in js


def test_grow_explains_each_recorded_form_from_the_panel_text():
    js = (ROOT / 'APP' / 'static' / 'tabletop' / 'grow.js').read_text(encoding='utf-8')
    assert 'panel.forms.filter((row) => row.benefit)' in js
    from combat.ext import qi_path
    assert set(qi_path.FORM_BENEFITS) == {'stable', 'circulating', 'reservoir'}
    assert all(qi_path.FORM_BENEFITS[key].get('benefit') for key in qi_path.FORM_BENEFITS)
