"""SOL118: real builder admission and accepted table actions, reloads and replay.

No browser is launched. Browser presentation remains a lead check outside the
sandbox; API table menus and their help are checked here.
"""
import hashlib
import json
import os
from pathlib import Path
import zipfile

import pytest

from app.api import create_app
from app.core import Database, FoundryError, Settings
from combat import ext
from combat.ext import cai_clan as cai
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from non_sphere_authority.owner_subpaths import load_owner_subpaths
from non_sphere_authority.service import NonSphereAuthorityService
from tests.h1_support import ROOT, sheet
from tests.test_lock2_persistence import act
from tests.test_tabletop_hunt6 import LEFT, ALLY, RIGHT, PROJECTS, on_hold, HOLD
from tests.test_ns1r_non_sphere_authority import authority as ns_authority, insert_project

SUBPATH = cai.BASE.split(".feature.")[0]
QI = "tianxia.path.qi_cultivation"
FEATURES = [(3, cai.INVEST), (6, cai.EDICT), (10, cai.DUTY), (14, cai.FLARE), (18, cai.COURT)]


def _features(cl):
    return [feature for level, feature in FEATURES if level <= cl]


def _loaded(combat, mid):
    return CombatService(ROOT, combat.userdata_root)._load_session(mid)


def _fight(tmp_path, cl=15, modes=None, extra_features=(), ally_features=None):
    for name, actor_id in zip(("left", "ally", "right"), (LEFT, ALLY, RIGHT)):
        owned = [*_features(cl), *extra_features] if name == "left" else (
            ally_features if name == "ally" and ally_features is not None else ["AIR_BASE_WIND_LASH"])
        doc = sheet(owned, cl=cl, key="CHA", dc=30)
        doc["identity"]["display_name"] = name.title()
        doc["ability_scores_and_statistics"]["hit_points"]["maximum"] = 300
        folder = tmp_path / "portable_characters" / PROJECTS[name]
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(doc))
    combat = CombatService(ROOT, tmp_path)
    combat.tabletop_maps.save({"display_name": "Cai yard", "width_squares": 12, "height_squares": 8,
        "walls": [], "starts": {"team1": [[3, 4], [3, 6]], "team2": [[4, 4]]}})
    mid = combat.create_factory_match(project_ids=[PROJECTS["left"], PROJECTS["ally"]], opponent_actor_ids=[RIGHT],
        arena_id="battlefield:map.cai-yard", match_seed="SOL118-CAI",
        control_modes=modes or {a: "MANUAL" for a in (LEFT, ALLY, RIGHT)})["match_id"]
    table = TabletopService(combat, tmp_path)
    _turn(table, mid, LEFT)
    return combat, table, mid


def _turn(table, mid, actor):
    for _ in range(12):
        if table.state(mid)["menu"]["actor_id"] == actor:
            return
        assert act(table, mid, "end")["status"] == "COMMITTED"
    raise AssertionError("actor did not receive its turn")


def _use(table, mid, name, picks=(), *, target=None, destination=None):
    state = table.state(mid)
    menu = state["menu"]
    group = next(g for g in menu["actions"] if g["label"].startswith(name))
    options = group["options"]
    option = next(o for o in options if (target is None or target in (o.get("target_ids") or []))
                  and (destination is None or o.get("destination") == destination))
    answers, prompts = [], []
    for _ in range(8):
        result = table.act(mid, option["candidate_id"], menu["decision_id"], menu["state_version"], state["last_sequence"], answers)
        if result["status"] == "COMMITTED":
            return prompts, option
        assert result["status"] == "REACTION_REQUIRED", result
        prompt = result["reaction"]
        prompts.append(prompt)
        ids = list(picks) if prompt.get("choice") else []
        if not ids and prompt.get("choice"):
            ids = [prompt["choice"]["options"][0]["id"]]
        answers.append({**prompt["context"], "selection": "USE", "option_ids": ids})
    raise AssertionError("too many choices")


