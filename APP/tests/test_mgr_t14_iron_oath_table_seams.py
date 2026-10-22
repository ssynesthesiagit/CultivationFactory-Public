"""The owner/GM table entries the Iron Oath consumers read must exist and persist.

Regression for the merge that dropped these TabletopService methods: without
them every consumer test stops at ``AttributeError: 'TabletopService' object has
no attribute 'record_fact'`` and the owner-only Fact endpoint raises 500.
"""
from combat.tabletop_service import TabletopService
from tests.test_mgr_t14_iron_oath_3 import oath_table
from tests.iron_oath_support import duty
from tests.worker2_support import reload

OWNER_ENTRIES = ('record_fact', 'record_foundation_attainment',
                 'reconcile_character_effects', 'acquire_feature')


def test_owner_table_entries_are_present():
    missing = [name for name in OWNER_ENTRIES if not callable(getattr(TabletopService, name, None))]
    assert missing == []


def test_owner_recorded_fact_commits_and_survives_reload(tmp_path):
    combat, table, mid = oath_table(tmp_path)
    document = duty(combat, table, mid)
    engine = reload(tmp_path, mid)
    facts = [event.payload['fact'] for event in engine.events
             if event.event_type == 'TABLE_FACT_RECORDED']
    assert any(fact['record_id'] == document['record_id'] and fact['active'] for fact in facts)
