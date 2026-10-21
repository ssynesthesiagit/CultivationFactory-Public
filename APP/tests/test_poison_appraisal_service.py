"""Appraise reach through acquired Poison base rows and the native table."""
import pytest

from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
import json
import zipfile
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX

OWNER, FOE, SECOND = [FACTORY_ACTOR_PREFIX + "r1i-" + k for k in ("owner", "foe", "second")]

def fixture(tmp_path, talents, *, positions=None, seed="APPRAISE", owner_dc=50, wide=True):
    """Synthetic portable sheets and an empty map; no private replay fixtures."""
    ids = [OWNER, FOE, SECOND]
    docs = [sheet(talents, cl=17, dc=owner_dc), sheet([], cl=17), sheet([], cl=17)]
    for aid, doc in zip(ids, docs):
        doc["identity"]["display_name"] = aid.rsplit("-", 1)[-1].title()
        folder = tmp_path / "portable_characters" / aid.removeprefix(FACTORY_ACTOR_PREFIX)
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(doc))
    bundles = [compile_character(doc, actor_id=aid, reaction_plan={"ask": True})
               for aid, doc in zip(ids, docs)]
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    saved = combat.tabletop_maps.save({"display_name": "Appraise test",
        "width_squares": 40, "height_squares": 20, "walls": [], "terrain": [],
        "starts": {"team1": [[3, 6]], "team2": [[4, 6], [15, 12]]}})
    arena = combat.factory_arenas()["battlefield:map." + saved["map_id"]]
    mid = combat._finish_factory_match(bundles, ids,
        {OWNER: "team:a", FOE: "team:b", SECOND: "team:b"},
        positions or {OWNER: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6},
                      SECOND: {"x": 15, "y": 12}},
        arena, [OWNER], ids[1:], control_modes={aid: "MANUAL" for aid in ids},
        match_seed=seed, display_name="Appraise test", maximum_rounds=10)["match_id"]

    def commit(cid):
        answers = []
        for _ in range(16):
            menu = table.state(mid)["menu"]
            result = table.act(mid, cid, menu["decision_id"], menu["state_version"], 0, answers)
            if result["status"] == "COMMITTED":
                return result
            assert result["status"] == "REACTION_REQUIRED", result
            prompt = result["reaction"]
            answer = {**prompt["context"], "selection": "DECLINE"}
            if prompt.get("choice"):
                answer.update(selection="USE",
                    option_ids=(prompt["choice"].get("preferred")
                                or [prompt["choice"]["options"][0]["id"]])[:1])
            answers.append(answer)
        raise AssertionError("Unresolved prompt")

    while table.state(mid)["menu"]["actor_id"] != OWNER:
        commit(table.state(mid)["menu"]["end_turn"])
    return combat, table, mid, None, commit


def candidate(table, mid, label, target):
    return next(o["candidate_id"] for g in table.state(mid)["menu"]["actions"]
                if g["label"] == label for o in g["options"]
                if target in o.get("target_ids", []))


APPRAISE = "POISON_BASE_APPRAISE_THE_VENOM"


def appraisal_options(table, mid):
    return [o for g in table.state(mid)["menu"]["actions"]
            if g["label"] == "Appraise the Venom" for o in g["options"]]