@pytest.fixture
def cai_builder_environment(request):
    """Fresh builds normally; opt-in reuse of this lane's actual native results.

    Reuse avoids duplicating the large Factory fixture just to inspect the same
    captured CL5/CL15 candidates. It is limited to the prescribed task basetemp.
    """
    if os.getenv("SOL118_REUSE_BUILDER_EVIDENCE") != "1":
        return request.getfixturevalue("catalog_environment")
    settings = Settings.from_env(ROOT, Path("/var/tmp/sol118-pytest/vendor_session0"))
    db = Database(settings)
    with db.connection() as conn:
        from app.core import CORE_PACK_ID, CORE_PACK_VERSION
        row = conn.execute("SELECT pack_hash FROM content_packs WHERE pack_id=? AND version=?",
                           (CORE_PACK_ID, CORE_PACK_VERSION)).fetchone()
    assert row is not None
    return {"settings": settings, "db": db, "report": {"pack_hash": row["pack_hash"]}, "reuse": True}


@pytest.mark.parametrize("cl,mode", [(5, "detailed"), (15, "quick")])
def test_builder_can_select_and_create_cai_at_5_and_15(cai_builder_environment, monkeypatch, cl, mode):
    catalog_environment = cai_builder_environment
    from character_creation.compiler_selection_authority import PINNED_CORE_PACK_HASH
    assert catalog_environment["report"]["pack_hash"] == PINNED_CORE_PACK_HASH
    browser_opt_in = os.getenv("SOL118_RUN_BROWSER") == "1"
    monkeypatch.setenv("TIANXIA_BROWSER_EXECUTABLE",
                      "/usr/bin/chromium" if browser_opt_in else "/var/tmp/sol118-pytest/BROWSER_FORBIDDEN")
    app = create_app(catalog_environment["settings"])
    builder = app.state.character_builder
    choices = next(c["choices"] for c in builder.options()["categories"] if c["slot_id"] == "subpath_choice")
    cai_choice = next(c for c in choices if c["choice_id"] == SUBPATH)
    assert cai_choice["owning_path_id"] == QI
    assert cai_choice["pack_id"] == "tianxia.owner.subpaths.cai_clan"
    assert "{" not in cai_choice["description"]
    if catalog_environment.get("reuse"):
        with catalog_environment["db"].connection() as conn:
            row = conn.execute("SELECT r.run_id FROM character_creation_runs r JOIN projects p "
                               "ON p.project_id=r.project_id WHERE p.working_name=? AND r.idempotency_key=?",
                               (f"Cai CL{cl}", f"sol118-build-{cl}")).fetchone()
        assert row is not None
        run = app.state.character_creation.get(row["run_id"])
        assert run["request"]["autogen_seed"] == f"SOL118-CL{cl}"
    else:
        project = builder.create_project(working_name=f"Cai CL{cl}", concept="Colorless-light retainer commander",
            source_reference=None, target_cl=cl, power_band="rival/boss", creation_mode=mode,
            generation_route="ai_bootstrap", ability_scores={}, autogen_seed=f"SOL118-CL{cl}",
            selections={"path_choice": [QI], "subpath_choice": [SUBPATH]}, method_planning_mode="AUTO")
        builder.commit_normal_first_cycle_catalog_choices(project["project_id"])
        run = app.state.character_creation.start(project["project_id"], execution_mode="STANDARD_API",
            idempotency_key=f"sol118-build-{cl}", controller_route="DETERMINISTIC_CREATIVE_CONTROLLER")
    if run["status"] != "READY_FOR_REVIEW":
        # Full creation reaches Command 6's real browser consumer. Under the
        # owner's no-browser rule only that exact guarded boundary may remain.
        assert not browser_opt_in
        assert run["status"] == "NEEDS_REVIEW"
        blockers = run["blockers"]
        assert len(blockers) == 1 and blockers[0]["code"] == "COMMAND6_CHARACTER_GM_CONSUMER_FAILED"
        harness = blockers[0]["details"]["consumer_report"]["harness_run"]
        assert harness["skipped"] is True and harness["exit_code"] is None
        assert "Explicit TIANXIA_BROWSER_EXECUTABLE is missing" in harness["stderr"]
    candidate = app.state.character_creation.load_candidate_gm_context(run["run_id"])
    owner_sheet = candidate["owner_character_sheet"]
    assert owner_sheet["identity"]["cultivation_level"] == cl
    compiled = compile_character(owner_sheet, actor_id=LEFT)
    sources = {a["parameters"].get("typed", {}).get("source") for a in compiled["action_catalog"]}
    assert cai.INVEST in sources
    assert (cai.FLARE in sources) == (cl >= 14)
    assert cai.COURT not in sources
    # The source progression in the authenticated builder snapshot is the same
    # one used by normal and seeded Quick Build's subpath menu.
    authority = NonSphereAuthorityService(catalog_environment["db"])
    record = authority.project_locked_subpath_catalog_record(SUBPATH)
    progression = record["compatibility"]["factory"]["stage2_authority"]["feature_progression"]
    assert [f["canonical_id"] for f in progression if f["granted_at_cl"] <= cl] == _features(cl)


