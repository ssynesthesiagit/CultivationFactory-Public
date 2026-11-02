"""Public regression: fact_consent_admission.read follows the committed sequence.

Synthetic records and a stub schema only: no Pulse authority data, rules text,
private resources or fixtures, so it is public-safe by construction and meant
for public CI (ci_route lists it LOCAL until an export publishes it). Canonical snapshots list
condition keys in sorted order ("...:100" before "...:98"), so the list order
of reloaded rows is not chronology. The source-backed Pulse tests in
test_mgr_t15_gentle_source_pulse.py cover the same selection end to end as
additional (private-only) coverage.
"""
import pytest

from combat import fact_consent_admission as fca

SOURCE = 'synthetic:source'
SUBJECT = 'synthetic:subject'
KIND = 'synthetic.kind'
SCOPE = 'synthetic:scope'
SCHEMA = {'value_type': 'flag', 'maximum_seconds': 1000, 'authority': 'table_owner', 'subject_access': True}


class FakeSession:
    def __init__(self, rows):
        self.state = {fca.KEY: rows}

    def clock(self):
        return 0


def record(sequence, value):
    body = {'source': SOURCE, 'subject': SUBJECT, 'kind': KIND, 'scope': SCOPE, 'value': value,
            'expires_at': 1000, 'readers': [], 'authority': 'table_owner', 'created_at': 0,
            'sequence': sequence}
    body['receipt_id'] = fca.digest(body)
    return body


@pytest.fixture
def stub_schema(monkeypatch):
    def fake_query(point, *args, **kwargs):
        assert point == 'fact_admission_schema'
        return [SCHEMA]
    monkeypatch.setattr(fca, 'query', fake_query)


@pytest.mark.parametrize('order', ['reloaded_lexical', 'appended'])
def test_latest_committed_sequence_wins_regardless_of_list_order(stub_schema, order):
    approval = record(98, 1)
    revocation = record(100, 0)
    # "reloaded_lexical": a snapshot lists the ":100" key before the ":98" key.
    rows = [revocation, approval] if order == 'reloaded_lexical' else [approval, revocation]
    live = fca.read(FakeSession(rows), SOURCE, SUBJECT, KIND, SCOPE, SUBJECT)
    assert live is not None
    assert live['receipt_id'] == revocation['receipt_id']
    assert live['value'] == 0
