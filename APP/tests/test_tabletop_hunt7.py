"""Hunt 7 prompt identities through table preview, commit and disk reload."""
import pytest

from combat.gate4_adapters import ManualControllerAdapter
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT
from tests.test_hunt5_player_choices import fixture, PLAYER, FOE
from tests.test_lock2_persistence import act
from tests.test_tabletop_hunt6 import table_fight, on_hold, LEFT, ALLY, RIGHT, HOLD
from tests.test_tabletop_hunt6_fixup import hit_script
from tests.test_carry import KIT


def identified(prompt, ability, actor, action, affected):
    assert ability in prompt["reaction"]
    # "by" is the creature the choice is about (the page shows "<ability> on <by>"); the triggering creature is trigger_actor.
    assert prompt["trigger_actor"] == actor
    assert prompt["by"] == affected
    assert action in prompt["action"]
    assert prompt["affected"] == affected
    for name in (actor, action, affected):
        assert name in prompt["moment"]


@pytest.mark.parametrize("auto_turn", [False, True])
def test_footwork_attack_names_trigger_actor_and_defender(tmp_path, auto_turn):
    combat, table, mid, cid, send = fixture(tmp_path, "TAL_FENCING_FOOTWORK")
    engine = combat._load_session(mid).engine
    candidate = next(c for c in engine.legal_candidates() if c.candidate_id == cid)
    action = engine.action_catalog[candidate.source_definition_id].display_name
    if auto_turn:
        combat.set_controller_mode(mid, actor_id=FOE, controller_mode="LOCAL_AUTO")
    result = table.auto_step(mid, 0) if auto_turn else send(cid)
    assert result["status"] == "REACTION_REQUIRED"
    identified(result["reaction"], "Footwork", engine.state.actors[FOE].display_name,
               action, engine.state.actors[PLAYER].display_name)


