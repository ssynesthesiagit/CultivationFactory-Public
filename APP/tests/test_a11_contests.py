"""Opposed checks at the table boundary, with both rolls and saved reloads."""
import os
from pathlib import Path

import pytest

from combat import ext, typed_executor as te
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.factory_compiler import compile_character
from combat.canonical import canonical_sha256
from tests.h1_support import ROOT, ME, FOE, duel, script, sheet
from tests.test_tabletop_hunt6 import table_fight, LEFT, RIGHT
from tests.test_hunt32_inert_replay import _capture

HUNGER = "HUNGER_BASE_TASTE_THE_QI"
DARK = "TAL_DARK_TENEBROUS_LEGERDEMAIN"


@pytest.fixture(scope="session")
def old_authority():
    """Opt-in negative control uses a developer-supplied authority copy."""
    # Extract APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json from 65cf60c9.
    path = os.environ.get("A11_OLD_AUTHORITY")
    return Path(path) if path else None


@pytest.fixture(autouse=True)
def use_old_authority_for_negative_control(monkeypatch, old_authority):
    if old_authority:
        from combat import factory_compiler
        monkeypatch.setattr(factory_compiler, "TYPED_AUTHORITY", old_authority)


def _act(table, mid, text, answers=(), destination=None):
    if destination is not None:
        from tests.r1i_service_support import place
        return place(table, mid, text, destination, answers)
    state = table.state(mid)
    menu = state["menu"]
    group = next((g for g in menu["actions"] if text in g["label"]), None)
    assert group is not None, f"Missing action {text!r}; menu: {menu['actions']!r}"
    option = next((o for o in group["options"] if RIGHT in o.get("target_ids", [])), group["options"][0])
    return table.act(mid, option["candidate_id"], menu["decision_id"], menu["state_version"],
                     state["last_sequence"], list(answers))


def _reload(tmp_path, mid):
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    assert session.verify()["status"] == "PASS"
    assert session.mechanical.replay()["status"] == "PASS"
    return session.engine


@pytest.mark.parametrize("save", ["Charisma", "Constitution"])
def test_taste_concealed_nature_rolls_both_sides_in_table_history_and_reload(tmp_path, save):
    service, table, mid = table_fight(tmp_path, [HUNGER])
    result = _act(table, mid, "Unwilling, concealed nature: oppose " + save)
    assert result["status"] == "COMMITTED"
    engine = _reload(tmp_path, mid)
    events = [e for e in engine.events if e.event_type == "CHECK_ROLLED" and e.payload.get("roll_kind") == "opposed_check"]
    assert len(events) == 1
    event = events[0]
    assert event.actor_id == LEFT and event.target_ids == (RIGHT,)
    mine, theirs = event.payload["actor"], event.payload["target"]
    assert mine["actor_id"] == LEFT and theirs["actor_id"] == RIGHT
    assert mine["natural_result"] in range(1, 21) and theirs["natural_result"] in range(1, 21)
    assert event.payload["margin"] == mine["total"] - theirs["total"]
    assert event.payload["success"] == (mine["total"] > theirs["total"])
    feed = table.events(mid, 0)["events"]
    line = next(row["summary"] for row in feed if row["event_sequence"] == event.sequence)
    assert "against" in line and save in line and "DC ?" not in line
    assert str(mine["total"]) in line and str(theirs["total"]) in line


def test_taste_open_nature_does_not_invent_a_concealment_roll(tmp_path):
    _, table, mid = table_fight(tmp_path, [HUNGER])
    assert _act(table, mid, "Read an openly shown nature")["status"] == "COMMITTED"
    engine = _reload(tmp_path, mid)
    assert not any(e.payload.get("roll_kind") == "opposed_check" for e in engine.events)


@pytest.mark.parametrize("defender,attacker,expected", [(12, 12, False), (1, 20, True), (20, 1, False)])
def test_check_contest_ties_preserve_situation_and_natural_twenty_is_only_a_total(defender, attacker, expected):
    engine = duel(HUNGER)
    actor, target = engine.state.actors[ME], engine.state.actors[FOE]
    actor.skills["Sleight of Hand"] = target.skills["Perception"] = 0
    action = next(a for a in engine.action_catalog.values() if a.owner_id == ME and a.parameters.get("typed"))
    ctx = te.Context(engine, actor, action, None, action.parameters["typed"], [target], target)
    script(engine, [defender, attacker])
    result = te.resolve_opposed_check(ctx, target,
        {"kind": "check", "ability": "DEX", "skill": "Sleight of Hand"},
        {"kind": "check", "ability": "WIS", "skill": "Perception"})
    assert result.success is expected and result.tied == (defender == attacker)
    assert result.margin == attacker - defender


