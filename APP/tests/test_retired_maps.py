"""SOL213: retirement affects selection, never historical sealed arenas."""
import json

import pytest

from combat.canonical import canonical_sha256
from combat.gate5_service import CombatService, CombatServiceError, DEFAULT_FACTORY_ARENA, FACTORY_ACTOR_PREFIX
from combat.tabletop import TabletopMapStore, to_battlefield
from combat.tabletop_service import TabletopService
from tests.test_builtin_arenas import ROOT, RETIRED_IDS, CLASSIC
from tests.retired_arena_support import HistoricalArenaWriter
from tests.test_factory_live_match import _install


def test_retirement_is_general_builtin_listing_metadata(tmp_path):
    builtins = tmp_path / "builtins"
    builtins.mkdir()
    owner = tmp_path / "owners"
    owner.mkdir()
    document = CombatService(ROOT, tmp_path).tabletop_maps.get(RETIRED_IDS[0])
    # Arbitrary ids exercise the general flag, not a special case for these maps.
    for map_id, folder, retired in (("old-map", builtins, True), ("new-map", builtins, False),
                                    ("bamboo-road", owner, True), ("wooden-dungeon", owner, False)):
        (folder / f"{map_id}.json").write_text(json.dumps({**document, "map_id": map_id, "retired": retired}))
    store = TabletopMapStore(owner, builtins)
    assert {row["map_id"] for row in store.list()} == {"new-map", "bamboo-road", "wooden-dungeon"}
    assert "retired" not in store.get("old-map")
    assert "battlefield:map.old-map" not in store.arenas()
    assert to_battlefield(store.get("old-map"))["stable_id"] == "battlefield:map.old-map"


@pytest.mark.parametrize("map_id", RETIRED_IDS)
def test_retired_maps_cannot_create_new_fights(tmp_path, map_id):
    _install(tmp_path, "left")
    _install(tmp_path, "right")
    service = CombatService(ROOT, tmp_path)
    assert map_id not in {row["map_id"] for row in service.tabletop_maps.list()}
    assert "battlefield:map." + map_id not in service.factory_arenas()
    with pytest.raises(CombatServiceError, match="That arena is not available"):
        service.create_factory_match(project_ids=["left"],
            opponent_actor_ids=[FACTORY_ACTOR_PREFIX + "right"], arena_id="battlefield:map." + map_id)
    assert DEFAULT_FACTORY_ARENA in service.factory_arenas()


def test_both_picker_endpoints_and_editor_copy_list_exclude_retired_maps(tmp_path):
    # Invoke real endpoint functions directly: no sockets, HTTP portal or browser.
    from app.api import create_app
    from app.core import Settings

    app = create_app(Settings.from_env(ROOT, tmp_path))
    endpoints = {route.path: route.endpoint for route in app.routes
                 if hasattr(route, "endpoint") and "GET" in (getattr(route, "methods", None) or ())}
    factory = endpoints["/api/combat/factory-arenas"]()
    catalog = endpoints["/api/tabletop/maps"]()
    retired = {"battlefield:map." + i for i in RETIRED_IDS} | set(CLASSIC)
    assert not retired.intersection(row["arena_id"] for row in factory + catalog["builtin"])
    assert not any("Pillar Arena" in row["display_name"] or "Mist Courtyard" in row["display_name"]
                   for row in factory + catalog["builtin"] + catalog["maps"])
    assert catalog["default_arena_id"] == DEFAULT_FACTORY_ARENA == factory[0]["arena_id"]
    for file, api in (("app.js", "/combat/factory-arenas"), ("tabletop/tabletop.js", "/tabletop/maps"),
                      ("tabletop/mapeditor.js", "/tabletop/maps")):
        assert api in (ROOT / "static" / file).read_text()


def _pre_retirement_fight(tmp_path, map_id):
    """Create a sealed historical fixture; also used by opt-in renderer checks."""
    class BeforeRetirement(CombatService):
        """Fixture writer exposes the unchanged geometry once to create an old save."""
        def factory_arenas(self):
            arenas = super().factory_arenas()
            arenas["battlefield:map." + map_id] = to_battlefield(self.tabletop_maps.get(map_id))
            return arenas

    for pid in ("left", "right"):
        _install(tmp_path, pid)
    writer = BeforeRetirement(ROOT, tmp_path)
    view = writer.create_factory_match(project_ids=["left"],
        opponent_actor_ids=[FACTORY_ACTOR_PREFIX + "right"], arena_id="battlefield:map." + map_id,
        match_seed="SOL213-SEALED-" + map_id, maximum_rounds=2)
    mid = view["match_id"]
    return writer, mid


