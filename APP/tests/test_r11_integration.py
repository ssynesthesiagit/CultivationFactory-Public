"""Round 17 integration: lane concentration copies persist and end independently."""

import json

import pytest

from combat import concentration, zones
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent
from combat.gate4_persistence import Gate4Persistence
from combat.factory_compiler import compile_character
from tests.test_riders_lane11 import ROOT, ME, CONCENTRATION_IDS, _sheet

AUTHORITY = json.loads((ROOT / "authority/Tianxia_Typed_Mechanics_Authority_R1.json").read_text())["mechanics"]


@pytest.mark.parametrize("auto_turn", [False, True])
@pytest.mark.parametrize("other_sight,expected", [(None, 0), ("deep", 60), ("meld", 60)])
def test_tidal_sight_requires_environment_table_commit_reload(tmp_path, auto_turn, other_sight, expected):
    """A dry table cannot activate Deep-Sight Adaptation or boost other sight."""
    import zipfile

    from combat import senses
    from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
    from combat.tabletop_service import TabletopService
    from tests.test_riders_lane11 import DEEP, PREFIX

    tidal = PREFIX + "abyssal_depths_cultivator.feature.tidal_resilience"
    player, foe = [FACTORY_ACTOR_PREFIX + pid for pid in ("r11-sight", "r11-sight-foe")]
    document = _sheet(tidal)
    if other_sight == "deep":
        document["path_and_subpath"]["path_feature_record_ids"].append(DEEP)
    elif other_sight == "meld":
        document["spheres_and_talents"] = {"sphere_record_ids": ["tianxia.sphere.dark"],
                                          "learned_talent_record_ids": ["TAL_DARK_DARKVISION"]}
    enemy = _sheet(tidal)
    enemy["path_and_subpath"] = {"path_feature_record_ids": []}
    for aid, doc in ((player, document), (foe, enemy)):
        folder = tmp_path / "portable_characters" / aid.removeprefix(FACTORY_ACTOR_PREFIX)
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(doc))
    bundles = [compile_character(doc, actor_id=aid) for aid, doc in ((player, document), (foe, enemy))]
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    mid = combat._finish_factory_match(bundles, [player, foe],
        {player: "team:factory", foe: "team:opponents"},
        {player: {"x": 3, "y": 6}, foe: {"x": 9, "y": 5}},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [player], [foe],
        control_modes={player: "MANUAL", foe: "MANUAL"}, match_seed="R11-TIDAL-SIGHT",
        display_name="Dry battlefield sight", maximum_rounds=10)["match_id"]

    def check():
        session = combat._load_session(mid)
        actor = session.engine.state.actors[player]
        assert senses.of(session.engine, actor).get("darkvision", {}).get("range_ft", 0) == expected
        info = next(b for b in session.engine.typed_bundle_documents if b["actor_id"] == player)["senses"]
        assert not any(row["feature_id"] == tidal for row in info.get("rows", []))
        assert "fully submerged or in an Abyssal environment" in info["gm"][tidal]
        assert session.verify()["status"] == "PASS"

    check()
    menu = table.state(mid)["menu"]
    if auto_turn:
        combat.set_controller_mode(mid, actor_id=menu["actor_id"], controller_mode="LOCAL_AUTO")
        result = table.auto_step(mid, 0)
    else:
        result = table.act(mid, menu["end_turn"], menu["decision_id"], menu["state_version"], 0)
    assert result["status"] == "COMMITTED", result
    check()


