"""Session stand-ins for service tests that build their own engine.

CombatService and the table read a fight through the session it is handed, a
real combat.gate4_persistence.Gate4PersistentSession. Its read surface is its
engine, its match id and its mechanical journal (session.mechanical, a
PersistentMatchSession): the failed-action menu guard reads the already
verified journal records as session.mechanical._records.

Tests that drive the real service over a hand-built engine cannot create a
saved match, so they pass this stand-in instead of a hand-rolled
SimpleNamespace. When the service starts reading another session field, add it
here once rather than in every test's fake.
"""
from types import SimpleNamespace


def table_session(engine):
    """A session carrying what the service reads: its engine, match id and an empty journal."""
    mechanical = SimpleNamespace(_records=[])
    return SimpleNamespace(engine=engine, match_id=engine.state.match_id, mechanical=mechanical)
