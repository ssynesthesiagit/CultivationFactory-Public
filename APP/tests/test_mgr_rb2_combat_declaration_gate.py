"""Public regression (RB2 finding 1): the combat declaration gate restricts only restricted sources.

A combat fact session refuses a declaration only when the source is neither
schema-combat-admitted (spec 'combat': True) nor admitted by every
combat_fact_admission_allowed hook. Synthetic schema and hooks only.
"""
import pytest

from combat import fact_consent_admission as fca

SOURCE = 'synthetic:source'
SUBJECT = 'synthetic:subject'
KIND = 'synthetic.kind'
SCHEMA = {'value_type': 'flag', 'maximum_seconds': 1000, 'authority': 'table_owner', 'subject_access': True}


class CombatSession:
    is_combat_fact_context = True

    def __init__(self):
        self.state = {'actors': {SUBJECT: {}}, fca.KEY: []}

    def clock(self):
        return 0


@pytest.fixture
def hooks(monkeypatch):
    table = {'schema': SCHEMA, 'allowed': []}

    def fake_query(point, *args, **kwargs):
        if point == 'fact_admission_schema':
            return [table['schema']]
        if point == 'combat_fact_admission_allowed':
            return list(table['allowed'])
        return []

    monkeypatch.setattr(fca, 'query', fake_query)
    monkeypatch.setattr(fca, 'run_strict', lambda *a, **k: None)
    return table


def test_unrestricted_source_without_combat_admission_is_refused(hooks):
    hooks['allowed'] = [None]
    assert fca._combat_admitted(CombatSession(), SCHEMA, SOURCE, SUBJECT, KIND) is False


def test_schema_combat_flag_admits(hooks):
    assert fca._combat_admitted(CombatSession(), {**SCHEMA, 'combat': True}, SOURCE, SUBJECT, KIND) is True


def test_hook_allowed_source_without_schema_flag_is_admitted(hooks):
    hooks['allowed'] = [True]
    assert fca._combat_admitted(CombatSession(), SCHEMA, SOURCE, SUBJECT, KIND) is True


def test_one_refusing_hook_blocks_admission(hooks):
    hooks['allowed'] = [True, None]
    assert fca._combat_admitted(CombatSession(), SCHEMA, SOURCE, SUBJECT, KIND) is False


def test_declare_in_combat_refuses_unadmitted_source_with_gate_message(hooks):
    payload = {'source': SOURCE, 'subject': SUBJECT, 'kind': KIND, 'scope': 's', 'value': 1,
               'expires_at': 1, 'readers': []}
    with pytest.raises(ValueError, match='does not admit declarations during combat'):
        fca._declare(CombatSession(), SUBJECT, payload, world=False)
