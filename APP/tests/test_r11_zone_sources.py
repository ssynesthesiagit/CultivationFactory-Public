"""Area source metadata survives real table commits, reloads and replays.

This is the provenance prerequisite for Drown the Flame, not a suppression test.
"""

import copy
import json
import zipfile
from types import SimpleNamespace

import pytest

from combat import zone_sources, zones
from combat.factory_compiler import compile_character
from combat.gate4_adapters import ManualControllerAdapter
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService
from tests.test_riders_lane11 import MOON, ROOT, _sheet

FIRE = "FIRE_BASE_CONFLAGRATION"


@pytest.mark.parametrize("auto_turn", [False, True])
@pytest.mark.parametrize("legacy", [False, True])
def test_area_source_snapshot_table_commit_reload(tmp_path, auto_turn, legacy):
    owners = [FACTORY_ACTOR_PREFIX + name for name in ("r11-fire-a", "r11-fire-b")]
    documents = [_sheet(MOON, cl=cl, dc=dc) for cl, dc in ((5, 17), (20, 33))]
    for aid, document in zip(owners, documents):
        stats = document["ability_scores_and_statistics"]
        stats["hit_points"] = {"maximum": 10000}
        stats["abilities"] = [{**row, "modifier": 1000} if row["ability"] == "CON" else dict(row)
                              for row in stats["abilities"]]
        document["path_and_subpath"] = {"path_feature_record_ids": []}
        document["spheres_and_talents"] = {"sphere_record_ids": ["tianxia.sphere.fire"],
                                           "learned_talent_record_ids": [FIRE]}
        folder = tmp_path / "portable_characters" / aid.removeprefix(FACTORY_ACTOR_PREFIX)
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(document))
    bundles = [compile_character(doc, actor_id=aid) for aid, doc in zip(owners, documents)]
    if legacy:
        # Model a sealed pre-contract bundle; loading must not retrofit its areas.
        for bundle in bundles:
            for action in bundle["action_catalog"]:
                spec = action.get("parameters", {}).get("typed", {}).get("zone_spec")
                if spec is not None:
                    spec.pop("source_profile", None)
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    mid = combat._finish_factory_match(bundles, owners,
        {owners[0]: "team:factory", owners[1]: "team:opponents"},
        {owners[0]: {"x": 3, "y": 6}, owners[1]: {"x": 13, "y": 8}},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [owners[0]], [owners[1]],
        control_modes={aid: "MANUAL" for aid in owners},
        match_seed="R11-AREA-SOURCES", display_name="Independent fire source snapshots",
        maximum_rounds=20)["match_id"]
    original = combat.controller
    selected = None

    class SelectedController:
        def choose_primary_action(self, context):
            # Advance turns automatically; the stock strategy is not claimed to
            # choose duplicate Conflagrations (it prunes such cell targets).
            candidate = next(c for c in context.legal_candidates
                             if c.source_definition_id == selected.source_definition_id and c.kind == selected.kind)
            return ManualControllerAdapter(lambda _: (candidate.candidate_id, ())).choose_primary_action(context)

        def __getattr__(self, name):
            return getattr(original, name)

    if auto_turn:
        combat.controller = SelectedController()

    def take(candidate):
        nonlocal selected
        automate = auto_turn and candidate.kind.value == "END_TURN"
        combat.set_controller_mode(mid, actor_id=candidate.actor_id,
                                   controller_mode="LOCAL_AUTO" if automate else "MANUAL")
        candidate = next(c for c in combat._load_session(mid).engine.legal_candidates()
                         if c.source_definition_id == candidate.source_definition_id
                         and c.kind == candidate.kind and c.destination == candidate.destination)
        selected = candidate
        menu = table.state(mid)["menu"]
        result = (table.auto_step(mid, 0) if automate else
                  table.act(mid, selected.candidate_id, menu["decision_id"], menu["state_version"], 0))
        assert result["status"] == "COMMITTED", result
        session = CombatService(ROOT, tmp_path)._load_session(mid)
        assert session.verify()["status"] == "PASS"
        assert session.mechanical.replay()["status"] == "PASS"
        return session

    def end_turn():
        return take(next(c for c in combat._load_session(mid).engine.legal_candidates() if c.kind.value == "END_TURN"))

    snapshots = {}
    for owner, cl, dc in zip(owners, (5, 20), (17, 33)):
        while table.state(mid)["menu"]["actor_id"] != owner:
            end_turn()
        for cast in range(2):
            engine = combat._load_session(mid).engine
            candidates = [c for c in engine.legal_candidates()
                if c.source_definition_id in engine.action_catalog
                and engine.action_catalog[c.source_definition_id].parameters.get("typed", {}).get("source") == FIRE
                and c.destination is not None]
            assert candidates
            # Keep concentration-copy provenance independent of damage/save luck.
            candidate = max(candidates, key=lambda c: min(engine.grid.distance_ft(c.destination, a.position)
                                                         for a in engine.state.actors.values()))
            session = take(candidate)
            own = [z for z in zones.typed_zones(session.engine) if z.owner_id == owner]
            assert len(own) == cast + 1
            for zone in own:
                profile = zone.trigger_profile.get("source_profile")
                if legacy:
                    assert profile is None
                else:
                    assert profile is not None, "persistent areas need sealed authoritative source metadata"
                    assert profile["mechanic_id"] == FIRE
                    assert profile["sphere_id"] == "tianxia.sphere.fire"
                    assert profile["source_tags"] == ["Fire"]
                    assert profile["source_cl"] == cl and profile["save_dc"] == dc
                    assert profile["duration_kind"] == "minutes" and profile["concentration"] == 1
                    assert len(profile["text_sha256"]) == 64
                    assert profile == zone.trigger_profile["source_profile"]
                if zone.zone_id in snapshots:
                    assert profile == snapshots[zone.zone_id]
                snapshots[zone.zone_id] = copy.deepcopy(profile)
            end_turn()
            if cast == 0:
                end_turn()
    # All four exact source instances survive later commits and fresh services.
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    assert len(zones.typed_zones(session.engine)) == 4
    for zone in zones.typed_zones(session.engine):
        assert zone.trigger_profile.get("source_profile") == snapshots[zone.zone_id]