def test_skill_totals_use_sheet_and_both_sides_receive_check_penalties(monkeypatch):
    engine = duel(HUNGER)
    actor, target = engine.state.actors[ME], engine.state.actors[FOE]
    engine.typed_bundle_documents = ({"actor_id": ME, "skills": {"Sleight of Hand": 9}},)
    actor.skills["Sleight of Hand"] = -20
    target.skills["Athletics"] = 4
    seen = []
    def penalty(ctx, subject):
        seen.append((ctx.actor.entity_id, subject.entity_id, ctx.target.entity_id))
        return -2
    ext.effects()
    monkeypatch.setitem(ext._HOOKS, "check_bonus", [penalty])
    action = next(a for a in engine.action_catalog.values() if a.owner_id == ME and a.parameters.get("typed"))
    ctx = te.Context(engine, actor, action, None, action.parameters["typed"], [target], target)
    script(engine, [10, 10])
    result = te.resolve_opposed_check(ctx, target,
        {"kind": "check", "ability": "DEX", "skill": "Sleight of Hand"},
        {"kind": "check", "ability": "STR", "skill": "Athletics"})
    assert result.actor.total == 17 and result.target.total == 12 and result.margin == 5
    assert seen == [(FOE, FOE, ME), (ME, ME, FOE)]


def test_saved_stock_ai_continuation_is_byte_identical_without_contest_extensions(monkeypatch):
    current = _capture()
    for name, callbacks in list(ext._HOOKS.items()):
        monkeypatch.setitem(ext._HOOKS, name, [f for f in callbacks if f.__module__ != "combat.ext.contests"])
    monkeypatch.delitem(ext._EFFECTS, "contest_against")
    assert _capture() == current


def _dark_table(tmp_path):
    from tests.test_riders_c4 import AXE

    bundles = []
    for aid in (LEFT, RIGHT):
        document = sheet([DARK] if aid == LEFT else [], kit=AXE)
        document["identity"]["display_name"] = "Left" if aid == LEFT else "Right"
        document["ability_scores_and_statistics"]["skills"] = [
            {"skill": "Sleight of Hand", "bonus": 100 if aid == LEFT else 0},
            {"skill": "Athletics", "bonus": 0}, {"skill": "Acrobatics", "bonus": 1}]
        b = compile_character(document, actor_id=aid, reaction_plan={"ask": True})
        b["actor_template"]["initiative_bonus"] = 100 if aid == LEFT else -100
        b.pop("bundle_sha256", None)
        b["bundle_sha256"] = canonical_sha256(b)
        bundles.append(b)
    service = CombatService(ROOT, tmp_path)
    session = service.persistence.create_match(match_seed="A11-DARK", typed_bundles=tuple(bundles),
        roster_setup={"primary_actor_ids": [LEFT, RIGHT], "team_by_actor": {LEFT: "team:a", RIGHT: "team:b"},
                      "starting_positions": {LEFT: {"x": 3, "y": 6}, RIGHT: {"x": 4, "y": 6}}})
    table = TabletopService(service, tmp_path)
    assert _act(table, session.match_id, "Shape Darkness: Tenebrous Legerdemain")["status"] == "COMMITTED"
    assert _act(table, session.match_id, "Darkness", destination={"x": 4, "y": 6})["status"] == "COMMITTED"
    return service, table, session.match_id


def test_legerdemain_manual_skill_choices_pause_without_spending_then_disarm_and_reload(tmp_path):
    service, table, mid = _dark_table(tmp_path)
    before = service._load_session(mid).engine.state.model_dump(mode="json")
    name = "Tenebrous Legerdemain: pull a weapon away"
    first = _act(table, mid, name)
    assert first["status"] == "REACTION_REQUIRED"
    assert first["reaction"]["context"]["reactor_id"] == LEFT
    assert "Tenebrous Legerdemain" in first["reaction"]["moment"] and "Right" in first["reaction"]["moment"]
    answer = {**first["reaction"]["context"], "selection": "USE", "option_ids": ["Dexterity (Sleight of Hand) contest"]}
    second = _act(table, mid, name, [answer])
    assert second["status"] == "REACTION_REQUIRED"
    prompt = second["reaction"]
    assert prompt["context"]["reactor_id"] == RIGHT
    assert {o["label"] for o in prompt["choice"]["options"]} == {"Strength (Athletics)", "Dexterity (Acrobatics)"}
    assert "Tenebrous Legerdemain" in prompt["moment"] and "Right" in prompt["moment"]
    assert service._load_session(mid).engine.state.model_dump(mode="json") == before
    defense = {**prompt["context"], "selection": "USE", "option_ids": ["1"]}
    assert _act(table, mid, name, [answer, defense])["status"] == "COMMITTED"
    engine = _reload(tmp_path, mid)
    event = next(e for e in engine.events if e.payload.get("roll_kind") == "opposed_check")
    assert event.payload["against"] == "Dexterity (Acrobatics)" and event.payload["success"]
    condition = next(c for c in engine.state.actors[RIGHT].conditions.values() if c.condition_id == te.CONDITION_PREFIX + "disarmed")
    assert condition.expires_on == "UNTIL_REMOVED"
    assert condition.data["dropped_at"] != engine.state.actors[RIGHT].position.model_dump(mode="json")
    assert not engine.state.actors[LEFT].bonus_action_available