def test_footwork_dex_save_names_effect_on_ai_turn(monkeypatch, tmp_path):
    """riders/c13 (14cd285f, approved C13r3.review.md) makes Crack target
    an owned Obsidian patch, not a creature. Prepare that persisted terrain;
    retain the original AI-turn Dexterity-save prompt identity checks.
    """
    from combat.factory_compiler import compile_character
    from tests.h1_support import sheet
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    player = compile_character(sheet(["TAL_FENCING_FOOTWORK"], cl=15, kit={"starting_kit": KIT}),
                               actor_id=PLAYER, reaction_plan={"ask": True})
    foe = compile_character(sheet(["TAL_MAGMA_MAGMA_GLOB", "TAL_MAGMA_SHAPE_THE_CRUST"], cl=15), actor_id=FOE)
    mid = combat._finish_factory_match([player, foe], [PLAYER, FOE],
        {PLAYER: "team:factory", FOE: "team:opponents"},
        {PLAYER: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [PLAYER], [FOE],
        control_modes={PLAYER: "MANUAL", FOE: "MANUAL"}, match_seed="H7-DEX",
        display_name="Dexterity prompt", maximum_rounds=10)["match_id"]
    while table.state(mid)["menu"]["actor_id"] != FOE:
        assert act(table, mid, "end")["status"] == "COMMITTED"
    from combat.ext import placed
    def prepare_patch(engine):
        source = next(s for s in engine.action_catalog
                      if engine.action_catalog[s].display_name == "Magma Glob: Obsidian Terrain Patch"
                      and engine.action_catalog[s].owner_id == FOE)
        placed.place(engine, engine.state.actors[FOE], source=source,
                     tag="magma_patch", placed={"kind": "obsidian"},
                     cells=engine.state.actors[PLAYER].position, name="Obsidian Terrain",
                     duration_rounds=10, terrain=["obsidian terrain"], difficult="hostile")
    on_hold(monkeypatch, prepare_patch)
    assert act(table, mid, "system:combat.hold_position")["status"] == "COMMITTED"
    engine = combat._load_session(mid).engine
    assert len(placed.of(engine, "magma_patch", owner_id=FOE)) == 1
    menu = table.state(mid)["menu"]
    group = next(g for g in menu["actions"] if "SHAPE_THE_CRUST#opt1" in g["source_definition_id"])
    assert any(o.get("destination") == {"x": 3, "y": 6} for o in group["options"])
    real = combat.controller
    class Controller:
        def choose_primary_action(self, context):
            candidate = next(c for c in context.legal_candidates
                             if c.source_definition_id == group["source_definition_id"]
                             and c.destination is not None
                             and (c.destination.x, c.destination.y) == (3, 6))
            return ManualControllerAdapter(lambda _: (candidate.candidate_id, ())).choose_primary_action(context)
        def __getattr__(self, name):
            return getattr(real, name)
    combat.controller = Controller()
    combat.set_controller_mode(mid, actor_id=FOE, controller_mode="LOCAL_AUTO")
    result = table.auto_step(mid, 0)
    assert result["status"] == "REACTION_REQUIRED"
    engine = combat._load_session(mid).engine
    identified(result["reaction"], "Footwork", engine.state.actors[FOE].display_name,
               "Crack Obsidian Patch", engine.state.actors[PLAYER].display_name)


def test_exploit_names_opportunity_attack_during_ai_move(monkeypatch, tmp_path):
    combat, table, mid = table_fight(tmp_path, ["TAL_FENCING_FACE_STRIKE"],
                                   kit={"starting_kit": KIT}, ask=True, ally_talents=[])
    while table.state(mid)["menu"]["actor_id"] != RIGHT:
        act(table, mid, "end")
    cid = next(m["candidate_id"] for m in table.state(mid)["menu"]["moves"]
               if m["destination"] == {"x": 6, "y": 4})
    real = combat.controller
    class Controller:
        def choose_primary_action(self, context):
            return ManualControllerAdapter(lambda _: (cid, ())).choose_primary_action(context)
        def __getattr__(self, name):
            return getattr(real, name)
    combat.controller = Controller()
    combat.set_controller_mode(mid, actor_id=RIGHT, controller_mode="LOCAL_AUTO")
    hit_script(monkeypatch)
    answers = []
    found = False
    for _ in range(8):
        result = table.auto_step(mid, 0, answers)
        if result["status"] == "COMMITTED":
            break
        prompt = result["reaction"]
        answer = {**prompt["context"], "selection": "USE"}
        if prompt.get("choice"):
            identified(prompt, "Exploit", "Left", "Opportunity Attack", "Right")
            found = True
            answer["option_ids"] = [prompt["choice"]["options"][0]["id"]]
        answers.append(answer)
    assert found and result["status"] == "COMMITTED"
    assert CombatService(ROOT, tmp_path)._load_session(mid).mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("selection", ["USE", "DECLINE"])
@pytest.mark.parametrize("auto_turn", [False, True])
def test_soul_consent_names_caster_and_ability_after_commit_reload(monkeypatch, tmp_path, selection, auto_turn):
    from combat.ext import life_state
    from combat.tabletop import ButtonStore
    from tests.test_tabletop_hunt6 import PROJECTS
    source = "tianxia.talent.life.one_breath_resuscitation"
    ButtonStore(tmp_path / "tabletop_buttons").save_reactions(PROJECTS["ally"], {"mode": "ask"}, set())
    combat, table, mid = table_fight(tmp_path, [source], ally_talents=["TAL_BERSERKER_DEATHLESS"])
    def kill(engine):
        target = engine.state.actors[ALLY]
        engine._commit_damage(target, target.current_hp, "FORCE", "test:lethal", RIGHT, engine._active_intent, reaction_depth=0)
        for _ in range(3):
            engine._commit_damage(target, 1, "FORCE", "test:lethal", RIGHT, engine._active_intent, reaction_depth=0)
    on_hold(monkeypatch, kill)
    assert act(table, mid, HOLD)["status"] == "COMMITTED"
    monkeypatch.undo()
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    assert life_state.is_dead(combat._load_session(mid).engine.state.actors[ALLY])
    menu = table.state(mid)["menu"]
    cid = next(o["candidate_id"] for g in menu["actions"] if source in g["source_definition_id"]
               for o in g["options"] if ALLY in o.get("target_ids", []))
    if auto_turn:
        real = combat.controller
        class Controller:
            def choose_primary_action(self, context):
                return ManualControllerAdapter(lambda _: (cid, ())).choose_primary_action(context)
            def __getattr__(self, name):
                return getattr(real, name)
        combat.controller = Controller()
        combat.set_controller_mode(mid, actor_id=LEFT, controller_mode="LOCAL_AUTO")
    def send(answers=()):
        return table.auto_step(mid, 0, list(answers)) if auto_turn else table.act(
            mid, cid, menu["decision_id"], menu["state_version"], 0, list(answers))
    result = send()
    assert result["status"] == "REACTION_REQUIRED"
    prompt = result["reaction"]
    identified(prompt, "One-Breath Resuscitation", "Left", "One-Breath Resuscitation", "Ally")
    assert send()["reaction"] == prompt
    answer = {**prompt["context"], "selection": selection,
              "option_ids": ["return"] if selection == "USE" else []}
    assert send([answer])["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    target = loaded.engine.state.actors[ALLY]
    assert life_state.is_dead(target) == (selection == "DECLINE")
    assert target.current_hp == (1 if selection == "USE" else 0)
    assert loaded.mechanical.replay()["status"] == "PASS"