def test_explicit_tags_do_not_come_from_fire_damage_sphere_or_visuals():
    typed = {"source": "test:area", "sphere": "test:sphere", "numbers": {"cl": 7, "save_dc": 21},
             "duration": {"kind": "minutes"}, "effects": [
                 {"type": "damage", "damage_types": ["fire"]}, {"type": "zone"}]}
    mechanic = {"source": {"text_sha256": "sealed"}, "sphere_id": "test:sphere"}
    profile = zone_sources.compile_profile(typed, mechanic, typed["duration"])
    assert profile["source_tags"] == []
    typed["sphere"] = "tianxia.sphere.fire"
    assert zone_sources.compile_profile(typed, mechanic, typed["duration"])["source_tags"] == []
    zone = SimpleNamespace(trigger_profile={"source_profile": profile, "visual": {"material": "fire"}})
    assert zone_sources.of(zone)["source_tags"] == []
    returned = zone_sources.of(zone)
    returned["source_tags"].append("Fire")
    assert zone_sources.of(zone)["source_tags"] == []
    zone.trigger_profile.pop("source_profile")
    assert zone_sources.of(zone) is None


def test_selected_option_tags_and_numbers_are_sealed_independently():
    typed = {"source": "test:menu", "option_label": "selected", "numbers": {"cl": 8, "save_dc": 22},
             "duration": {"kind": "instant"}, "effects": [{"type": "zone", "source_tags": ["Water", "Water"]}]}
    mechanic = {"effects": [{"type": "zone", "source_tags": ["Fire"]}]}
    profile = zone_sources.compile_profile(typed, mechanic, {"kind": "rounds"})
    assert profile["source_tags"] == ["Water"]
    assert profile["activation_duration_kind"] == "instant" and profile["duration_kind"] == "rounds"
    typed["numbers"].update(cl=20, save_dc=99)
    typed["effects"][0]["source_tags"].append("Fire")
    assert profile["source_tags"] == ["Water"]
    assert profile["source_cl"] == 8 and profile["save_dc"] == 22
    actual = zone_sources.capture(profile, typed["numbers"])
    assert actual["source_cl"] == 20 and actual["save_dc"] == 99
    assert actual["source_tags"] == ["Water"]
    assert profile["source_cl"] == 8
    assert zone_sources.capture(None, typed["numbers"]) is None


def test_instantaneous_fireball_never_compiles_a_persistent_area():
    sheet = _sheet(MOON)
    sheet["path_and_subpath"] = {"path_feature_record_ids": []}
    sheet["spheres_and_talents"] = {"sphere_record_ids": ["tianxia.sphere.fire"],
                                   "learned_talent_record_ids": ["FIRE_TAL_FIREBALL_ART"]}
    bundle = compile_character(sheet, actor_id=FACTORY_ACTOR_PREFIX + "r11-fireball")
    fireballs = [a["parameters"]["typed"] for a in bundle["action_catalog"]
                 if a.get("parameters", {}).get("typed", {}).get("source") == "FIRE_TAL_FIREBALL_ART"]
    assert fireballs
    assert all("zone_spec" not in typed for typed in fireballs)