def _choice_table(tmp_path, *, ai_actor=False, ai_defender=False):
    """Synthetic owned typed row isolates the general choice contract in the real table."""
    bundles = []
    for aid in (LEFT, RIGHT):
        b = compile_character(sheet([HUNGER] if aid == LEFT else []), actor_id=aid, reaction_plan={"ask": True})
        b["actor_template"]["initiative_bonus"] = 100 if aid == LEFT else -100
        if aid == LEFT:
            action = next(a for a in b["action_catalog"] if "oppose Charisma" in a["display_name"])
            action["display_name"] = "Training contest"
            action["parameters"]["expected_damage"] = 100
            action["parameters"]["typed"]["riders"] = []
            action["parameters"]["typed"]["effects"] = [{"type": "contest_against", "harmful": True,
                "actor_check": {"kind": "check", "ability": "DEX", "skill": "Sleight of Hand"},
                "target_check": {"options": [
                    {"kind": "check", "ability": "STR", "skill": "Athletics", "label": "Strength (Athletics)"},
                    {"kind": "check", "ability": "DEX", "skill": "Acrobatics", "label": "Dexterity (Acrobatics)"}]},
                "on_success": [{"type": "condition", "condition": "prone", "applies_to": "target"}],
                "on_fail": []}]
            b["action_catalog"] = [action]
            b["actor_template"]["action_ids"] = [action["source_definition_id"]]
        else:
            b["skills"] = {"Athletics": 100, "Acrobatics": 1}
        b.pop("bundle_sha256", None)
        b["bundle_sha256"] = canonical_sha256(b)
        bundles.append(b)
    service = CombatService(ROOT, tmp_path)
    session = service.persistence.create_match(match_seed="A11-CHOICES", typed_bundles=tuple(bundles),
        roster_setup={"primary_actor_ids": [LEFT, RIGHT], "team_by_actor": {LEFT: "team:a", RIGHT: "team:b"},
                      "starting_positions": {LEFT: {"x": 3, "y": 6}, RIGHT: {"x": 4, "y": 6}}})
    mid = session.match_id
    if ai_actor:
        service.set_controller_mode(mid, actor_id=LEFT, controller_mode="LOCAL_AUTO")
    if ai_defender:
        service.set_controller_mode(mid, actor_id=RIGHT, controller_mode="LOCAL_AUTO")
    return service, TabletopService(service, tmp_path), mid


@pytest.mark.parametrize("ai_actor", [False, True])
def test_manual_defender_chooses_skill_on_player_and_ai_turns_with_rollback(tmp_path, ai_actor):
    service, table, mid = _choice_table(tmp_path, ai_actor=ai_actor)
    before = service._load_session(mid).engine.state.model_dump(mode="json")
    result = table.auto_step(mid, 0) if ai_actor else _act(table, mid, "Training contest")
    assert result["status"] == "REACTION_REQUIRED"
    prompt = result["reaction"]
    assert prompt["context"]["reactor_id"] == RIGHT and "Training contest" in prompt["moment"]
    assert service._load_session(mid).engine.state.model_dump(mode="json") == before
    answer = {**prompt["context"], "selection": "USE", "option_ids": ["1"]}
    committed = table.auto_step(mid, 0, [answer]) if ai_actor else _act(table, mid, "Training contest", [answer])
    assert committed["status"] == "COMMITTED"
    engine = _reload(tmp_path, mid)
    event = next(e for e in engine.events if e.payload.get("roll_kind") == "opposed_check")
    assert event.payload["against"] == "Dexterity (Acrobatics)"


def test_ai_defender_automatically_uses_its_better_skill_and_failure_runs_no_success_branch(tmp_path):
    _, table, mid = _choice_table(tmp_path, ai_defender=True)
    assert _act(table, mid, "Training contest")["status"] == "COMMITTED"
    engine = _reload(tmp_path, mid)
    event = next(e for e in engine.events if e.payload.get("roll_kind") == "opposed_check")
    assert event.payload["against"] == "Strength (Athletics)" and not event.payload["success"]
    assert not any(c.condition_id == te.CONDITION_PREFIX + "prone" for c in engine.state.actors[RIGHT].conditions.values())


def test_natural_twenty_does_not_defeat_a_higher_opposed_total():
    engine = duel(HUNGER)
    actor, target = engine.state.actors[ME], engine.state.actors[FOE]
    actor.skills["Sleight of Hand"] = -10
    target.skills["Perception"] = 20
    action = next(a for a in engine.action_catalog.values() if a.owner_id == ME and a.parameters.get("typed"))
    ctx = te.Context(engine, actor, action, None, action.parameters["typed"], [target], target)
    script(engine, [1, 20])
    result = te.resolve_opposed_check(ctx, target,
        {"kind": "check", "ability": "DEX", "skill": "Sleight of Hand"},
        {"kind": "check", "ability": "WIS", "skill": "Perception"})
    assert result.actor.natural_result == 20 and result.target.natural_result == 1
    assert not result.success and result.margin == -11