@pytest.mark.parametrize("map_id", RETIRED_IDS)
def test_pre_retirement_sealed_fight_loads_verifies_and_replays(tmp_path, map_id):
    writer, mid = _pre_retirement_fight(tmp_path, map_id)
    writer.local_step(mid)
    sealed = writer._load_session(mid).engine.battlefield_document
    digest = canonical_sha256(sealed)
    reader = CombatService(ROOT, tmp_path)
    assert "battlefield:map." + map_id not in reader.factory_arenas()
    loaded = reader._load_session(mid)
    assert canonical_sha256(loaded.engine.battlefield_document) == digest
    assert loaded.verify()["status"] == "PASS"
    assert reader.replay(mid)["status"] == "PASS"
    table = TabletopService(reader, tmp_path)
    state = table.state(mid)
    assert state["map"]["map_id"] == map_id
    assert table.auto_step(mid, state["last_sequence"])["status"] == "COMMITTED"
    reloaded = CombatService(ROOT, tmp_path)
    assert canonical_sha256(reloaded._load_session(mid).engine.battlefield_document) == digest
    assert reloaded._load_session(mid).verify()["status"] == "PASS"
    assert reloaded.replay(mid)["status"] == "PASS"


def test_rule_retirement_is_general_metadata_and_never_sealed(tmp_path):
    # Use arbitrary rule ids, so this fails for a per-arena special case.
    source = tmp_path / "source"
    rules = source / "combat/rules/arenas"
    rules.mkdir(parents=True)
    document = CombatService(ROOT, tmp_path).factory_arenas(include_retired=True)[CLASSIC[0]]
    for name, flag in (("old", True), ("new", False)):
        (rules / f"{name}.json").write_text(json.dumps({**document, "stable_id": "battlefield:" + name, "retired": flag}))
    service = CombatService(ROOT, tmp_path / "data")
    service.source_root = source  # isolated catalog only; no engine files copied
    assert set(service.factory_arenas()) == {"battlefield:new"}
    historical = service.factory_arenas(include_retired=True)
    assert set(historical) == {"battlefield:old", "battlefield:new"}
    assert all("retired" not in arena for arena in historical.values())


@pytest.mark.parametrize("arena_id", CLASSIC)
def test_retired_classic_arena_rejected_for_new_fight_but_sealed_save_replays(tmp_path, arena_id):
    for pid in ("left", "right"):
        _install(tmp_path, pid)
    kwargs = dict(project_ids=["left"], opponent_actor_ids=[FACTORY_ACTOR_PREFIX + "right"],
                  arena_id=arena_id, match_seed="SOL213b-SEALED-" + arena_id, maximum_rounds=2)
    reader = CombatService(ROOT, tmp_path)
    with pytest.raises(CombatServiceError, match="That arena is not available"):
        reader.create_factory_match(**kwargs)
    writer = HistoricalArenaWriter(ROOT, tmp_path)
    mid = writer.create_factory_match(**kwargs)["match_id"]
    writer.local_step(mid)
    sealed = writer._load_session(mid).engine.battlefield_document
    digest = canonical_sha256(sealed)
    assert "retired" not in sealed
    assert arena_id not in reader.factory_arenas()
    loaded = reader._load_session(mid)
    assert canonical_sha256(loaded.engine.battlefield_document) == digest
    assert loaded.verify()["status"] == reader.replay(mid)["status"] == "PASS"
    table = TabletopService(reader, tmp_path)
    state = table.state(mid)
    assert table.auto_step(mid, state["last_sequence"])["status"] == "COMMITTED"
    reloaded = CombatService(ROOT, tmp_path)
    assert canonical_sha256(reloaded._load_session(mid).engine.battlefield_document) == digest
    assert reloaded._load_session(mid).verify()["status"] == reloaded.replay(mid)["status"] == "PASS"