@pytest.mark.parametrize("mid", CONCENTRATION_IDS)
def test_lane_concentration_recast_commit_reload_keeps_older_copy(tmp_path, mid):
    persistence = Gate4Persistence(ROOT, tmp_path)
    document = _sheet(mid)
    # Isolate copy lifetime from defeat, Qi exhaustion and concentration-save luck.
    document["ability_scores_and_statistics"].update(
        hit_points={"maximum": 10000}, primary_resource={"name": "Qi", "maximum": 1000})
    document["ability_scores_and_statistics"]["abilities"] = [
        {**row, "modifier": 1000} if row["ability"] == "CON" else dict(row)
        for row in document["ability_scores_and_statistics"]["abilities"]]
    foe_document = {**document, "path_and_subpath": {"path_feature_record_ids": []}}
    bundles = (compile_character(document, actor_id=ME), compile_character(foe_document, actor_id=AN))
    assert bundles[0]["concentration_rules"]["capacity"] == "unlimited"
    session = persistence.create_match(match_seed="R11-COPIES", typed_bundles=bundles,
        roster_setup={"primary_actor_ids": [ME, AN],
            "team_by_actor": {ME: "team:a", AN: "team:b"},
            "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": 8, "y": 6}}})

    def take(candidate):
        session.mechanical.execute_intent(ActionIntent(
            intent_id=f"r11-copy-{candidate.state_version}", decision_id=candidate.decision_id,
            candidate_id=candidate.candidate_id, state_version=candidate.state_version,
            actor_id=candidate.actor_id, target_ids=candidate.target_ids,
            destination=candidate.destination))

    def my_turn():
        while session.engine.state.current_actor_id != ME:
            take(next(c for c in session.engine.legal_candidates() if c.display_name == "End turn"))

    def cast(source=None):
        candidate = next(c for c in session.engine.legal_candidates()
            if c.source_definition_id in session.engine.action_catalog
            and (source is None or c.source_definition_id == source)
            and session.engine.action_catalog[c.source_definition_id].parameters.get("typed", {}).get("source") == mid)
        take(candidate)
        return candidate.source_definition_id

    my_turn()
    source = cast()
    older_zones = {z.zone_id for z in zones.typed_zones(session.engine) if z.source_definition_id == source}
    take(next(c for c in session.engine.legal_candidates() if c.display_name == "End turn"))
    my_turn()
    if AUTHORITY[mid].get("use_limit"):
        # A printed once-per-scene limit forbids a second activation. Verify the
        # persisted first cast, then exercise its concentration-copy contract
        # directly; this does not assert a second legal ability activation.
        assert AUTHORITY[mid]["use_limit"] == "text:once per scene"
        assert not any(c.source_definition_id == source for c in session.engine.legal_candidates())
        session = persistence.load_match(session.match_id)
        assert session.verify()["status"] == "PASS"
        session.engine._start_concentration(session.engine.state.actors[ME], source)
    else:
        assert cast(source) == source
        session = persistence.load_match(session.match_id)
        assert session.verify()["status"] == "PASS"
    actor = session.engine.state.actors[ME]
    assert concentration.sources(actor) == [source, source]
    assert older_zones <= {z.zone_id for z in zones.typed_zones(session.engine)}
    session.engine._end_concentration(actor, "FAILED_DAMAGE_CHECK")
    assert concentration.sources(actor) == [source]
    assert older_zones <= {z.zone_id for z in zones.typed_zones(session.engine)}