@pytest.mark.parametrize("wins", [False, True])
def test_void_contest_reaction_uses_caster_check_and_persists_paid_outcome(tmp_path, wins):
    source = "TAL_VOID_RETURN_THE_TECHNIQUE_TO_NOTHING"
    bundles = []
    for aid, owned in ((LEFT, source), (RIGHT, "TAL_VOID_HOLLOW_TOUCH")):
        # Seeded dice still roll normally; extreme input modifiers isolate each
        # branch without patching a live engine or its roller.
        document = sheet([owned], cl=17)
        b = compile_character(document, actor_id=aid)
        b["actor_template"]["initiative_bonus"] = 100 if aid == RIGHT else -100
        for row in b.get("typed_reactions", []):
            if row.get("feature_id") == source:
                row["numbers"]["key_mod"] = 100 if wins else -100
        b.pop("bundle_sha256", None)
        b["bundle_sha256"] = canonical_sha256(b)
        bundles.append(b)
    service = CombatService(ROOT, tmp_path)
    session = service.persistence.create_match(match_seed="A11-VOID", typed_bundles=tuple(bundles),
        roster_setup={"primary_actor_ids": [LEFT, RIGHT], "team_by_actor": {LEFT: "team:a", RIGHT: "team:b"},
                      "starting_positions": {LEFT: {"x": 3, "y": 6}, RIGHT: {"x": 4, "y": 6}}})
    table, mid = TabletopService(service, tmp_path), session.match_id
    assert _act(table, mid, "Hollow Touch")["status"] == "COMMITTED"
    engine = _reload(tmp_path, mid)
    event = next((e for e in engine.events if e.payload.get("roll_kind") == "opposed_check"), None)
    assert event is not None, f"Missing opposed check; events: {engine.events!r}"
    assert event.actor_id == LEFT and event.target_ids == (RIGHT,) and event.payload["success"] is wins
    assert event.payload["target"]["total"] - event.payload["target"]["natural_result"] == 6
    assert engine.state.actors[LEFT].resources["resource:core.qi"] == 15
    assert not engine.state.actors[LEFT].reaction_available
    hollowed = [c for c in engine.state.actors[RIGHT].conditions.values() if c.condition_id == te.CONDITION_PREFIX + "hollowed"]
    assert bool(hollowed) is not wins
    if hollowed:
        assert hollowed[0].expires_on == "START_OF_SOURCE_NEXT_TURN"
    incoming = next((a.source_definition_id for a in engine.action_catalog.values()
                     if a.owner_id == RIGHT and a.display_name == "Hollow Touch"), None)
    assert incoming is not None, f"Missing Hollow Touch; catalog: {engine.action_catalog!r}"
    saves = [e for e in engine.events if e.event_type == "SAVE_ROLLED" and e.source_definition_id == incoming]
    assert bool(saves) is not wins


def test_opposed_skill_modes_cancel_independent_sources_and_preserve_defender_disadvantage():
    engine = duel(HUNGER)
    actor, target = engine.state.actors[ME], engine.state.actors[FOE]
    actor.skills["Sleight of Hand"] = target.skills["Perception"] = 0
    for subject in (actor, target):
        engine._apply_condition(subject, te.CONDITION_PREFIX + "check_mode", "test:penalty", subject.entity_id,
                                expires_on="END_OF_HOLDER_NEXT_TURN", data={"rule": {"check_mode": {"ALL": "DISADVANTAGE"}}})
    action = next(a for a in engine.action_catalog.values() if a.owner_id == ME and a.parameters.get("typed"))
    ctx = te.Context(engine, actor, action, None, action.parameters["typed"], [target], target)
    queue = script(engine, [14, 2, 10])
    result = te.resolve_opposed_check(ctx, target,
        {"kind": "check", "ability": "DEX", "skill": "Sleight of Hand", "mode": "ADVANTAGE"},
        {"kind": "check", "ability": "WIS", "skill": "Perception"})
    assert result.target.mode == "DISADVANTAGE" and result.target.total == 2
    assert result.actor.mode == "NORMAL" and result.actor.total == 10 and result.success
    assert not queue


@pytest.mark.parametrize("reaction", [False, True])
def test_charged_countermeasure_penalizes_only_the_owned_reaction_contest_roll(reaction):
    from combat.ext.charged_countermeasure import uses_roll

    assert uses_roll({"effects": [{"type": "contest_against"}]})
    engine = duel(HUNGER)
    actor, target = engine.state.actors[ME], engine.state.actors[FOE]
    actor.skills["Sleight of Hand"] = target.skills["Perception"] = 0
    action = next(a for a in engine.action_catalog.values() if a.owner_id == ME and a.parameters.get("typed"))
    typed = {**action.parameters["typed"], "reaction_attack": reaction}
    ctx = te.Context(engine, actor, action, None, typed, [target], target)
    engine._typed_reaction_frames = {
        (ME, ctx.source): {"penalty": {"actor_id": ME, "feature_id": ctx.source}},
    }
    script(engine, [10, 2, 12])
    result = te.resolve_opposed_check(ctx, target,
        {"kind": "check", "ability": "DEX", "skill": "Sleight of Hand"},
        {"kind": "check", "ability": "WIS", "skill": "Perception"})
    assert result.target.mode == "NORMAL"
    assert result.actor.mode == ("DISADVANTAGE" if reaction else "NORMAL")
    assert result.actor.total == 2


