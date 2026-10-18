import pytest

from tests.anchor_support import ANCHOR, FRIEND, fight, push


@pytest.mark.parametrize("ai", [False, True])
@pytest.mark.parametrize("feet", [30, 40])
def test_printed_anchor_range_at_table_boundary(tmp_path, monkeypatch, ai, feet):
    service, table, mid = fight(tmp_path, ally=True, feet=feet, ai=ai)
    engine, prompts = push(service, table, mid, FRIEND, ai=ai, monkeypatch=monkeypatch)
    anchor = [p for p in prompts if p["reaction"] == "Anchor the Link"]
    assert bool(anchor) == (feet == 30)
    resolved = [e for e in engine.events if e.event_type == "REACTION_RESOLVED" and e.source_definition_id == ANCHOR]
    assert bool(resolved) == (feet == 30)


@pytest.mark.parametrize("feature,cl,feet", [
    ("BEAUTY_BASE_TURN_THE_BLADE_ASIDE", 5, 60),
    ("tianxia.talent.chains.iron_link_guard", 5, 30),
    ("tianxia.talent.chains.rescue_line", 9, 60),
    ("tianxia.talent.chains.rescue_line", 10, 90),
])
def test_other_reaction_headers_and_printed_realm_growth(feature, cl, feet):
    from combat.factory_compiler import compile_character
    from tests.h1_support import sheet
    bundle = compile_character(sheet([feature], cl=cl), actor_id="actor:factory.range_sample")
    rows = [r for r in bundle["typed_reactions"] if r["feature_id"] == feature]
    assert rows and all(r["range_ft"] == feet for r in rows)


def test_old_null_range_row_uses_header_without_mutation():
    from combat import typed_reactions
    from combat.gate2_runtime_models import Position
    from tests.test_forced_movement_reactions import _engine, _row, REACTOR, LEE
    row = _row("ally_forced_moved", feature_id=ANCHOR, range_ft=None)
    engine = _engine([row])
    reactor, ally = engine.state.actors[REACTOR], engine.state.actors[LEE]
    reactor.position, ally.position = Position(x=3, y=4), Position(x=11, y=4)
    assert not typed_reactions._generic_in_range(engine, reactor, ally, row)
    ally.position = Position(x=9, y=4)
    assert typed_reactions._generic_in_range(engine, reactor, ally, row)
    assert row["range_ft"] is None


@pytest.mark.parametrize("ai", [False, True])
@pytest.mark.parametrize("feet", [30, 40])
def test_legacy_null_range_at_table_commit_reload_replay(tmp_path, monkeypatch, ai, feet):
    from combat.gate3_storage import TYPED_BUNDLES_FILE, load_typed_bundles
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from tests.anchor_support import ME, ROOT

    service, _table, mid = fight(tmp_path, ally=True, feet=feet, ai=ai, legacy_range=True)
    folder = service._match_dir(mid)
    sealed_bytes = (folder / TYPED_BUNDLES_FILE).read_bytes()
    before = load_typed_bundles(folder)
    rows = [row for bundle in before if bundle["actor_id"] == ME
            for row in bundle["typed_reactions"] if row["feature_id"] == ANCHOR]
    assert rows and all(row["range_ft"] is None for row in rows)
    # Reopen before the trigger as well as after commit: today's compiler
    # must not hide a legacy persisted row's missing range.
    service = CombatService(ROOT, tmp_path)
    table = TabletopService(service, tmp_path)
    engine, prompts = push(service, table, mid, FRIEND, ai=ai, monkeypatch=monkeypatch)
    assert any(p["reaction"] == "Anchor the Link" for p in prompts) == (feet == 30)
    assert any(e.event_type == "REACTION_RESOLVED" and e.source_definition_id == ANCHOR
               for e in engine.events) == (feet == 30)
    assert load_typed_bundles(folder) == before
    assert (folder / TYPED_BUNDLES_FILE).read_bytes() == sealed_bytes