def test_optional_owner_catalog_is_inert_without_files_and_rejects_collisions(tmp_path):
    assert load_owner_subpaths(tmp_path) == ([], {})
    rows, commitments = load_owner_subpaths(ROOT)
    assert SUBPATH in {r["canonical_id"] for r in rows} and len(commitments) == 1
    with pytest.raises(FoundryError, match="identity"):
        load_owner_subpaths(ROOT, [SUBPATH])


@pytest.mark.parametrize("prefix", ["BACKGROUND", "OWNER_SUBPATH"])
def test_supplement_conflict_preserves_pack_specific_error_code(tmp_path, prefix):
    from catalog.service import CatalogService
    db = Database(Settings.from_env(ROOT, tmp_path / "data"))
    db.migrate()
    pack_id = f"test.{prefix.lower()}"
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO content_packs(pack_id,version,pack_hash,lifecycle_state,authority,"
            "installed_path,manifest_json,installed_at) VALUES(?,?,?,?,?,?,?,?)",
            (pack_id, "1.0.0", "0" * 64, "published", "canonical", str(tmp_path), "{}", "2026-10-04"))
    with pytest.raises(FoundryError) as conflict:
        CatalogService(db)._rebuild_builtin_supplement(
            [], "1" * 64, tmp_path, pack_id=pack_id, pack_version="1.0.0",
            manifest_schema="test.supplement.v1", error_prefix=prefix,
            subject="test supplement", record_directory="test-records")
    assert conflict.value.code == f"{prefix}_PACK_VERSION_HASH_CONFLICT"


def test_owner_addition_preserves_existing_non_sphere_state_identity(ns_authority, monkeypatch):
    added, db = ns_authority
    with monkeypatch.context() as patch:
        patch.setattr("non_sphere_authority.service.load_owner_subpaths", lambda *args: ([], {}))
        sealed = NonSphereAuthorityService(db)
    assert added.authority_snapshot_hash == sealed.authority_snapshot_hash
    insert_project(db, "sol118-existing-state", target_cl=5)
    sealed.initialize_for_project("sol118-existing-state", target_cl=5,
                                  path_ids=[QI], method_id="METHOD-001")
    before = sealed.get_state("sol118-existing-state")
    after = added.get_state("sol118-existing-state")
    assert before == after


def test_generated_text_and_reviews_match_authored_rules():
    rules = json.loads((ROOT / "authority/typed_mechanics/rules_text.json").read_text())
    authority = json.loads((ROOT / "authority/Tianxia_Typed_Mechanics_Authority_R1.json").read_text())["mechanics"]
    rows, _ = load_owner_subpaths(ROOT)
    for feature in next(r for r in rows if r["canonical_id"] == SUBPATH)["feature_progression"]:
        fid, text = feature["canonical_id"], feature["source_markdown"]
        assert rules[fid] == text
        assert authority[fid]["typing_status"] == "reviewed_final"
        assert authority[fid]["source"]["text_sha256"] == hashlib.sha256(text.encode()).hexdigest()
    assert not {f for _, f in FEATURES} & set(json.loads((ROOT / "authority/typed_mechanics/reviewed_final.d/subpaths.json").read_text())["mechanics"])