def test_automatic_roll_alternative_compares_cultivation_bonus_with_skill_total():
    from combat.ext.contests import select_check

    engine = duel(HUNGER)
    actor, target = engine.state.actors[ME], engine.state.actors[FOE]
    actor.skills["Sleight of Hand"] = 0
    action = next(a for a in engine.action_catalog.values() if a.owner_id == ME and a.parameters.get("typed"))
    ctx = te.Context(engine, actor, action, None, action.parameters["typed"], [target], target)
    chosen = select_check(ctx, actor, target, {"options": [
        {"kind": "check", "ability": "DEX", "skill": "Sleight of Hand", "label": "Dexterity (Sleight of Hand)"},
        {"kind": "cultivation", "label": "Cultivation Check"}]}, "actor")
    assert chosen["kind"] == "cultivation"


MEMORY = "tianxia.subpath.qi.bloodline_cultivator.feature.ancestral_memory_unsealed"
WHEEL = "tianxia.subpath.qi.samsara_wheel_cultivator.feature.wheel_turns_once"
COUNTERFLOW = "tianxia.subpath.qi.devil_heart_second_furnace.feature.heart_devil_counterflow"
CROWN = "tianxia.tradition.spirit.inner_soul_gate_ascetic.feature.crown_soul_gate"


def _interaction_table(tmp_path, *, owner=LEFT, feature=WHEEL, defending_save=False, penalty=None,
                       actor_feature=None, actor_floor=None, defender_modifier=None, first_actor=LEFT):
    """Owned compiled abilities, deterministic input modifiers, real table transactions."""
    bundles = []
    for aid in (LEFT, RIGHT):
        owned = ([HUNGER] if aid == LEFT else []) + ([feature] if aid == owner and feature else [])
        if aid == LEFT and actor_feature:
            owned.append(actor_feature)
        doc = sheet(owned, cl=18 if feature == CROWN and aid == owner else 10,
                    primary="Resonance" if feature in (MEMORY, CROWN) and aid == owner else "Qi")
        doc["identity"]["display_name"] = "Left" if aid == LEFT else "Right"
        b = compile_character(doc, actor_id=aid, reaction_plan={"ask": True})
        b["actor_template"]["initiative_bonus"] = 100 if aid == first_actor else -100
        if aid == RIGHT and defender_modifier is not None:
            b["actor_template"]["saving_throws"]["CHA"] = defender_modifier
        if aid == owner and feature == COUNTERFLOW:
            pool = next(r for r in b["actor_template"]["resources"] if r["resource_id"] == "resource:named.devil_qi")
            pool["initial"] = pool["maximum"]
        if aid == LEFT:
            action = next(a for a in b["action_catalog"] if "oppose Charisma" in a["display_name"])
            if not defending_save:
                action["display_name"] = "Training contest"
                action["parameters"]["typed"]["riders"] = []
                action["parameters"]["typed"]["effects"] = [{"type": "contest_against",
                    "actor_check": {"kind": "check", "ability": "DEX", "skill": "Sleight of Hand"},
                    "target_check": {"kind": "check", "ability": "STR", "skill": "Athletics"},
                    "on_success": [{"type": "condition", "condition": "prone", "applies_to": "target"}],
                    "on_fail": []}]
            elif not feature:
                # Seeded raw totals otherwise differ by 3. A +2 input modifier
                # puts them one point apart so the -2 save penalty flips outcome.
                action["parameters"]["typed"]["numbers"]["key_mod"] += 2
            b["action_catalog"] = [action]
            b["actor_template"]["action_ids"] = [action["source_definition_id"]]
            if actor_floor:
                import copy
                setup = copy.deepcopy(action)
                setup["source_definition_id"] += ".floor"
                setup["display_name"] = "Apply check floor"
                setup["economy"] = "ACTION"
                setup["parameters"]["typed"]["effects"] = [{"type": "d20_floor", "floor": actor_floor,
                    "applies_to": "self", "duration": "until_end_of_next_turn"}]
                setup["parameters"]["typed"]["riders"] = []
                b["action_catalog"].append(setup)
                b["actor_template"]["action_ids"].append(setup["source_definition_id"])
            if penalty:
                import copy
                setup = copy.deepcopy(action)
                setup["source_definition_id"] += ".setup"
                setup["display_name"] = "Apply save penalty"
                setup["economy"] = "ACTION"
                setup["parameters"]["typed"]["effects"] = [{"type": "condition", "condition": penalty,
                    "applies_to": "target", "duration": "until_end_of_next_turn"}]
                setup["parameters"]["typed"]["riders"] = []
                b["action_catalog"].append(setup)
                b["actor_template"]["action_ids"].append(setup["source_definition_id"])
        if not defending_save:
            b["skills"] = {"Sleight of Hand": -8 if owner == LEFT else 0, "Athletics": 4 if owner == RIGHT else 0}
        b.pop("bundle_sha256", None)
        b["bundle_sha256"] = canonical_sha256(b)
        bundles.append(b)
    service = CombatService(ROOT, tmp_path)
    session = service.persistence.create_match(match_seed="SOL91r", typed_bundles=tuple(bundles),
        roster_setup={"primary_actor_ids": [LEFT, RIGHT], "team_by_actor": {LEFT: "team:a", RIGHT: "team:b"},
                      "starting_positions": {LEFT: {"x": 3, "y": 6}, RIGHT: {"x": 4, "y": 6}}})
    return service, TabletopService(service, tmp_path), session.match_id


