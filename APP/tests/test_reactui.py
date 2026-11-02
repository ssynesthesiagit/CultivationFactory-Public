"""REACTUI: full manual consent menus, real table pause/commit/reload."""
import pytest
import subprocess
from pathlib import Path

from combat.gate4_adapters import ManualControllerAdapter
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.test_lock2_persistence import act
from tests.test_tabletop_hunt6 import table_fight, on_hold, LEFT, RIGHT, HOLD
from tests.h1_support import ROOT
from tests.r10_fixup_support import fixed_dice

CORRUPT = "TAL_DAEMONIC_CULTIVATION_CORRUPT_THE_RIGHTEOUS_LAW"
TAX = "TAL_DEATH_GRAVE_TAX"


def test_node_picker_and_reaction_menu_regressions():
    app = Path(__file__).resolve().parents[1]
    subprocess.run(["node", "--test", str(app / "tests/tabletop_target_selection.test.mjs"),
                    str(app / "static/tabletop/tabletop_map_pick.test.mjs")], check=True, timeout=60)


@pytest.mark.parametrize("automatic_turn", [False, True])
@pytest.mark.parametrize("pick", [None, "Reduce Healing", "Mark the Target", "Grave Tax"])
def test_all_eligible_reactions_and_modes_wait_for_the_player(monkeypatch, tmp_path, automatic_turn, pick):
    combat, table, mid = table_fight(tmp_path, [CORRUPT, TAX], cl=20, ask=True, ally_talents=[])
    while table.state(mid)["menu"]["actor_id"] != RIGHT:
        assert act(table, mid, "end")["status"] == "COMMITTED"
    fixed_dice(monkeypatch, [1] * 120)

    def heal(engine):
        target = engine.state.actors[RIGHT]
        target.current_hp = 40
        engine._heal(target, 5, HOLD, RIGHT, notify_healed=True)

    on_hold(monkeypatch, heal)
    if automatic_turn:
        combat.set_controller_mode(mid, actor_id=RIGHT, controller_mode="LOCAL_AUTO")
        base = combat.controller

        class HoldController:
            def choose_primary_action(self, context):
                cid = next(c.candidate_id for c in context.legal_candidates if c.source_definition_id == HOLD)
                return ManualControllerAdapter(lambda _: (cid, ())).choose_primary_action(context)

            def __getattr__(self, name):
                return getattr(base, name)

        combat.controller = HoldController()
        send = lambda answers=(): table.auto_step(mid, 0, list(answers))
    else:
        state = table.state(mid)
        menu = state["menu"]
        cid = next(o["candidate_id"] for g in menu["actions"] if g["source_definition_id"] == HOLD for o in g["options"])
        send = lambda answers=(): table.act(mid, cid, menu["decision_id"], menu["state_version"], 0, list(answers))

    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    result = send()
    assert result["status"] == "REACTION_REQUIRED"
    alternatives = result["reaction"]["alternatives"]
    names = [p["reaction"] for p in alternatives]
    # Every compiled mode, plus the independent eligible reaction. The preset
    # Mark cannot select itself on either a manual or an automatic attacker's turn.
    assert set(names) == {"Corrupt the Righteous Law — " + mode for mode in (
        "Reduce Healing", "Reduce Temporary HP", "Deny Reactions", "Mark the Target")} | {"Grave Tax"}
    assert len(alternatives) == 5
    assert all(p["reactor"] == "Left" and p["affected"] == "Right" for p in alternatives)
    assert all("Reaction" in p["cost"] for p in alternatives)
    mark = next(p for p in alternatives if p["reaction"].endswith(" — Mark the Target"))
    temp = next(p for p in alternatives if p["reaction"].endswith(" — Reduce Temporary HP"))
    assert "Demon Mark until the start of your next turn" in mark["summary"]
    assert "On a failed save:" in mark["summary"]
    assert "reduce healing" not in mark["summary"]
    assert "saved option" not in mark["table_note"]
    assert "Temporary HP gained by 2d8 + Proficiency Bonus" in temp["summary"]
    assert "GM" in temp["table_note"] and "not apply" in temp["table_note"]
    assert "cannot suppress Secret Inheritances" in temp["limits"]
    assert "saved option" not in temp["table_note"]
    assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
    assert send()["reaction"] == result["reaction"]

    reopened = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    assert reopened.state(mid)["pending_action"]["reaction"] == result["reaction"]
    answers = []
    selected = None
    for p in alternatives:
        use = pick is not None and (p["reaction"] == pick or p["reaction"].endswith(" — " + pick))
        answers.append({**p["context"], "selection": "USE" if use else "DECLINE"})
        if use:
            selected = p
            break
    assert pick is None or selected is not None
    assert send(answers)["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    actor = loaded.engine.state.actors[LEFT]
    resolved = [e for e in loaded.engine.events if e.event_type == "REACTION_RESOLVED" and e.actor_id == LEFT]
    assert len(resolved) == (0 if pick is None else 1)
    assert actor.reaction_available == (pick is None)
    if pick == "Mark the Target":
        assert any("demon" in c.condition_id.lower() for c in loaded.engine.state.actors[RIGHT].conditions.values())
    elif pick == "Reduce Healing":
        assert not any("demon" in c.condition_id.lower() for c in loaded.engine.state.actors[RIGHT].conditions.values())
    assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"


def test_manual_modes_are_transient_and_auto_keeps_its_preset():
    from combat.factory_compiler import compile_character
    from combat.ext.reaction_menus import manual_modes
    from tests.h1_support import sheet
    from types import SimpleNamespace

    bundle = compile_character(sheet([CORRUPT], cl=20), actor_id=LEFT,
                               reaction_plan={"ask": True, "options": {CORRUPT: 3}})
    rows = [r for r in bundle["typed_reactions"] if r["feature_id"] == CORRUPT]
    assert rows[0]["option"] == 3
    assert len(rows[0]["reaction_modes"]) == 4
    assert manual_modes(SimpleNamespace(typed_ask_reactors=()), LEFT, "generic", rows) is None
    expanded = manual_modes(SimpleNamespace(typed_ask_reactors={LEFT}), LEFT, "generic", rows)
    assert {r["option"] for r in expanded} == {0, 1, 2, 3}
    assert all("consent_source_id" not in r for r in rows)
    expanded[0]["effects"][0]["transient_test"] = True
    assert all("transient_test" not in e for r in rows for mode in r["reaction_modes"] for e in mode["effects"])


def test_menu_discovery_does_not_drop_legacy_or_extension_source_forms():
    from types import SimpleNamespace
    from combat.reaction_menu import ReactionMenuProbe

    contexts = [SimpleNamespace(checkpoint="SAVE_RESULT_BEFORE_DECLARED", reactor_id=LEFT,
        reaction_source_id=source, extension_choice=None) for source in (
            "reaction:typed.guard", "action:legacy.save_witness", "choice:extension.guard")]
    discovery = ReactionMenuProbe(contexts[0])
    for context in contexts:
        assert discovery.answer(context).selection == "DECLINE"
    assert discovery.contexts == contexts


def test_pass_first_hit_reaction_still_offers_damage_guard(monkeypatch, tmp_path):
    """Owner addendum: one melee hit, decline its first defense, then use its next."""
    guard = "tianxia.path.body_refining.feature.stamina_guard"
    forearm = "TAL_IRON_FIST_IRON_FOREARM_GUARD"
    from tests.test_carry import KIT
    combat, table, mid = table_fight(tmp_path, [forearm, guard], ask=True,
                                    ally_talents=[], primary="Stamina", kit={"starting_kit": KIT})
    while table.state(mid)["menu"]["actor_id"] != RIGHT:
        assert act(table, mid, "end")["status"] == "COMMITTED"
    fixed_dice(monkeypatch, [10] * 120)

    def hit(engine):
        from combat import typed_executor
        action = engine.action_catalog[attack_source]
        target = engine.state.actors[LEFT]
        ctx = typed_executor.Context(engine, engine.state.actors[RIGHT], action, engine._active_intent,
                                     {**action.parameters["typed"], "numbers": {"attack_bonus": 60}}, [target], target, {})
        typed_executor.block_attack(ctx, {"type": "attack", "attack_kind": "weapon", "count": 1,
            "on_hit": [{"type": "damage", "flat": 20, "damage_types": ["bludgeoning"]}]})

    on_hold(monkeypatch, hit)
    menu = table.state(mid)["menu"]
    attack_source = next(g["source_definition_id"] for g in menu["actions"] if ".weapon." in g["source_definition_id"])
    cid = next(o["candidate_id"] for g in menu["actions"] if g["source_definition_id"] == HOLD for o in g["options"])
    send = lambda answers=(): table.act(mid, cid, menu["decision_id"], menu["state_version"], 0, list(answers))
    first = send()
    assert first["status"] == "REACTION_REQUIRED"
    assert first["reaction"]["reaction"] == "Iron Forearm Guard"
    declined = {**first["reaction"]["context"], "selection": "DECLINE"}
    second = send([declined])
    assert second["status"] == "REACTION_REQUIRED"
    assert second["reaction"]["reaction"] == "Stamina Guard"
    reopened = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    assert reopened.state(mid)["pending_action"]["reaction"] == second["reaction"]
    # Continue using the independently reconstructed service, with the same test attack hook.
    use = {**second["reaction"]["context"], "selection": "USE", "option_ids": ["1"]}
    assert reopened.act(mid, cid, menu["decision_id"], menu["state_version"], 0, [declined, use])["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    resolved = [e for e in loaded.engine.events if e.event_type == "REACTION_RESOLVED" and e.actor_id == LEFT]
    assert [e.source_definition_id for e in resolved] == [guard]
    damage = [e for e in loaded.engine.events if e.event_type == "DAMAGE_COMMITTED" and LEFT in e.target_ids]
    assert len(damage) == 1
    assert damage[0].payload["hp_damage"] < damage[0].payload["rolled_or_pending_damage"]
    assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"
