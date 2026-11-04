"""L18 regressions through accepted table actions and a fresh disk load."""
from combat.factory_compiler import compile_character
from combat.condition_text import all_conditions
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.test_lock2_persistence import act
from tests.test_tabletop_hunt6 import LEFT, RIGHT, table_fight


def _commit(table, match_id, source, target=None):
    state = table.state(match_id)
    menu = state["menu"]
    groups = [g for g in menu["actions"] if source in g["source_definition_id"]]
    options = [o for group in groups for o in group["options"]
               if target is None or target in o["target_ids"]]
    assert options, f"no table action for {source} against {target}; actions={menu['actions']}"
    options.sort(key=lambda o: -(o.get("expected_damage") or 0))
    answers = []
    for _ in range(20):
        result = table.act(match_id, options[0]["candidate_id"], menu["decision_id"],
                           menu["state_version"], state["last_sequence"], answers)
        if result["status"] == "COMMITTED":
            return result
        prompt = result["reaction"]
        answer = {**prompt["context"], "selection": "USE"}
        if prompt.get("choice"):
            answer["option_ids"] = [x["id"] for x in prompt["choice"]["options"][:1]]
        answers.append(answer)
    raise AssertionError("too many reaction prompts")


def _end_turn(table, match_id):
    assert act(table, match_id, "end")["status"] == "COMMITTED"


def test_stunned_keeps_speed_and_movement_in_a_saved_table(tmp_path):
    condition = all_conditions()["stunned"]
    assert "can't speak" in condition["reading"]
    assert "Speed is unchanged" in condition["reading"]
    assert "Its Speed is 0" not in condition["mechanics"]
    combat, table, mid = table_fight(tmp_path, ["TAL_IRON_FIST_ONE_INCH_HEAVENQUAKE"])
    _commit(table, mid, "TAL_IRON_FIST_ONE_INCH_HEAVENQUAKE", RIGHT)
    for _ in range(12):
        if table.state(mid)["menu"]["actor_id"] == RIGHT:
            break
        _end_turn(table, mid)
    state = table.state(mid)
    assert state["menu"]["actor_id"] == RIGHT
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    target = loaded.engine.state.actors[RIGHT]
    assert any(c.condition_id == "condition:typed.stunned" for c in target.conditions.values())
    assert loaded.engine._effective_speed(target) == target.speed_ft
    assert state["menu"]["moves"], "Stunned must not remove legal movement"
    assert loaded.verify()["status"] == "PASS"
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_poisoned_grapple_escape_check_is_disadvantaged_after_reload(tmp_path):
    assert "Disadvantage on ability checks" in all_conditions()["poisoned"]["mechanics"]
    grappler = "actor:factory.grappler"
    foe = "actor:factory.foe"
    ids = [LEFT, grappler, RIGHT, foe]
    docs = [sheet(["tianxia.talent.poison.toxic_cloud"], cl=5), sheet([], cl=5),
            sheet([], cl=5), sheet([], cl=5)]
    bundles = [compile_character(doc, actor_id=actor) for doc, actor in zip(docs, ids)]
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    teams = {actor: "team:a" if i < 2 else "team:b" for i, actor in enumerate(ids)}
    positions = dict(zip(ids, [{"x": 3, "y": 6}, {"x": 3, "y": 5},
                               {"x": 4, "y": 6}, {"x": 4, "y": 5}]))
    mid = combat._finish_factory_match(
        bundles, ids, teams, positions, combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"],
        ids[:2], ids[2:], control_modes={actor: "MANUAL" for actor in ids},
        match_seed="H43-POISON-CHECK-3", display_name="Poisoned grapple escape", maximum_rounds=6,
    )["match_id"]
    escaped = False
    poison_attempted = False
    for _ in range(80):
        state = table.state(mid)
        if state["presentation"].get("terminal"):
            break
        actor = state["menu"]["actor_id"]
        loaded = combat._load_session(mid)
        target = loaded.engine.state.actors[RIGHT]
        conditions = {c.condition_id for c in target.conditions.values()}
        if actor == LEFT and not poison_attempted:
            poison_attempted = True
            _commit(table, mid, "tianxia.talent.poison.toxic_cloud")
        elif (actor == grappler and "condition:typed.grappled" not in conditions
              and loaded.engine.state.actors[grappler].action_available):
            _commit(table, mid, "unarmed.grapple", RIGHT)
        elif actor == RIGHT and {"condition:typed.grappled", "condition:typed.poisoned"} <= conditions:
            escape_actions = [g["source_definition_id"] for g in state["menu"]["actions"]
                              if "escape" in g["source_definition_id"]]
            if escape_actions:
                _commit(table, mid, escape_actions[0])
                escaped = True
                break
            _end_turn(table, mid)
        else:
            _end_turn(table, mid)
    assert escaped, "table never offered Escape Grapple while Poisoned"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    checks = [e for e in loaded.engine.events if e.event_type == "CHECK_ROLLED"
              and e.source_definition_id and "escape" in e.source_definition_id]
    assert len(checks) == 1
    assert checks[0].payload["actor"]["mode"] == "DISADVANTAGE"
    assert loaded.verify()["status"] == "PASS"
    assert loaded.mechanical.replay()["status"] == "PASS"
