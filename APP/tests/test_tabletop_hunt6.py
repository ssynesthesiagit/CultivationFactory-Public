"""Hunt 6 regressions through accepted table actions and disk reloads."""
import json
import zipfile

import pytest

from combat import ext
from combat.ext import life_state
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService
from tests.h1_support import sheet, ROOT
from tests.test_lock2_persistence import act

PROJECTS = {"left": "11111111", "ally": "22222222", "right": "33333333"}
LEFT, ALLY, RIGHT = [FACTORY_ACTOR_PREFIX + PROJECTS[name] for name in ("left", "ally", "right")]
HOLD = "system:combat.hold_position"


def table_fight(tmp_path, talents, *, cl=15, kit=None, ask=False, ally_talents=None, kits=None, control_modes=None, starts=None, primary=None, foe_types=(), ally_types=()):
    for name in ("left", "ally", "right"):
        owned = [] if name == "right" else ally_talents if name == "ally" and ally_talents is not None else talents
        document = sheet(owned, cl=cl, kit=(kits or {}).get(name, kit), **({'primary': primary} if primary is not None else {}))
        if name == "right" and foe_types:
            document["identity"]["creature_types"] = list(foe_types)
        if name == "ally" and ally_types:
            document["identity"]["creature_types"] = list(ally_types)
        document["identity"]["display_name"] = name.title()
        folder = tmp_path / "portable_characters" / PROJECTS[name]
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(document))
    if ask:
        from combat.tabletop import ButtonStore
        ButtonStore(tmp_path / "tabletop_buttons").save_reactions(PROJECTS["left"], {"mode": "ask"}, {"opportunity_attack"})
    combat = CombatService(ROOT, tmp_path)
    combat.tabletop_maps.save({"display_name": "Hunt6 yard", "width_squares": 12, "height_squares": 8,
                              "walls": [], "starts": starts or {"team1": [[3, 4], [3, 5]], "team2": [[4, 4]]}})
    mid = combat.create_factory_match(project_ids=[PROJECTS["left"], PROJECTS["ally"]], opponent_actor_ids=[RIGHT],
                                     control_modes=control_modes or {a: "MANUAL" for a in (LEFT, ALLY, RIGHT)},
                                     arena_id="battlefield:map.hunt6-yard", match_seed="HUNT6-TABLE")["match_id"]
    table = TabletopService(combat, tmp_path)
    while table.state(mid)["menu"]["actor_id"] != LEFT:
        assert act(table, mid, "end")["status"] == "COMMITTED"
    return combat, table, mid


def on_hold(monkeypatch, callback):
    from combat.gate4_engine import Gate4ControllerEngine
    original = Gate4ControllerEngine._append_event
    def run(engine, event_type, *args, **kwargs):
        result = original(engine, event_type, *args, **kwargs)
        if event_type == "HOLD_POSITION_COMMITTED":
            # Synthetic damage/save inside the accepted action, outside the
            # event hook's recursion guard, with normal transactional pauses.
            callback(engine)
        return result
    monkeypatch.setattr(Gate4ControllerEngine, "_append_event", run)


