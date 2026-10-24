"""Fight-to-sheet feature uses are declared by plug-ins, never named in core.

No live server, model or embedding service is used.
"""
from types import SimpleNamespace

import combat.ext as ext

ext.feature_use_flags()  # load every plug-in before any test swaps the registry copy, so no registration is lost
from combat.tabletop_service import TabletopService

OWNER = 'actor:factory.char-1'


def _engine(flags):
    actor = SimpleNamespace(entity_id=OWNER, turn_flags=dict(flags))
    return SimpleNamespace(state=SimpleNamespace(actors={OWNER: actor}, match_id='match:7', round_number=4))


def _service(calls):
    table = object.__new__(TabletopService)

    def record(project, feature, **kwargs):
        calls.append((project, feature, kwargs))

    table.record_feature_use = record
    return table


def test_a_second_plugin_declaration_is_persisted_without_a_core_change(monkeypatch):
    """Core iterates the declared (flag, feature) pairs; a new declaration is recorded with no change to core."""
    monkeypatch.setattr(ext, '_FEATURE_USE_FLAGS', dict(ext._FEATURE_USE_FLAGS))
    ext.register_feature_use_flag('fixture_round_flag', 'tianxia.test.feature.fixture_round')
    calls = []
    _service(calls)._record_fight_feature_uses(_engine({'fixture_round_flag': 1}))
    assert calls == [('char-1', 'tianxia.test.feature.fixture_round',
                      {'gm': True, 'source': 'fight', 'fight': 'match:7', 'round_number': 4})]


def test_an_unset_declared_flag_records_nothing(monkeypatch):
    monkeypatch.setattr(ext, '_FEATURE_USE_FLAGS', dict(ext._FEATURE_USE_FLAGS))
    ext.register_feature_use_flag('fixture_round_flag', 'tianxia.test.feature.fixture_round')
    calls = []
    _service(calls)._record_fight_feature_uses(_engine({}))
    assert calls == []


def test_a_failed_sheet_write_never_breaks_a_committed_fight(monkeypatch):
    """The sheet write happens after the fight is committed, so a write failure is best effort, not an error."""
    monkeypatch.setattr(ext, '_FEATURE_USE_FLAGS', dict(ext._FEATURE_USE_FLAGS))
    ext.register_feature_use_flag('fixture_round_flag', 'tianxia.test.feature.fixture_round')
    table = object.__new__(TabletopService)

    def exploding(project, feature, **kwargs):
        raise OSError('disk is full')

    table.record_feature_use = exploding
    table._record_fight_feature_uses(_engine({'fixture_round_flag': 1}))  # must not raise


def test_a_flag_cannot_be_redeclared_for_another_feature(monkeypatch):
    monkeypatch.setattr(ext, '_FEATURE_USE_FLAGS', dict(ext._FEATURE_USE_FLAGS))
    ext.register_feature_use_flag('fixture_round_flag', 'tianxia.test.feature.a')
    try:
        ext.register_feature_use_flag('fixture_round_flag', 'tianxia.test.feature.b')
    except ValueError:
        return
    raise AssertionError('a conflicting declaration must be refused')


def test_nascent_continuity_is_declared_by_the_plugin(monkeypatch):
    """The declaration comes from the plug-in registry, not from a name in the core service."""
    monkeypatch.setattr(ext, '_FEATURE_USE_FLAGS', dict(ext._FEATURE_USE_FLAGS))
    assert ('nascent_continuity_used_round_scene',
            'tianxia.path.qi_cultivation.feature.nascent_soul') in ext.feature_use_flags()
    assert ext.feature_use_flags()  # every plug-in loaded