@pytest.mark.parametrize("auto_turn", [False, True])
@pytest.mark.parametrize("selection", ["USE", "DECLINE"])
def test_moon_turn_start_player_rewrite_table_commit_reload(tmp_path, auto_turn, selection):
    import json
    import zipfile

    from combat.gate4_adapters import ManualControllerAdapter
    from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
    from combat.tabletop_service import TabletopService
    from tests.h1_support import sheet
    from tests.test_riders_lane11 import MOON

    player, caster = [FACTORY_ACTOR_PREFIX + pid for pid in ("r11-player", "r11-caster")]
    documents = [sheet(["TAL_FATE_REWRITE_THE_DISASTER"], cl=15), _sheet(MOON, cl=15, dc=20)]
    documents[0]["identity"]["display_name"] = "Moon target"
    documents[1]["identity"]["display_name"] = "Moon caster"
    for aid, document in zip((player, caster), documents):
        folder = tmp_path / "portable_characters" / aid.removeprefix(FACTORY_ACTOR_PREFIX)
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(document))
    bundles = [compile_character(document, actor_id=aid,
                   reaction_plan={"ask": True} if aid == player else None)
               for aid, document in zip((player, caster), documents)]
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    arena = combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"]
    mid = combat._finish_factory_match(bundles, [player, caster],
        {player: "team:factory", caster: "team:opponents"},
        {player: {"x": 3, "y": 6}, caster: {"x": 4, "y": 6}}, arena,
        [player], [caster], control_modes={player: "MANUAL", caster: "MANUAL"},
        match_seed="R11-MOON-ASK", display_name="Moon turn-start choices", maximum_rounds=10)["match_id"]

    def act(cid, answers=()):
        menu = table.state(mid)["menu"]
        return table.act(mid, cid, menu["decision_id"], menu["state_version"], 0, list(answers))

    if table.state(mid)["menu"]["actor_id"] != caster:
        assert act(table.state(mid)["menu"]["end_turn"])["status"] == "COMMITTED"
    menu = table.state(mid)["menu"]
    group = next(g for g in menu["actions"] if "Moon’s Pull" in g["label"])
    cid = next(o["candidate_id"] for o in group["options"] if o.get("destination") == {"x": 3, "y": 6})
    assert act(cid)["status"] == "COMMITTED"
    if auto_turn:
        combat.set_controller_mode(mid, actor_id=caster, controller_mode="LOCAL_AUTO")
        original = combat.controller

        class EndTurnController:
            def choose_primary_action(self, context):
                end = next(c for c in context.legal_candidates if c.kind.value == "END_TURN")
                return ManualControllerAdapter(lambda _context: (end.candidate_id, ())).choose_primary_action(context)

            def __getattr__(self, name):
                return getattr(original, name)

        combat.controller = EndTurnController()
    before = combat._load_session(mid).engine.state.model_dump(mode="json")

    def send(answers=()):
        return table.auto_step(mid, 0, list(answers)) if auto_turn else act(table.state(mid)["menu"]["end_turn"], answers)

    result = send()
    assert result["status"] == "REACTION_REQUIRED", result
    prompt = result["reaction"]
    assert prompt["context"]["reactor_id"] == player
    assert prompt["context"]["reaction_source_id"] == "choice:needle.rewrite_the_disaster"
    assert prompt["choice"]["allow_decline"]
    assert send()["reaction"] == prompt
    assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
    answer = {**prompt["context"], "selection": selection,
              "option_ids": ["20"] if selection == "USE" else []}
    result = send([answer])
    if result["status"] == "REACTION_REQUIRED":
        # After declining the defender's rewrite, the manual caster still owns
        # the failed-save distance. Both answers belong to this END_TURN intent.
        pull = result["reaction"]
        assert pull["context"]["reactor_id"] == caster
        assert pull["context"]["reaction_source_id"] == "choice:abyssal.moon_pull"
        result = send([answer, {**pull["context"], "selection": "USE", "option_ids": ["15"]}])
    assert result["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    rewritten = [e for e in loaded.engine.events if e.event_type == "D20_REWRITTEN"]
    assert len(rewritten) == (selection == "USE")
    assert loaded.engine._active_intent is None
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("auto_turn", [False, True])
@pytest.mark.parametrize("distance", [None, 0, 5, 10, 15])
@pytest.mark.parametrize("copies", [1, 2])
def test_moon_caster_owns_optional_pull_on_foe_turn_commit_reload(tmp_path, auto_turn, distance, copies):
    import zipfile

    from combat.gate4_adapters import ManualControllerAdapter
    from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
    from combat.tabletop_service import TabletopService
    from tests.test_riders_lane11 import MOON

    player, foe = [FACTORY_ACTOR_PREFIX + pid for pid in ("r11-pull-caster", "r11-pull-target")]
    documents = [_sheet(MOON, dc=50), _sheet(MOON)]
    documents[1]["path_and_subpath"] = {"path_feature_record_ids": []}
    for aid, document in zip((player, foe), documents):
        document["identity"]["display_name"] = "Lunar caster" if aid == player else "Moving target"
        folder = tmp_path / "portable_characters" / aid.removeprefix(FACTORY_ACTOR_PREFIX)
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(document))
    bundles = [compile_character(doc, actor_id=aid,
                   reaction_plan={"ask": True} if aid == player else None)
               for aid, doc in zip((player, foe), documents)]
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    arena = combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"]
    mid = combat._finish_factory_match(bundles, [player, foe],
        {player: "team:factory", foe: "team:opponents"},
        {player: {"x": 3, "y": 6}, foe: {"x": 9, "y": 5}}, arena, [player], [foe],
        control_modes={player: "MANUAL", foe: "MANUAL"}, match_seed="R11-PULL-ASK",
        display_name="Optional lunar pull", maximum_rounds=10)["match_id"]

    def act(cid, answers=()):
        menu = table.state(mid)["menu"]
        return table.act(mid, cid, menu["decision_id"], menu["state_version"], 0, list(answers))

    if table.state(mid)["menu"]["actor_id"] != player:
        assert act(table.state(mid)["menu"]["end_turn"])["status"] == "COMMITTED"
    menu = table.state(mid)["menu"]
    group = next(g for g in menu["actions"] if "Moon’s Pull" in g["label"])
    cid = next(o["candidate_id"] for o in group["options"] if o.get("destination") == {"x": 4, "y": 5})
    assert act(cid)["status"] == "COMMITTED"
    assert act(table.state(mid)["menu"]["end_turn"])["status"] == "COMMITTED"
    if copies == 2:
        assert act(table.state(mid)["menu"]["end_turn"])["status"] == "COMMITTED"
        menu = table.state(mid)["menu"]
        group = next(g for g in menu["actions"] if "Moon’s Pull" in g["label"])
        cid = next(o["candidate_id"] for o in group["options"] if o.get("destination") == {"x": 4, "y": 5})
        assert act(cid)["status"] == "COMMITTED"
        assert act(table.state(mid)["menu"]["end_turn"])["status"] == "COMMITTED"
    session = combat._load_session(mid)
    candidate = next(c for c in session.engine.legal_candidates()
                     if c.kind.value == "MOVE" and c.destination.x == 8 and c.destination.y == 5)
    if auto_turn:
        combat.set_controller_mode(mid, actor_id=foe, controller_mode="LOCAL_AUTO")
        original = combat.controller

        class MoveController:
            def choose_primary_action(self, context):
                return ManualControllerAdapter(lambda _context: (candidate.candidate_id, ())).choose_primary_action(context)

            def __getattr__(self, name):
                return getattr(original, name)

        combat.controller = MoveController()
    before = combat._load_session(mid).engine.state.model_dump(mode="json")

    def send(answers=()):
        return table.auto_step(mid, 0, list(answers)) if auto_turn else act(candidate.candidate_id, answers)

    result = send()
    assert result["status"] == "REACTION_REQUIRED", [
        (e.event_type, e.payload) for e in combat._load_session(mid).engine.events
        if e.event_type in {"PASSIVE_TRIGGERED", "SAVE_ROLLED", "GM_LINE"}]
    prompt = result["reaction"]
    assert prompt["context"]["reactor_id"] == player
    assert prompt["context"]["reaction_source_id"] == "choice:abyssal.moon_pull"
    assert prompt["choice"]["allow_decline"]
    assert {o["id"] for o in prompt["choice"]["options"]} == {"0", "5", "10", "15"}
    assert prompt["reaction"] == "Moon’s Pull"
    assert "Moon’s Pull" in prompt["moment"] and "Moving target" in prompt["moment"]
    assert send()["reaction"] == prompt
    assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
    answer = {**prompt["context"], "selection": "DECLINE" if distance is None else "USE",
              "option_ids": [] if distance is None else [str(distance)]}
    result = send([answer])
    if copies == 2:
        assert result["status"] == "REACTION_REQUIRED"
        second = result["reaction"]
        assert second["context"]["reaction_source_id"] == "choice:abyssal.moon_pull"
        assert second["context"]["checkpoint"] != prompt["context"]["checkpoint"]
        result = send([answer, {**second["context"], "selection": "DECLINE", "option_ids": []}])
    assert result["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.actors[foe].position.x == 8 - (distance or 0) // 5
    assert sum(m.value for m in loaded.engine.state.actors[foe].modifiers.values()
               if m.target_field == "speed_ft") == -10  # overlapping copies never double the debuff
    assert loaded.engine.state.actors[player].movement_remaining_ft == before["actors"][player]["movement_remaining_ft"]
    assert loaded.mechanical.replay()["status"] == "PASS"