@pytest.mark.parametrize("feature,pool,cost", [(WHEEL, "qi", 3), (MEMORY, "resonance", 2)])
@pytest.mark.parametrize("owner,defending_save", [(LEFT, True), (LEFT, False), (RIGHT, False)])
@pytest.mark.parametrize("selection", ["USE", "DECLINE"])
def test_failed_contest_checks_offer_owned_reroll_consent_pay_and_reload(tmp_path, feature, pool, cost, owner, defending_save, selection):
    service, table, mid = _interaction_table(tmp_path, owner=owner, feature=feature, defending_save=defending_save)
    name = "oppose Charisma" if defending_save else "Training contest"
    before = service._load_session(mid).engine.state.model_dump(mode="json")
    required = _act(table, mid, name)
    assert required["status"] == "REACTION_REQUIRED"
    prompt = required["reaction"]
    assert prompt["context"]["reactor_id"] == owner
    assert ("Memory Before Thought" if feature == MEMORY else "Wheel Turns Once") in str(prompt)
    assert name in str(prompt) and ("Left" if owner == LEFT else "Right") in prompt["moment"]
    assert service._load_session(mid).engine.state.model_dump(mode="json") == before
    answer = {**prompt["context"], "selection": selection}
    assert _act(table, mid, name, [answer])["status"] == "COMMITTED"
    engine = _reload(tmp_path, mid)
    used = selection == "USE"
    assert engine.state.actors[owner].resources["resource:core." + pool] == 30 - (cost if used else 0)
    assert engine.state.actors[owner].reaction_available is (not used)
    rewrites = [e for e in engine.events if e.event_type == "D20_REWRITTEN" and e.source_definition_id == feature]
    assert len([e for e in rewrites if e.payload["operation"] == "reroll"]) == int(used)
    if feature == MEMORY and used:
        assert len([e for e in rewrites if e.payload["operation"] == "bonus" and e.payload["bonus"] == 4]) == 1
    contest = next(e for e in engine.events if e.payload.get("roll_kind") == "opposed_check")
    assert contest.payload["success"] is (defending_save if used else owner == RIGHT)
    adjusted = contest.payload["actor" if owner == LEFT else "target"]
    if used:
        assert adjusted["total"] == rewrites[-1].payload["result"]["total"]


@pytest.mark.parametrize("penalty", ["needle_soul_strike", "needle_shadow_strike"])
def test_hunger_defending_save_applies_typed_penalty_and_persists_outcome(tmp_path, penalty):
    # Both transactions start with the same seed/inputs. The setup condition
    # rolls no dice, isolating the printed -2 from initiative and randomness.
    captures = []
    for label, condition in (("control", None), ("penalized", penalty)):
        service, table, mid = _interaction_table(tmp_path / label, feature=None, defending_save=True, penalty=condition)
        if condition:
            assert _act(table, mid, "Apply save penalty")["status"] == "COMMITTED"
            setup_engine = _reload(tmp_path / label, mid)
            assert any(c.condition_id == te.CONDITION_PREFIX + condition for c in setup_engine.state.actors[RIGHT].conditions.values())
        assert _act(table, mid, "oppose Charisma")["status"] == "COMMITTED"
        engine = _reload(tmp_path / label, mid)
        captures.append(next(e.payload for e in engine.events if e.payload.get("roll_kind") == "opposed_check"))
    control, penalized = captures
    assert penalized["actor"] == control["actor"]
    assert penalized["target"]["natural_result"] == control["target"]["natural_result"]
    assert penalized["target"]["total"] == control["target"]["total"] - 2
    assert penalized["margin"] == control["margin"] + 2
    assert control["success"] is False and penalized["success"] is True


def test_dark_method_description_distinguishes_attack_ac_from_opposed_skill(tmp_path):
    _, _, mid = _dark_table(tmp_path)
    engine = _reload(tmp_path, mid)
    action = next(a for a in engine.action_catalog.values() if a.parameters.get("dark_legerdemain"))
    description = action.parameters["description"]
    assert "Attack that must hit the creature's AC" in description
    assert "check that must beat its chosen Strength (Athletics) or Dexterity" in description
    assert "A tied check leaves it held" in description


@pytest.mark.parametrize("selection", ["USE", "DECLINE"])
@pytest.mark.parametrize("actor_adjustment", ["floor", "reroll-use", "reroll-decline"])
@pytest.mark.parametrize("feature,pool,label", [(MEMORY, "resource:core.resonance", "Memory Before Thought"),
    (COUNTERFLOW, "resource:named.devil_qi", "Heart-Devil Counterflow")])