def test_published_owner_sections_have_exact_locations_and_reject_tampering(tmp_path):
    from character_creation.constructed_arts.sources import published_section
    rows, _ = load_owner_subpaths(ROOT)
    for feature in rows[0]["feature_progression"]:
        source = feature["source"]
        assert published_section(tmp_path, source) == feature["source_markdown"]
        for key, wrong in [("section_sha256", "0" * 64), ("line_end", 1),
                           ("json_pointer", "/entries/0/source_markdown"),
                           ("factory_source_path", "/etc/passwd")]:
            assert published_section(tmp_path, {**source, key: wrong}) == ""


@pytest.mark.parametrize("cl,count,ac", [(5, 1, 1), (15, 2, 2)])
def test_layer_owner_choice_payment_saved_bonuses_and_replay(tmp_path, cl, count, ac):
    combat, table, mid = _fight(tmp_path, cl)
    prompts, _ = _use(table, mid, "Empyreal Layer", [ALLY] if count == 1 else [LEFT, ALLY])
    assert prompts and "Empyreal Layer" in prompts[0]["moment"] and "Left" in prompts[0]["moment"]
    loaded = _loaded(combat, mid)
    actor = loaded.engine.state.actors[LEFT]
    assert actor.resources["resource:core.qi"] == 28
    layers = [(a, c) for a in loaded.engine.state.actors.values() for c in a.conditions.values() if c.condition_id == cai.LAYER]
    assert len(layers) == count
    assert all(c.expires_on == "CONCENTRATION_END" and c.data["ac"] == ac for a, c in layers)
    assert all(type(v) in (int, str) for _, c in layers for v in c.data.values())
    assert all(ext.run("ac", loaded.engine, a)[-1:] != [] for a, _ in layers)
    if cl >= 10:
        assert loaded.engine.state.actors[ALLY].temporary_hp == 6
        assert cai.layer_wisdom(loaded.engine, loaded.engine.state.actors[ALLY], "WIS", 15, "test", None) == 2
        assert cai.layer_wisdom(loaded.engine, loaded.engine.state.actors[ALLY], "DEX", 15, "test", None) is None
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("native_recipient", [False, True])
def test_layer_reduces_once_round_and_ends_with_concentration_through_table(monkeypatch, tmp_path, native_recipient):
    combat, table, mid = _fight(tmp_path, 5)
    _use(table, mid, "Empyreal Layer", [ALLY])
    def packets(engine):
        ally = engine.state.actors[ALLY]
        if native_recipient:
            engine.typed_actor_ids.discard(ALLY)
        engine._commit_damage(ally, 3, "FORCE", "test:packet1", RIGHT, None, reaction_depth=0)
        engine._commit_damage(ally, 10, "FORCE", "test:packet2", RIGHT, None, reaction_depth=0)
    on_hold(monkeypatch, packets)
    assert act(table, mid, HOLD)["status"] == "COMMITTED"
    loaded = _loaded(combat, mid)
    damages = [e for e in loaded.engine.events if e.source_definition_id in {"test:packet1", "test:packet2"} and e.event_type == "DAMAGE_COMMITTED"]
    assert [e.payload["reduced_to"] for e in damages] == [0, 10]
    assert loaded.engine.state.actors[ALLY].current_hp == 290
    # End via the real accepted tabletop Concentration control.
    state = table.state(mid)
    end = next(g for g in state["menu"]["actions"] if "End Empyreal Layers" in g["label"])
    _use(table, mid, end["label"])
    loaded = _loaded(combat, mid)
    assert not list(cai._active_layers(loaded.engine, loaded.engine.state.actors[ALLY]))
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_judgment_hit_opens_one_radiant_ally_strike_and_replays(tmp_path):
    combat, table, mid = _fight(tmp_path)
    _use(table, mid, "Judgment Saber", target=RIGHT)
    loaded = _loaded(combat, mid)
    assert any(c.condition_id == cai.CENSURE for c in loaded.engine.state.actors[RIGHT].conditions.values())
    _turn(table, mid, ALLY)
    _use(table, mid, "Wind Lash: Cut", target=RIGHT)
    loaded = _loaded(combat, mid)
    assert not any(c.condition_id == cai.CENSURE for c in loaded.engine.state.actors[RIGHT].conditions.values())
    claims = [e for e in loaded.engine.events if e.event_type == "PASSIVE_TRIGGERED" and "claims Censure" in e.payload.get("text", "")]
    assert len(claims) == 1 and claims[0].actor_id == ALLY
    bonus = [e for e in loaded.engine.events if e.event_type == "DAMAGE_ROLLED"
             and e.source_definition_id == cai.EDICT]
    assert len(bonus) == 1 and bonus[0].payload["expression"] == "2d8+0"
    assert loaded.engine.state.actors[LEFT].resources["resource:core.qi"] == 29
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_white_sun_hits_only_hostiles_and_protects_invested_allies(tmp_path):
    combat, table, mid = _fight(tmp_path)
    _use(table, mid, "Empyreal Layer", [LEFT, ALLY])
    _use(table, mid, "White Sun Judgment", destination={"x": 4, "y": 4})
    loaded = _loaded(combat, mid)
    saves = [e.actor_id for e in loaded.engine.events if e.event_type == "SAVE_ROLLED" and cai.FLARE in e.source_definition_id]
    assert saves == [RIGHT]
    assert loaded.engine.state.actors[ALLY].current_hp == 300
    protection_rolls = [e for e in loaded.engine.events if e.event_type == "DAMAGE_ROLLED"
                        and e.payload.get("reason") == "White Sun Judgment protects invested allies"]
    assert len(protection_rolls) == 1
    assert set(protection_rolls[0].target_ids) == {LEFT, ALLY}
    assert loaded.engine.state.actors[ALLY].temporary_hp == max(6, protection_rolls[0].payload["total"], 1)
    assert any(c.condition_id.endswith("reaction_denied") for c in loaded.engine.state.actors[RIGHT].conditions.values())
    assert loaded.engine.state.actors[LEFT].resources["resource:core.qi"] == 24
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_colorless_court_replaces_layers_once_combat_and_replays(tmp_path):
    combat, table, mid = _fight(tmp_path, 18)
    _use(table, mid, "Empyreal Layer", [LEFT, ALLY])
    assert act(table, mid, "end")["status"] == "COMMITTED"
    _turn(table, mid, LEFT)
    _use(table, mid, "Court Beneath the Colorless Star", [LEFT, ALLY])
    loaded = _loaded(combat, mid)
    actor = loaded.engine.state.actors[LEFT]
    assert actor.resources["resource:core.qi"] == 20
    assert cai._court(actor)
    assert len(list(cai._active_layers(loaded.engine, loaded.engine.state.actors[ALLY]))) == 1
    layer = next(cai._active_layers(loaded.engine, loaded.engine.state.actors[ALLY]))
    assert (layer.data["ac"], layer.data["wisdom_save"], layer.data["reduction"]) == (2, 2, 6)
    assert not any(g["label"].startswith(("Court Beneath", "Empyreal Layer")) for g in table.state(mid)["menu"]["actions"])
    assert any(g["label"] == "End Empyreal Layers" for g in table.state(mid)["menu"]["actions"])
    _use(table, mid, "Judgment Saber", target=RIGHT)
    loaded = _loaded(combat, mid)
    mark = next(c for c in loaded.engine.state.actors[RIGHT].conditions.values() if c.condition_id == cai.CENSURE)
    assert mark.data["dice"] == 3
    _use(table, mid, "End Empyreal Layers")
    loaded = _loaded(combat, mid)
    assert not cai._court(loaded.engine.state.actors[LEFT])
    assert any(c.condition_id == cai.COURT_USED for c in loaded.engine.state.actors[LEFT].conditions.values())
    assert next(c for c in loaded.engine.state.actors[RIGHT].conditions.values() if c.condition_id == cai.CENSURE).data["dice"] == 3
    assert act(table, mid, "end")["status"] == "COMMITTED"
    _turn(table, mid, LEFT)
    labels = [g["label"] for g in table.state(mid)["menu"]["actions"]]
    assert "Empyreal Layer" in labels
    assert not any(label.startswith("Court Beneath") for label in labels)
    loaded = _loaded(combat, mid)
    assert not any(c.condition_id == cai.CENSURE for c in loaded.engine.state.actors[RIGHT].conditions.values())
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_unowned_plugin_does_not_change_seeded_ai_continuation(monkeypatch):
    from tests.test_hunt32_inert_replay import _capture
    enabled = _capture()
    for point, callbacks in list(ext._HOOKS.items()):
        monkeypatch.setitem(ext._HOOKS, point, [f for f in callbacks if f.__module__ != cai.__name__])
    assert _capture() == enabled