@pytest.mark.parametrize("minute_gate,window", [(False, 1), (True, 10)])
def test_lingering_soul_commits_and_reloads_through_table(monkeypatch, tmp_path, minute_gate, window):
    talents = ["tianxia.talent.life.one_breath_resuscitation", "TAL_BERSERKER_DEATHLESS"]
    if minute_gate:
        talents.append("tianxia.talent.life.minute_gate_resuscitation")
    combat, table, mid = table_fight(tmp_path, talents)
    def kill(engine):
        target = engine.state.actors[ALLY]
        engine._commit_damage(target, target.current_hp, "FORCE", "test:blow", RIGHT, None, reaction_depth=0)
        for _ in range(3):
            engine._commit_damage(target, 1, "FORCE", "test:blow", RIGHT, None, reaction_depth=0)
    on_hold(monkeypatch, kill)
    assert act(table, mid, HOLD)["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    soul = life_state.soul_of(loaded.engine.state.actors[ALLY])
    assert soul is not None and type(soul.data["window"]) is int and soul.data["window"] == window
    assert loaded.mechanical.replay()["status"] == "PASS"


def answer_action(table, mid, source, pick=None):
    state = table.state(mid)
    menu = state["menu"]
    cid = next(g["options"][0]["candidate_id"] for g in menu["actions"] if source in g["source_definition_id"])
    answers = []
    for _ in range(12):
        result = table.act(mid, cid, menu["decision_id"], menu["state_version"], state["last_sequence"], answers)
        if result["status"] == "COMMITTED":
            return result
        prompt = result["reaction"]
        answer = {**prompt["context"], "selection": "USE"}
        if prompt.get("choice"):
            answer["option_ids"] = [pick or prompt["choice"]["options"][0]["id"]]
        answers.append(answer)
    raise AssertionError("too many reaction prompts")


@pytest.mark.parametrize("cl,count", [(5, 1), (11, 2), (17, 3)])
def test_spear_infusion_waits_for_a_weapon_hit_and_scales(monkeypatch, tmp_path, cl, count):
    from combat import typed_executor
    from tests.h1_support import script
    from tests.test_auto_martial import SPEAR_KIT
    source = "TAL_SPEAR_SPEAR_LIGHT_INFUSION"
    combat, table, mid = table_fight(tmp_path, [source], cl=cl, kit=SPEAR_KIT)
    result = answer_action(table, mid, source)
    engine = CombatService(ROOT, tmp_path)._load_session(mid).engine
    assert engine.state.actors[LEFT].current_hp == 60
    assert not any(e.event_type == "DAMAGE_COMMITTED" and e.source_definition_id.endswith(source) for e in engine.events)
    assert any(m.target_field == "typed_on_hit" for m in engine.state.actors[LEFT].modifiers.values())
    def hit_twice(engine):
        actor, target = engine.state.actors[LEFT], engine.state.actors[RIGHT]
        bound = next(m.value.rsplit("|", 1)[-1] for m in actor.modifiers.values() if m.target_field == "typed_on_hit")
        action = next(a for a in engine.action_catalog.values() if a.owner_id == LEFT and a.source_definition_id == bound)
        typed = action.parameters["typed"]
        ctx = typed_executor.Context(engine, actor, action, engine._active_intent, typed, [target], target, {})
        # A different hit kind must neither receive nor consume the infusion.
        script(engine, [19, *([1] * 20)])
        typed_executor.block_attack(ctx, {"type": "attack", "attack_kind": "unarmed", "count": 1,
                                         "on_hit": [{"type": "damage", "dice": {"count": 1, "sides": 4},
                                                     "damage_types": ["bludgeoning"]}]})
        assert not any(e.event_type == "DAMAGE_COMMITTED" and e.source_definition_id.endswith(source)
                       for e in engine.events)
        # Each attack hits without crit; every damage die rolls 1.
        script(engine, [19, *([1] * 20)])
        typed_executor.block_attack(ctx, {"type": "attack", "attack_kind": "weapon", "count": 1,
                                         "on_hit": [{"type": "damage", "weapon_damage": True}]})
        script(engine, [19, *([1] * 20)])
        typed_executor.block_attack(ctx, {"type": "attack", "attack_kind": "weapon", "count": 1,
                                         "on_hit": [{"type": "damage", "weapon_damage": True}]})
    on_hold(monkeypatch, hit_twice)
    assert answer_action(table, mid, HOLD)["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    damage = [e for e in loaded.engine.events if e.event_type == "DAMAGE_COMMITTED" and e.source_definition_id.endswith(source)]
    assert len(damage) == 1 and damage[0].target_ids == (RIGHT,) and damage[0].payload["hp_damage"] == count
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("owns_infusion", [False, True])
def test_inactive_infusion_does_not_change_weapon_hits(monkeypatch, tmp_path, owns_infusion):
    from combat import typed_executor
    from tests.h1_support import script
    from tests.test_auto_martial import SPEAR_KIT

    source = "TAL_SPEAR_SPEAR_LIGHT_INFUSION"
    combat, table, mid = table_fight(tmp_path, [source] if owns_infusion else [], cl=11, kit=SPEAR_KIT)
    def hit(engine):
        actor, target = engine.state.actors[LEFT], engine.state.actors[RIGHT]
        action = next(a for a in engine.action_catalog.values()
                      if a.owner_id == LEFT and "Qiang" in a.display_name and a.parameters.get("typed", {}).get("weapon"))
        ctx = typed_executor.Context(engine, actor, action, engine._active_intent, action.parameters["typed"], [target], target, {})
        script(engine, [19, *([1] * 20)])
        typed_executor.block_attack(ctx, {"type": "attack", "attack_kind": "weapon", "count": 1,
                                         "on_hit": [{"type": "damage", "weapon_damage": True}]})
    on_hold(monkeypatch, hit)
    assert answer_action(table, mid, HOLD)["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert not any(m.target_field == "typed_on_hit" for m in loaded.engine.state.actors[LEFT].modifiers.values())
    assert not any(e.event_type == "DAMAGE_COMMITTED" and e.source_definition_id.endswith(source)
                   for e in loaded.engine.events)
    assert loaded.mechanical.replay()["status"] == "PASS"