def test_defending_rewrite_bonus_settles_against_final_actor_total_at_table(tmp_path, selection, actor_adjustment, feature, pool, label):
    service, table, mid = _interaction_table(tmp_path, owner=RIGHT, feature=feature, defending_save=True,
        actor_feature=WHEEL if actor_adjustment.startswith("reroll") else None,
        actor_floor=20 if actor_adjustment == "floor" else None, defender_modifier=-2)
    if actor_adjustment == "floor":
        assert _act(table, mid, "Apply check floor")["status"] == "COMMITTED"
        _reload(tmp_path, mid)
    name = "oppose Charisma"
    before = service._load_session(mid).engine.state.model_dump(mode="json")
    required = _act(table, mid, name)
    assert required["status"] == "REACTION_REQUIRED"
    prompt = required["reaction"]
    assert prompt["context"]["reactor_id"] == RIGHT
    assert label in str(prompt) and name in str(prompt) and "Right" in prompt["moment"]
    assert service._load_session(mid).engine.state.model_dump(mode="json") == before
    answers = [{**prompt["context"], "selection": selection}]
    result = _act(table, mid, name, answers)
    if result["status"] == "REACTION_REQUIRED":
        actor_prompt = result["reaction"]
        assert actor_adjustment.startswith("reroll") and selection == "USE"
        assert actor_prompt["context"]["reactor_id"] == LEFT
        assert "Wheel Turns Once" in str(actor_prompt) and "Left" in actor_prompt["moment"]
        assert service._load_session(mid).engine.state.model_dump(mode="json") == before
        answers.append({**actor_prompt["context"], "selection": "USE" if actor_adjustment == "reroll-use" else "DECLINE"})
        result = _act(table, mid, name, answers)
    assert result["status"] == "COMMITTED"
    engine = _reload(tmp_path, mid)
    payload = next(e.payload for e in engine.events if e.payload.get("roll_kind") == "opposed_check")
    rewrites = [e for e in engine.events if e.event_type == "D20_REWRITTEN"]
    used = selection == "USE"
    backlash = feature == COUNTERFLOW and used and actor_adjustment == "reroll-decline"
    assert engine.state.actors[RIGHT].resources[pool] == before["actors"][RIGHT]["resources"][pool] - (2 if used else 0)
    assert engine.state.actors[RIGHT].reaction_available is (not used)
    assert payload["target"]["modifier"] == -2 + (4 if used else 0)
    assert payload["success"] is (payload["actor"]["total"] > payload["target"]["total"])
    assert payload["margin"] == payload["actor"]["total"] - payload["target"]["total"]
    assert "outcome_override" not in payload
    assert payload["target"]["total"] == (10 if used else 9)
    expected_actor = 26 if actor_adjustment == "floor" else 20 if used and actor_adjustment == "reroll-use" else 10
    assert payload["actor"]["total"] == expected_actor
    assert payload["tied"] is (used and actor_adjustment == "reroll-decline")
    memory_rewrites = [e for e in rewrites if e.source_definition_id == feature]
    # Native save rechecking includes the printed bonus in the single effective
    # rewrite record; a second bonus event would count it twice on this base.
    assert [e.payload["operation"] for e in memory_rewrites] == (["reroll"] if used else [])
    if used:
        assert (memory_rewrites[-1].payload["result"]["modifier"]
                - memory_rewrites[-1].payload["original"]["modifier"]) == 4
        assert memory_rewrites[-1].payload["result"] == payload["target"]
    if actor_adjustment.startswith("reroll"):
        assert len(answers) == (2 if used else 1)
        actor_used = used and actor_adjustment == "reroll-use"
        assert engine.state.actors[LEFT].resources["resource:core.qi"] == 30 - (3 if actor_used else 0)
        assert engine.state.actors[LEFT].reaction_available is (not (actor_used or backlash))
        assert len([e for e in rewrites if e.source_definition_id == WHEEL]) == int(actor_used)
    assert not getattr(engine, "_d20_rewrite_opposed_save", None)
    assert not getattr(engine, "_d20_rewrite_check_bonuses", None)
    assert not getattr(engine, "_d20_rewrite_save_riders", None)
    if feature == COUNTERFLOW:
        assert (engine.state.actors[LEFT].current_hp < before["actors"][LEFT]["current_hp"]) is backlash


