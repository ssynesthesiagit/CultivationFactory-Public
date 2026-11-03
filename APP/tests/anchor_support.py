"""Synthetic Anchor/Wind Lash table fixtures; no owner sheets or engine patches."""
import json
import zipfile

from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop import ButtonStore
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.test_lock2_persistence import act

ANCHOR = "TAL_CHAINS_ANCHOR_LINK_BASE"
PROJECTS = ("aaa11111", "aaa22222", "aaa33333")
ME, FRIEND, FOE = (FACTORY_ACTOR_PREFIX + p for p in PROJECTS)


def fight(tmp_path, *, ally=False, feet=5, ai=False, auto_owner=False, legacy_range=False):
    for project, name, talents in zip(PROJECTS, ("Protector", "Traveler", "Pusher"),
                                      ([ANCHOR], [], ["AIR_BASE_WIND_LASH"])):
        doc = sheet(talents, cl=5, dc=60 if project == PROJECTS[2] else 16)
        if project == PROJECTS[2]:
            doc["ability_scores_and_statistics"]["technique_attack_bonus"] = 60
        doc["identity"]["display_name"] = name
        folder = tmp_path / "portable_characters" / project
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(doc))
    ButtonStore(tmp_path / "tabletop_buttons").save_reactions(
        PROJECTS[0], {"mode": "auto" if auto_owner else "ask"}, {ANCHOR})
    service = CombatService(ROOT, tmp_path)
    service.tabletop_maps.save({"display_name": "Anchor regression yard", "width_squares": 20,
        "height_squares": 10, "walls": [],
        "starts": {"team1": [[3, 4], [3 + feet // 5, 4]],
                   "team2": [[6 + feet // 5 if ally else 6, 4]]}})
    modes = {ME: "MANUAL", FRIEND: "MANUAL", FOE: "LOCAL_AUTO" if ai else "MANUAL"}
    arena_id = "battlefield:map.anchor-regression-yard"
    if legacy_range:
        # Supply the old sealed row shape before genesis, never rewrite a
        # committed bundle or patch compilation/runtime functions. Use the
        # same persistence/service setup as a regular Factory match.
        from combat.factory_compiler import compile_character

        bundles = []
        for project in PROJECTS:
            bundle = compile_character(service._factory_owner_sheet(project),
                actor_id=FACTORY_ACTOR_PREFIX + project,
                reaction_plan=ButtonStore(tmp_path / "tabletop_buttons").get(project).get("reactions"))
            for row in bundle["typed_reactions"]:
                if row["feature_id"] == ANCHOR:
                    row["range_ft"] = None
            bundle = service._with_prefight(bundle, None)
            bundles.append(bundle)
        positions = {ME: {"x": 3, "y": 4}, FRIEND: {"x": 3 + feet // 5, "y": 4},
                     FOE: {"x": 6 + feet // 5 if ally else 6, "y": 4}}
        mid = service._finish_factory_match(bundles, [ME, FRIEND, FOE],
            {ME: "team:factory", FRIEND: "team:factory", FOE: "team:opponents"},
            positions, service.factory_arenas()[arena_id], [ME, FRIEND], [FOE],
            control_modes=modes, match_seed="ANCHOR-TABLE-2", display_name=None,
            maximum_rounds=8)["match_id"]
    else:
        mid = service.create_factory_match(project_ids=list(PROJECTS[:2]), opponent_actor_ids=[FOE],
            control_modes=modes, arena_id=arena_id, match_seed="ANCHOR-TABLE-2", maximum_rounds=8)["match_id"]
    table = TabletopService(service, tmp_path)
    # Advance through accepted table end-turn actions. Configure the owner
    # for AI control only once setup has reached the forcing actor's turn.
    for _ in range(8):
        if table.state(mid)["menu"]["actor_id"] == FOE:
            if auto_owner:
                service.set_controller_mode(mid, actor_id=ME, controller_mode="LOCAL_AUTO")
            return service, table, mid
        assert act(table, mid, "end")["status"] == "COMMITTED"
    raise AssertionError("no enemy turn")


def push(service, table, mid, target, *, ai=False, monkeypatch=None):
    state = table.state(mid)
    menu = state["menu"]
    engine = service._load_session(mid).engine
    candidate = next(c for c in engine.legal_candidates()
        if c.source_definition_id in engine.action_catalog
        and "Wind Lash: Push" in engine.action_catalog[c.source_definition_id].display_name
        and target in c.target_ids)
    cid = candidate.candidate_id
    if ai:
        original = service.controller.choose_primary_action

        def choose(context):
            # Select the same legal Wind Lash candidate in the real AI path;
            # policy scoring is outside these reaction regressions.
            choice = original(context)
            candidate = next(c for c in context.legal_candidates if c.candidate_id == cid)
            return choice.model_copy(update={
                "intent": choice.intent.model_copy(update={"candidate_id": cid, "target_ids": candidate.target_ids,
                                                            "option_ids": candidate.option_ids, "destination": candidate.destination}),
                "record": choice.record.model_copy(update={"selected_candidate_id": cid,
                                                            "selected_option_ids": candidate.option_ids})})
        monkeypatch.setattr(service.controller, "choose_primary_action", choose)
    answers, prompts = [], []
    before = service._load_session(mid).engine.state.model_dump(mode="json")
    for _ in range(10):
        result = table.auto_step(mid, state["last_sequence"], answers) if ai else table.act(
            mid, cid, menu["decision_id"], menu["state_version"], state["last_sequence"], answers)
        if result["status"] == "COMMITTED":
            loaded = CombatService(ROOT, service.userdata_root)._load_session(mid)
            assert loaded.mechanical.replay()["status"] == "PASS"
            return loaded.engine, prompts
        assert result["status"] == "REACTION_REQUIRED"
        assert service._load_session(mid).engine.state.model_dump(mode="json") == before
        prompt = result["reaction"]
        prompts.append(prompt)
        answers.append({**prompt["context"], "selection": "USE" if prompt["reaction"] == "Anchor the Link" else "DECLINE"})
    raise AssertionError("too many prompts")