@pytest.mark.parametrize("feet,offered", [(5, True), (30, True), (35, False)])
def test_acquired_base_reach_and_cold_table_commit(tmp_path, feet, offered):
    # Learning a Poison talent grants the sphere's base rows through the real
    # compiler. No action definitions, conditions or fact receipts are injected.
    combat, table, mid, _, commit = fixture(tmp_path,
        ["tianxia.talent.poison.antidote_art"], wide=True,
        positions={OWNER: {"x": 3, "y": 6}, FOE: {"x": 3 + feet // 5, "y": 6},
                   SECOND: {"x": 15, "y": 12}}, seed=f"APPRAISE-{feet}")
    options = appraisal_options(table, mid)
    assert any(FOE in o.get("target_ids", []) for o in options) is offered
    session = combat._load_session(mid)
    action = next(a for a in session.engine.action_catalog.values()
                  if a.owner_id == OWNER and a.display_name == "Appraise the Venom")
    assert action.range_ft == 30
    if not offered:
        return
    before = dict(session.engine.state.actors[OWNER].resources)
    commit(candidate(table, mid, "Appraise the Venom", FOE))
    cold = CombatService(combat.source_root, tmp_path)
    fresh = cold._load_session(mid)
    assert fresh.engine.state.actors[OWNER].resources == before
    assert next(a for a in fresh.engine.action_catalog.values()
                if a.owner_id == OWNER and a.display_name == "Appraise the Venom").range_ft == 30
    # Use a fresh table as well as a cold engine load, without synthesizing state.
    assert TabletopService(cold, tmp_path).state(mid)["match_id"] == mid
    assert fresh.mechanical.replay()["status"] == "PASS"


def test_no_poison_sphere_does_not_gain_appraisal(tmp_path):
    _, table, mid, _, _ = fixture(tmp_path, [], wide=True, seed="APPRAISE-NONOWNER")
    assert not appraisal_options(table, mid)


@pytest.mark.parametrize("feet,offered", [(5, True), (10, False), (30, False)])
def test_native_blindfold_preserves_touch_but_not_longer_reach(tmp_path, feet, offered):
    combat, table, mid, _, commit = fixture(tmp_path,
        ["tianxia.talent.poison.antidote_art", "TAL_DARK_BLINDFOLD"],
        owner_dc=100, wide=True,
        positions={OWNER: {"x": 3, "y": 6}, FOE: {"x": 3 + feet // 5, "y": 6},
                   SECOND: {"x": 15, "y": 12}}, seed=f"APPRAISE-BLINDFOLD-{feet}")
    commit(candidate(table, mid, "Meld: Blindfold", OWNER))
    commit(table.state(mid)["menu"]["end_turn"])
    while table.state(mid)["menu"]["actor_id"] != OWNER:
        commit(table.state(mid)["menu"]["end_turn"])
    cold = CombatService(combat.source_root, tmp_path)
    actor = cold._load_session(mid).engine.state.actors[OWNER]
    assert any(c.condition_id == "condition:typed.blinded" for c in actor.conditions.values())
    table = TabletopService(cold, tmp_path)
    assert any(FOE in o.get("target_ids", []) for o in appraisal_options(table, mid)) is offered

    if offered:
        # Prospective AI targeting must not turn touch reach into detection of
        # an unseen enemy, even while the human's explicit touch stays legal.
        from combat.candidate_knowledge import query
        from combat.target_knowledge import knowledge
        session = cold._load_session(mid)
        engine = session.engine
        owner, foe = (engine.state.actors[aid] for aid in (OWNER, FOE))
        action = next(a for a in engine.action_catalog.values()
                      if a.owner_id == OWNER and a.display_name == "Appraise the Venom")
        with query(engine):
            assert knowledge(engine, owner, foe, action) is None
        menu = table.state(mid)["menu"]
        result = table.act(mid, candidate(table, mid, "Appraise the Venom", FOE),
                           menu["decision_id"], menu["state_version"], 0, [])
        assert result["status"] == "COMMITTED"
        assert cold._load_session(mid).mechanical.replay()["status"] == "PASS"


def test_native_tremorsense_allows_appraisal_without_sight(tmp_path):
    combat, table, mid, _, commit = fixture(tmp_path,
        ["tianxia.talent.poison.antidote_art", "TAL_DARK_BLINDFOLD",
         "tianxia.subpath.qi.mountain_core_cultivator.feature.stone_sense"],
        owner_dc=100, positions={OWNER: {"x": 3, "y": 6},
            FOE: {"x": 9, "y": 6}, SECOND: {"x": 15, "y": 12}},
        seed="APPRAISE-TREMORSENSE")
    commit(candidate(table, mid, "Meld: Blindfold", OWNER))
    commit(table.state(mid)["menu"]["end_turn"])
    while table.state(mid)["menu"]["actor_id"] != OWNER:
        commit(table.state(mid)["menu"]["end_turn"])
    cold = CombatService(combat.source_root, tmp_path)
    session = cold._load_session(mid)
    from combat.target_knowledge import can_see, located
    actor, target = (session.engine.state.actors[aid] for aid in (OWNER, FOE))
    assert not can_see(session.engine, actor, target)
    assert located(session.engine, actor, target)
    fresh_table = TabletopService(cold, tmp_path)
    assert any(FOE in o.get("target_ids", []) for o in appraisal_options(fresh_table, mid))
    menu = fresh_table.state(mid)["menu"]
    result = fresh_table.act(mid, candidate(fresh_table, mid, "Appraise the Venom", FOE),
                             menu["decision_id"], menu["state_version"], 0, [])
    assert result["status"] == "COMMITTED"
    assert cold._load_session(mid).mechanical.replay()["status"] == "PASS"