@pytest.mark.parametrize("selection", ["USE", "DECLINE"])
def test_owned_crown_opening_forces_save_success_after_actor_floor_at_table(tmp_path, selection):
    from tests.test_lock2_persistence import act

    service, table, mid = _interaction_table(tmp_path, owner=RIGHT, feature=CROWN, defending_save=True,
        first_actor=RIGHT, actor_floor=20, defender_modifier=-20)
    assert _act(table, mid, "Crown Opening")["status"] == "COMMITTED"
    opened = _reload(tmp_path, mid)
    assert opened.state.actors[RIGHT].resources["resource:core.resonance"] == 21
    assert any(c.condition_id == "condition:typed.gate_opening" and c.data["gate"] == "crown"
               for c in opened.state.actors[RIGHT].conditions.values())
    assert act(table, mid, "end")["status"] == "COMMITTED"
    assert _act(table, mid, "Apply check floor")["status"] == "COMMITTED"
    _reload(tmp_path, mid)
    before = service._load_session(mid).engine.state.model_dump(mode="json")
    required = _act(table, mid, "oppose Charisma")
    assert required["status"] == "REACTION_REQUIRED"
    prompt = required["reaction"]
    assert prompt["context"]["reactor_id"] == RIGHT
    assert "Crown Opening" in str(prompt) and "oppose Charisma" in str(prompt) and "Right" in prompt["moment"]
    assert service._load_session(mid).engine.state.model_dump(mode="json") == before
    answer = {**prompt["context"], "selection": selection}
    assert _act(table, mid, "oppose Charisma", [answer])["status"] == "COMMITTED"
    engine = _reload(tmp_path, mid)
    used = selection == "USE"
    defender = engine.state.actors[RIGHT]
    assert defender.resources["resource:core.resonance"] == 21 - (2 if used else 0)
    assert defender.reaction_available  # Crown's success option does not spend a Reaction.
    limit = "_round_h1_round:" + CROWN
    assert defender.turn_flags.get(limit) == (engine.state.round_number if used else None)
    rewrites = [e for e in engine.events if e.event_type == "D20_REWRITTEN" and e.source_definition_id == CROWN]
    payload = next(e.payload for e in engine.events if e.payload.get("roll_kind") == "opposed_check")
    assert payload["actor"]["total"] == 26  # The actor's later floor raises its natural result to 20.
    assert payload["margin"] > 0 and not payload["tied"]
    assert payload["success"] is (not used)
    assert payload["target"]["modifier"] == -20  # Forced success is not a numeric bonus.
    assert len(rewrites) == int(used)
    if used:
        assert payload["outcome_override"] is False
        assert rewrites[0].payload["original"]["natural_result"] == rewrites[0].payload["result"]["natural_result"]
    else:
        assert "outcome_override" not in payload
    assert not engine._typed_roll_outcome
    assert not getattr(engine, "_d20_rewrite_check_bonuses", None)
    assert not getattr(engine, "_d20_rewrite_save_riders", None)


@pytest.mark.parametrize("outcome", ["success", "failure"])
@pytest.mark.parametrize("kind", ["save", "check"])
def test_registered_rewrite_can_force_either_opposed_outcome(monkeypatch, outcome, kind):
    from combat.ext.d20_rewrite import Holder, Rule, RULES

    engine = duel(HUNGER)
    actor, target = engine.state.actors[ME], engine.state.actors[FOE]
    # A synthetic registration exercises the shared contract, not an after-save override substitute.
    rule = Rule("test_explicit_outcome", "Training rewrite", rolls=(kind,), when="any", op="choose",
        choose=lambda e, h, rc: rc.natural, outcome=outcome,
        finder=lambda e: [Holder(target, "test:rewrite", {}, "test:rewrite")], ai=lambda e, h, rc: True)
    ext.effects()
    monkeypatch.setitem(RULES, rule.kind, rule)
    action = next(a for a in engine.action_catalog.values() if a.owner_id == ME and a.parameters.get("typed"))
    ctx = te.Context(engine, actor, action, None, action.parameters["typed"], [target], target)
    # Saves draw the actor first; two checks draw the defender first.
    actor_first = [20, 1] if outcome == "success" else [1, 20]
    script(engine, actor_first if kind == "save" else actor_first[::-1])
    result = te.resolve_opposed_check(ctx, target, {"kind": "cultivation"}, {"kind": kind, "ability": "CHA"})
    assert result.success is (outcome == "failure")
    assert result.outcome_override is (outcome == "failure")
    assert not engine._typed_roll_outcome


def test_opposed_save_numeric_scope_restores_nested_scope_after_exception():
    from types import SimpleNamespace
    from combat.ext.d20_rewrite import opposed_save_totals

    engine = SimpleNamespace()
    subject = SimpleNamespace(entity_id=RIGHT)
    with opposed_save_totals(engine, subject, "outer"):
        with pytest.raises(ValueError), opposed_save_totals(engine, subject, "inner"):
            assert engine._d20_rewrite_opposed_save == (RIGHT, "inner")
            raise ValueError("preview pause")
        assert engine._d20_rewrite_opposed_save == (RIGHT, "outer")
    assert not hasattr(engine, "_d20_rewrite_opposed_save")


def test_defending_save_explicit_forced_outcome_remains_separate_from_numeric_total(monkeypatch):
    engine = duel(HUNGER)
    actor, target = engine.state.actors[ME], engine.state.actors[FOE]
    action = next(a for a in engine.action_catalog.values() if a.owner_id == ME and a.parameters.get("typed"))
    ctx = te.Context(engine, actor, action, None, action.parameters["typed"], [target], target)

    def force_save_success(ctx, subject, ability, named, failed):
        ctx.engine._typed_roll_outcome = {subject.entity_id: "success"}

    ext.effects()
    monkeypatch.setitem(ext._HOOKS, "after_save", [force_save_success])
    script(engine, [20, 1])
    result = te.resolve_opposed_check(ctx, target, {"kind": "cultivation"}, {"kind": "save", "ability": "CHA"})
    assert result.margin > 0 and not result.success and result.outcome_override is False
    assert not engine._typed_roll_outcome