def test_secondary_qi_uses_its_own_level_and_key_for_saber():
    doc = sheet([cai.INVEST], cl=15, key="STR")
    doc["path_and_subpath"]["paths"] = [
        {"path_id": "tianxia.path.body_refining", "effective_cl": 15, "key_ability": "STR"},
        {"path_id": QI, "effective_cl": 5, "key_ability": "CHA"},
    ]
    doc["ability_scores_and_statistics"]["abilities"][-1].update(score=18, modifier=4)
    compiled = compile_character(doc, actor_id=LEFT)
    actions = compiled["action_catalog"]
    saber = next(a for a in actions if a["display_name"] == "Judgment Saber")
    typed = saber["parameters"]["typed"]
    assert typed["numbers"]["cl"] == 5
    assert typed["numbers"]["key_mod"] == 4
    assert typed["effects"][0]["on_hit"][0]["dice"]["count"] == 2


def test_censure_is_not_consumed_by_damage_without_an_attack(monkeypatch, tmp_path):
    combat, table, mid = _fight(tmp_path)
    _use(table, mid, "Judgment Saber", target=RIGHT)
    def packet(engine):
        engine._commit_damage(engine.state.actors[RIGHT], 5, "FORCE",
                              "test:non-attack", ALLY, None, reaction_depth=0)
    on_hold(monkeypatch, packet)
    assert act(table, mid, HOLD)["status"] == "COMMITTED"
    loaded = _loaded(combat, mid)
    assert any(c.condition_id == cai.CENSURE for c in loaded.engine.state.actors[RIGHT].conditions.values())
    assert not any(e.event_type == "PASSIVE_TRIGGERED" and "claims Censure" in e.payload.get("text", "")
                   for e in loaded.engine.events)
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_ending_layers_preserves_an_unrelated_concentration_in_saved_table(tmp_path):
    from combat import concentration
    combat, table, mid = _fight(tmp_path, 5, extra_features=["DARK_BASE_DARKNESS"])
    _use(table, mid, "Darkness", destination={"x": 9, "y": 4})
    loaded = _loaded(combat, mid)
    darkness = concentration.sources(loaded.engine.state.actors[LEFT])
    assert len(darkness) == 1
    _use(table, mid, "Empyreal Layer", [LEFT])
    loaded = _loaded(combat, mid)
    assert len(concentration.sources(loaded.engine.state.actors[LEFT])) == 2
    _use(table, mid, "End Empyreal Layers")
    loaded = _loaded(combat, mid)
    assert concentration.sources(loaded.engine.state.actors[LEFT]) == darkness
    assert not list(cai._active_layers(loaded.engine, loaded.engine.state.actors[LEFT]))
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_a_second_administrator_does_not_refresh_reduction_or_stack_ac(monkeypatch, tmp_path):
    combat, table, mid = _fight(tmp_path, 5, ally_features=[cai.INVEST])
    _use(table, mid, "Empyreal Layer", [ALLY])
    def packet(engine):
        amount = 3 if engine.state.current_actor_id == LEFT else 10
        engine._commit_damage(engine.state.actors[ALLY], amount, "FORCE",
                              "test:multiple-administrators", RIGHT, None, reaction_depth=0)
    on_hold(monkeypatch, packet)
    assert act(table, mid, HOLD)["status"] == "COMMITTED"
    _turn(table, mid, ALLY)
    _use(table, mid, "Empyreal Layer", [ALLY])
    assert act(table, mid, HOLD)["status"] == "COMMITTED"
    loaded = _loaded(combat, mid)
    ally = loaded.engine.state.actors[ALLY]
    assert len(list(cai._active_layers(loaded.engine, ally))) == 2
    assert cai.layer_ac(loaded.engine, ally) == 1
    damage = [e.payload["reduced_to"] for e in loaded.engine.events
              if e.event_type == "DAMAGE_COMMITTED" and e.source_definition_id == "test:multiple-administrators"]
    assert damage == [0, 10]
    assert loaded.mechanical.replay()["status"] == "PASS"
