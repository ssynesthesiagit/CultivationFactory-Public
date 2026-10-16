"""C2 review fixes exercised as saved table actions, including normal turns.

No browser is needed: TabletopService is the same choice/commit/reload path used
by the table UI. Scratch matches live only in pytest's explicit basetemp.
"""
import pytest

from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.test_riders_c2 import ROOT, ME, ATK, ALLY, CH, G, _sheet


def table_fixture(tmp_path, sheets, positions, *, seed="C2-REVIEW", foes=(ATK,), configure=None):
    bundles = [compile_character(sheet, actor_id=aid, reaction_plan={"ask": True}) for aid, sheet in sheets.items()]
    if configure:
        configure(bundles)
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    mid = combat._finish_factory_match(
        bundles, list(sheets), {aid: "team:b" if aid in foes else "team:a" for aid in sheets},
        {aid: {"x": xy[0], "y": xy[1]} for aid, xy in positions.items()},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"],
        [aid for aid in sheets if aid not in foes], list(foes),
        control_modes={aid: "MANUAL" for aid in sheets}, match_seed=seed,
        display_name="C2 review regression", maximum_rounds=20)["match_id"]
    return combat, table, mid


# Rider lane C16 added two core Guardian rules every Guardian has (Interpose, Held Harm): a manual Guardian is asked about them.
# These regressions predate them; they answer the way the table behaved before (no Interpose, damage taken at once), so each test
# still checks what it was written for.
C16_PROMPTS = {"choice:needle.interpose": None, "choice:needle.held_harm": None,
               # Starbolt now asks its printed optional Stellar Mark choice.
               # These setup hits require the mark; don't suppress that prompt.
               "choice:needle.starbolt_mark": "MARK"}


def c16_answers(step, answers=()):
    answers = list(answers)
    for _ in range(8):
        result = step(answers)
        if result["status"] != "REACTION_REQUIRED" or result["reaction"]["context"]["reaction_source_id"] not in C16_PROMPTS:
            return result
        context = result["reaction"]["context"]
        picked = C16_PROMPTS[context["reaction_source_id"]]
        answers.append({**context, "selection": "DECLINE"} if picked is None else {**context, "selection": "USE", "option_ids": [picked]})
    return result


def send(table, mid, cid, answers=()):
    def step(answers):
        menu = table.state(mid)["menu"]
        return table.act(mid, cid, menu["decision_id"], menu["state_version"], 0, list(answers))
    return c16_answers(step, answers)


def action(table, mid, name, target=None):
    menu = table.state(mid)["menu"]
    return next(o["candidate_id"] for g in menu["actions"] if g["label"] == name
                for o in g["options"] if target is None or target in o.get("target_ids", []))


def until_turn(table, mid, actor):
    for _ in range(10):
        menu = table.state(mid)["menu"]
        if menu["actor_id"] == actor:
            return
        assert send(table, mid, menu["end_turn"])["status"] == "COMMITTED"
    raise AssertionError("actor did not receive a normal turn")


def reload(tmp_path, mid):
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    assert session.mechanical.replay()["status"] == "PASS"
    return session.engine


@pytest.mark.parametrize("weapon,challenger_xy,penalized", [
    ("tianxia.mortal.weapon.gong_jian", (7, 6), True),  # guardian 20 ft, victim 10 ft
    ("tianxia.mortal.weapon.dao", (5, 7), False),  # visible, equally close, beyond melee reach
])
@pytest.mark.parametrize("auto_turn", [False, True])
def test_challenge_uses_committed_attack_range(tmp_path, weapon, challenger_xy, penalized, auto_turn):
    from combat.gate4_adapters import ManualControllerAdapter

    combat, table, mid = table_fixture(tmp_path, {
        ME: _sheet([CH, G + "PUNISHING_CHALLENGE"], dc=50),
        ATK: _sheet(["TAL_ALCHEMY_CALMING_HEART_PILL"], weapon=weapon),
        ALLY: _sheet(["TAL_ALCHEMY_CALMING_HEART_PILL"]),
    }, {ME: challenger_xy, ATK: (3, 6), ALLY: (5, 6) if penalized else (4, 6)})
    until_turn(table, mid, ME)
    assert send(table, mid, action(table, mid, "Challenge Practice", ATK))["status"] == "COMMITTED"
    assert any(c.condition_id == "condition:typed.challenged" for c in reload(tmp_path, mid).state.actors[ATK].conditions.values())
    assert send(table, mid, table.state(mid)["menu"]["end_turn"])["status"] == "COMMITTED"
    until_turn(table, mid, ATK)
    name = "Gong Jian (Bow and Arrow) attack" if penalized else "Dao (Saber / Broadsword) attack"
    cid = action(table, mid, name, ALLY)
    if auto_turn:
        real = combat.controller

        class AttackController:
            def choose_primary_action(self, context):
                return ManualControllerAdapter(lambda _: (cid, ())).choose_primary_action(context)

            def __getattr__(self, name):
                return getattr(real, name)

        combat.controller = AttackController()
        combat.set_controller_mode(mid, actor_id=ATK, controller_mode="LOCAL_AUTO")
        result = c16_answers(lambda answers: table.auto_step(mid, 0, list(answers)))
    else:
        result = send(table, mid, cid)
    assert result["status"] == "COMMITTED"
    engine = reload(tmp_path, mid)
    rolled = [e for e in engine.events if e.event_type == "ATTACK_ROLLED" and e.actor_id == ATK]
    assert (rolled[-1].payload["mode"] == "DISADVANTAGE") == penalized
    punished = [e for e in engine.events if e.event_type == "DAMAGE_COMMITTED"
                and e.payload.get("damage_type") in ("PSYCHIC", "RADIANT")]
    assert bool(punished) == penalized


def has(engine, aid, cid):
    return [c for c in engine.state.actors[aid].conditions.values() if c.condition_id == cid]


def end_turn(table, mid):
    assert send(table, mid, table.state(mid)["menu"]["end_turn"])["status"] == "COMMITTED"


def auto_send(combat, table, mid, cid, answers=()):
    """Run a chosen fixture trigger through the AI-turn service entry point."""
    from combat.gate4_adapters import ManualControllerAdapter

    real = combat.controller

    class TriggerController:
        def choose_primary_action(self, context):
            return ManualControllerAdapter(lambda _: (cid, ())).choose_primary_action(context)

        def __getattr__(self, name):
            return getattr(real, name)

    combat.controller = TriggerController()
    actor = table.state(mid)["menu"]["actor_id"]
    combat.set_controller_mode(mid, actor_id=actor, controller_mode="LOCAL_AUTO")
    try:
        return c16_answers(lambda answers: table.auto_step(mid, 0, list(answers)), answers)
    finally:
        combat.controller = real
        combat.set_controller_mode(mid, actor_id=actor, controller_mode="MANUAL")


@pytest.mark.parametrize("skip", [False, True])
@pytest.mark.parametrize("auto_turn", [False, True])
def test_choke_hold_real_rounds_reload_and_release(tmp_path, skip, auto_turn):
    from combat.ext.forged_exhaustion import level
    from combat.ext.wrestling import CHOKE, CHOKING, CHOKE_HISTORY

    combat, table, mid = table_fixture(tmp_path, {
        ME: _sheet(["TAL_WRESTLING_CHOKE_HOLD"], dc=50),
        ATK: _sheet(["TAL_ALCHEMY_CALMING_HEART_PILL"]),
    }, {ME: (3, 6), ATK: (4, 6)})
    until_turn(table, mid, ME)
    assert send(table, mid, action(table, mid, "Grapple", ATK))["status"] == "COMMITTED"
    assert send(table, mid, action(table, mid, "Apply a Slam: Choke Hold", ATK))["status"] == "COMMITTED"
    initial = reload(tmp_path, mid)
    assert has(initial, ATK, CHOKE) and not has(initial, ATK, CHOKING)
    first_round = initial.state.round_number
    end_turn(table, mid)
    until_turn(table, mid, ME)
    assert reload(tmp_path, mid).state.round_number == first_round + 1
    assert not has(reload(tmp_path, mid), ATK, CHOKE)
    assert has(reload(tmp_path, mid), ATK, CHOKE_HISTORY)
    if skip:
        end_turn(table, mid)
        assert not has(reload(tmp_path, mid), ATK, CHOKE_HISTORY)
        until_turn(table, mid, ME)
    assert send(table, mid, action(table, mid, "Apply a Slam: Choke Hold", ATK))["status"] == "COMMITTED"
    assert bool(has(reload(tmp_path, mid), ATK, CHOKING)) == (not skip)
    end_turn(table, mid)
    until_turn(table, mid, ATK)
    if auto_turn:
        assert auto_send(combat, table, mid, table.state(mid)["menu"]["end_turn"])["status"] == "COMMITTED"
    else:
        end_turn(table, mid)
    assert level(reload(tmp_path, mid).state.actors[ATK]) == (0 if skip else 1)
    until_turn(table, mid, ME)
    # Release without reapplying: recover immediately, even during the holder's turn.
    assert send(table, mid, action(table, mid, "Release grapple"))["status"] == "COMMITTED"
    engine = reload(tmp_path, mid)
    assert level(engine.state.actors[ATK]) == 0
    assert not has(engine, ATK, CHOKING) and not has(engine, ATK, CHOKE_HISTORY)


@pytest.mark.parametrize("saved,blocker", [
    (False, "none"), (False, "guardian"), (False, "late_check"),
    (True, "none"), (True, "late_check"),
])
def test_prison_tears_only_after_successful_table_teleport(tmp_path, monkeypatch, blocker, saved):
    from combat import ext

    blocked = blocker != "none"
    prison = "TAL_VERDANT_GROWTH_THOUSAND_ROOT_PRISON"
    guardian = [CH, G + "INESCAPABLE_CHALLENGE"] if blocker == "guardian" else []
    if blocker == "late_check":
        # Isolate the later generic sealing-array gate, without building a Formation.
        monkeypatch.setitem(ext._HOOKS, "teleport_check", [*ext._HOOKS["teleport_check"], lambda *args: False])
    target = sheet(["TAL_SPACE_FOLD_STEP"], cl=17, ac=0)
    target["ability_scores_and_statistics"]["hit_points"] = {"maximum": 400}  # it survives the three Seed-Thorn Strikes and the tear
    combat, table, mid = table_fixture(tmp_path, {
        ME: _sheet([prison, "TAL_VERDANT_GROWTH_SEED_THORN_STRIKE", *guardian], cl=17, dc=1 if saved else 50),
        ATK: target,
    }, {ME: (3, 6), ATK: (4, 6)})
    # "Target: One creature with at least 3 of your Growth Marks" (rider lane C16: the table counts them now): three Seed-Thorn
    # Strikes, one a turn, each placing a Growth Mark.
    from combat.ext import verdant_chassis

    for _ in range(6):
        until_turn(table, mid, ME)
        engine = reload(tmp_path, mid)
        if verdant_chassis.marks(engine.state.actors[ATK], engine.state.actors[ME]) >= 3:
            break
        assert send(table, mid, action(table, mid, "Seed-Thorn Strike", ATK))["status"] == "COMMITTED"
        end_turn(table, mid)
    until_turn(table, mid, ME)
    if blocker == "guardian":
        assert send(table, mid, action(table, mid, "Challenge Practice", ATK))["status"] == "COMMITTED"
    assert send(table, mid, action(table, mid, "Thousand-Root Prison", ATK))["status"] == "COMMITTED"
    end_turn(table, mid)
    until_turn(table, mid, ATK)
    initial = reload(tmp_path, mid)
    hold = "condition:typed.grappled" if saved else "condition:typed.restrained"
    assert has(initial, ATK, hold)
    before = len(initial.events)
    cid = next(c.candidate_id for c in initial.legal_candidates()
               if c.display_name == "Fold Step to 8,6")
    result = send(table, mid, cid)
    assert result["status"] == "COMMITTED"
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[ATK]
    assert (actor.position.x == 8) == (not blocked)
    assert bool(has(engine, ATK, hold)) == blocked
    tears = [e for e in engine.events[before:] if e.event_type == "DAMAGE_ROLLED"
             and e.payload.get("expression", "").startswith("4d10")]
    assert len(tears) == (0 if blocked else 1)
    assert not actor.bonus_action_available  # even a failed teleport pays its action economy
    if not blocked:
        # A second real turn/teleport cannot tear the already removed prison again.
        end_turn(table, mid)
        until_turn(table, mid, ATK)
        initial = reload(tmp_path, mid)
        before = len(initial.events)
        cid = next(c.candidate_id for c in initial.legal_candidates()
                   if c.display_name == "Fold Step to 7,6")
        assert send(table, mid, cid)["status"] == "COMMITTED"
        engine = reload(tmp_path, mid)
        assert engine.state.actors[ATK].position.x == 7
        assert not any(e.event_type == "DAMAGE_ROLLED"
                       and e.payload.get("expression", "").startswith("4d10")
                       for e in engine.events[before:])


def sheet(mids, *, initiative=1, ac=14, **kwargs):
    document = _sheet(mids, **kwargs)
    document["ability_scores_and_statistics"]["initiative"] = {"bonus": initiative}
    document["ability_scores_and_statistics"]["armor_class"] = {"base_value": ac}
    return document


@pytest.mark.parametrize("skip", [False, True])
def test_choke_hold_preserves_two_holders_and_unrelated_effects(tmp_path, skip):
    from copy import deepcopy
    from combat.canonical import canonical_sha256
    from combat.ext.forged_exhaustion import level
    from combat.ext.wrestling import CHOKE, CHOKING, CHOKE_HISTORY

    unrelated_source = "action:fixture.unrelated_silence_and_exhaustion"

    def configure(bundles):
        # A committed fixture action supplies unrelated effects, even from the
        # same actor as a holder. It is not a production ability or engine patch.
        bundle = next(b for b in bundles if b["actor_id"] == ME)
        fixture = deepcopy(next(a for a in bundle["action_catalog"] if a["resolution_kind"] == "TYPED"))
        fixture.update(source_definition_id=unrelated_source, display_name="Fixture: unrelated effects",
                       economy="NONE", target_kind="HOSTILE_ENTITY", range_ft=60, costs=[])
        fixture["parameters"] = {"typed": {"source": unrelated_source, "numbers": {}, "effects": [
            {"type": "condition", "condition": "silenced", "applies_to": "target", "expires_on": "UNTIL_REMOVED"},
            {"type": "exhaustion", "amount": 1, "applies_to": "target"}]}}
        bundle["action_catalog"].append(fixture)
        bundle["actor_template"]["action_ids"].append(unrelated_source)
        bundle.pop("bundle_sha256")
        bundle["bundle_sha256"] = canonical_sha256(bundle)

    _, table, mid = table_fixture(tmp_path, {
        ME: sheet(["TAL_WRESTLING_CHOKE_HOLD"], initiative=50, dc=50),
        ALLY: sheet(["TAL_WRESTLING_CHOKE_HOLD"], initiative=30, dc=50),
        ATK: sheet(["TAL_ALCHEMY_CALMING_HEART_PILL"], initiative=1),
    }, {ME: (3, 6), ALLY: (4, 7), ATK: (4, 6)}, configure=configure)

    def owned(engine, cid, owner):
        return [c for c in has(engine, ATK, cid) if c.source_actor_id == owner]

    def slam():
        assert send(table, mid, action(table, mid, "Apply a Slam: Choke Hold", ATK))["status"] == "COMMITTED"

    until_turn(table, mid, ME)
    assert send(table, mid, action(table, mid, "Fixture: unrelated effects", ATK))["status"] == "COMMITTED"
    unrelated = next(c.instance_id for c in has(reload(tmp_path, mid), ATK, "condition:typed.silenced")
                     if c.source_definition_id == unrelated_source)
    for holder in (ME, ALLY):
        until_turn(table, mid, holder)
        assert send(table, mid, action(table, mid, "Grapple", ATK))["status"] == "COMMITTED"
        slam()
        end_turn(table, mid)
    for holder in (ME, ALLY):
        until_turn(table, mid, holder)
        slam()
        end_turn(table, mid)
    until_turn(table, mid, ATK)
    end_turn(table, mid)
    engine = reload(tmp_path, mid)
    assert level(engine.state.actors[ATK]) == 3  # unrelated + one per holder
    assert {c.source_actor_id for c in has(engine, ATK, CHOKE_HISTORY)} == {ME, ALLY}
    assert all(owned(engine, CHOKE_HISTORY, h)[0].data["levels"] == 1 for h in (ME, ALLY))
    survivor_ids = {c.instance_id for cid in ((CHOKING, CHOKE_HISTORY) if skip else
                    (CHOKE, CHOKING, CHOKE_HISTORY, "condition:typed.silenced"))
                    for c in owned(engine, cid, ALLY)}
    until_turn(table, mid, ME)
    before = len(reload(tmp_path, mid).events)
    if skip:
        end_turn(table, mid)
    else:
        assert send(table, mid, action(table, mid, "Release grapple"))["status"] == "COMMITTED"
    engine = reload(tmp_path, mid)
    assert not owned(engine, CHOKE_HISTORY, ME) and not owned(engine, CHOKING, ME)
    assert level(engine.state.actors[ATK]) == 2
    assert survivor_ids <= set(engine.state.actors[ATK].conditions)
    assert unrelated in engine.state.actors[ATK].conditions
    removals = [e for e in engine.events[before:] if e.event_type == "CONDITION_REMOVED"]
    assert any(e.payload.get("condition_id") == CHOKE_HISTORY and e.payload.get("instance_id") for e in removals)
    assert not any(e.payload.get("instance_id") in survivor_ids | {unrelated} for e in removals)
    if not skip:
        end_turn(table, mid)
    until_turn(table, mid, ALLY)
    slam()
    assert owned(reload(tmp_path, mid), CHOKE_HISTORY, ALLY)[0].data["levels"] == 1
    end_turn(table, mid)
    until_turn(table, mid, ATK)
    end_turn(table, mid)
    assert level(reload(tmp_path, mid).state.actors[ATK]) == 3
    until_turn(table, mid, ALLY)
    assert send(table, mid, action(table, mid, "Release grapple"))["status"] == "COMMITTED"
    engine = reload(tmp_path, mid)
    assert not has(engine, ATK, CHOKE_HISTORY) and not has(engine, ATK, CHOKING)
    assert level(engine.state.actors[ATK]) == 1 and unrelated in engine.state.actors[ATK].conditions


def test_challenge_penalizes_committed_offhand_attack(tmp_path):
    _, table, mid = table_fixture(tmp_path, {
        ME: sheet([CH, G + "PUNISHING_CHALLENGE"], initiative=50, dc=50, ac=100),
        ATK: sheet(["TAL_ALCHEMY_CALMING_HEART_PILL"], initiative=30,
                   weapon="tianxia.mortal.weapon.hu_die_dao"),
        ALLY: sheet(["TAL_ALCHEMY_CALMING_HEART_PILL"], initiative=1, ac=100),
    }, {ME: (3, 6), ATK: (4, 6), ALLY: (4, 7)})
    until_turn(table, mid, ME)
    assert send(table, mid, action(table, mid, "Challenge Practice", ATK))["status"] == "COMMITTED"
    end_turn(table, mid)
    until_turn(table, mid, ATK)
    name = next(g["label"] for g in table.state(mid)["menu"]["actions"] if "attack" in g["label"] and "off-hand" not in g["label"])
    assert send(table, mid, action(table, mid, name, ME))["status"] == "COMMITTED"
    before = len(reload(tmp_path, mid).events)
    name = next(g["label"] for g in table.state(mid)["menu"]["actions"] if "off-hand attack" in g["label"])
    assert send(table, mid, action(table, mid, name, ALLY))["status"] == "COMMITTED"
    engine = reload(tmp_path, mid)
    events = engine.events[before:]
    assert next(e for e in events if e.event_type == "ATTACK_ROLLED").payload["mode"] == "DISADVANTAGE"
    punish = [e for e in events if e.event_type == "DAMAGE_COMMITTED" and e.target_ids == (ATK,)]
    assert len(punish) == 1 and punish[0].payload["damage_type"] in ("PSYCHIC", "RADIANT")
    assert punish[0].payload["hp_damage"] == 10


def test_challenge_penalizes_committed_generic_reaction(tmp_path):
    _, table, mid = table_fixture(tmp_path, {
        ME: sheet([CH, G + "PUNISHING_CHALLENGE"], initiative=50, dc=50),
        ALLY: sheet(["TAL_ALCHEMY_CALMING_HEART_PILL"], initiative=30, ac=100),
        ATK: sheet(["TAL_BERSERKER_BLOODY_COUNTER"], initiative=1),
    }, {ME: (3, 6), ATK: (4, 6), ALLY: (4, 7)})
    until_turn(table, mid, ME)
    assert send(table, mid, action(table, mid, "Challenge Practice", ATK))["status"] == "COMMITTED"
    end_turn(table, mid)
    until_turn(table, mid, ALLY)
    before = len(reload(tmp_path, mid).events)
    name = next(g["label"] for g in table.state(mid)["menu"]["actions"]
                if g["label"].startswith("Fu (") and g["label"].endswith(" attack"))
    cid = action(table, mid, name, ATK)
    result = send(table, mid, cid)
    assert result["status"] == "REACTION_REQUIRED"
    assert result["reaction"]["context"]["reaction_source_id"] == "reaction:typed.TAL_BERSERKER_BLOODY_COUNTER"
    assert send(table, mid, cid, [answer(result, "USE")])["status"] == "COMMITTED"
    engine = reload(tmp_path, mid)
    assert "TAL_BERSERKER_BLOODY_COUNTER" not in engine.action_catalog
    events = engine.events[before:]
    rolls = [e for e in events if e.event_type == "ATTACK_ROLLED" and e.actor_id == ATK]
    assert len(rolls) == 1 and rolls[0].payload["mode"] == "DISADVANTAGE"
    punish = [e for e in events if e.event_type == "DAMAGE_COMMITTED" and e.target_ids == (ATK,)
              and e.payload.get("damage_type") in ("PSYCHIC", "RADIANT")]
    assert len(punish) == 1
    assert punish[0].payload["hp_damage"] == 10


def test_declared_target_query_keeps_target_restrictions(tmp_path):
    """Unit guard for the general seam; the attack paths above are table tests."""
    from combat.attack_declaration import can_target

    _, _, mid = table_fixture(tmp_path, {
        ME: _sheet([CH]), ATK: _sheet(["TAL_ALCHEMY_CALMING_HEART_PILL"]),
    }, {ME: (3, 6), ATK: (4, 6)})
    engine = reload(tmp_path, mid)
    actor, target = engine.state.actors[ATK], engine.state.actors[ME]
    declared = next(a for a in engine.action_catalog.values() if a.owner_id == ATK
                    and a.display_name.startswith("Fu (") and a.display_name.endswith(" attack"))
    # Activation requirements have already been consumed; they cannot reject a
    # legal recipient. Recipient conditions, charm and plug-in restrictions can.
    spent = declared.model_copy(update={"parameters": {**declared.parameters,
        "requires_turn_flag": "fixture:spent", "requires_resource": {"fixture:empty": 99}}})
    assert can_target(engine, actor, target, spent.source_definition_id, action=spent)
    restricted = spent.model_copy(update={"parameters": {**spent.parameters, "target_requires_condition": "fixture:required"}})
    assert not can_target(engine, actor, target, restricted.source_definition_id, action=restricted)
    plugin_restricted = spent.model_copy(update={"parameters": {**spent.parameters, "slip_and_strike": True}})
    assert not can_target(engine, actor, target, plugin_restricted.source_definition_id, action=plugin_restricted)
    engine._apply_condition(actor, "condition:typed.charmed", "fixture:charm", target.entity_id, expires_on="UNTIL_REMOVED")
    assert not can_target(engine, actor, target, spent.source_definition_id, action=spent)


def answer(result, selection):
    prompt = result["reaction"]
    options = (prompt.get("choice") or {}).get("options") or []
    return {**prompt["context"], "selection": selection,
            "option_ids": [options[0]["id"]] if selection == "USE" and options else []}


@pytest.mark.parametrize("selection", ["USE", "DECLINE"])
@pytest.mark.parametrize("ai_ally", [False, True])
def test_guiding_star_player_or_ai_ally_chooses_before_consumption(tmp_path, selection, ai_ally):
    from combat.ext.stars import GUIDE_USED

    combat, table, mid = table_fixture(tmp_path, {
        ME: sheet(["STARS_BASE_STARBOLT", "tianxia.talent.stars.guiding_star"], initiative=100, dc=50),
        ALLY: sheet(["TAL_ALCHEMY_CALMING_HEART_PILL"], initiative=50),
        ATK: sheet(["TAL_ALCHEMY_CALMING_HEART_PILL"], initiative=-50, ac=1),
    }, {ME: (3, 6), ALLY: (4, 7), ATK: (4, 6)})
    until_turn(table, mid, ME)
    assert send(table, mid, action(table, mid, "Guiding Star", ATK))["status"] == "COMMITTED"
    assert any(c.data.get("guide_target_id") == ATK for c in reload(tmp_path, mid).state.actors[ME].conditions.values())
    end_turn(table, mid)
    until_turn(table, mid, ALLY)
    cid = action(table, mid, "Fu (Short Axe) attack", ATK)
    before = reload(tmp_path, mid).state.model_dump(mode="json")
    if ai_ally:
        result = auto_send(combat, table, mid, cid)
        assert result["status"] == "COMMITTED"
    else:
        result = send(table, mid, cid)
        assert result["status"] == "REACTION_REQUIRED"
        assert result["reaction"]["context"]["reaction_source_id"] == "choice:needle.stars_guiding_die"
        assert reload(tmp_path, mid).state.model_dump(mode="json") == before
        assert send(table, mid, cid, [answer(result, selection)])["status"] == "COMMITTED"
    engine = reload(tmp_path, mid)
    used = ai_ally or selection == "USE"
    assert (engine.state.actors[ALLY].turn_flags.get(GUIDE_USED) == engine.state.round_number) == used
    assert bool(engine.state.actors[ME].turn_flags.get(GUIDE_USED + "_given")) == used


@pytest.mark.parametrize("selection", ["USE", "DECLINE"])
@pytest.mark.parametrize("auto_turn", [False, True])
def test_seven_star_step_optional_choice_through_table(tmp_path, selection, auto_turn):
    combat, table, mid = table_fixture(tmp_path, {
        ME: sheet(["STARS_BASE_STARBOLT", "tianxia.talent.stars.seven_star_step"], initiative=100, dc=50),
        ATK: sheet(["TAL_ALCHEMY_CALMING_HEART_PILL"], initiative=-50, ac=1),
    }, {ME: (3, 6), ATK: (4, 6)})
    assert send(table, mid, action(table, mid, "Starbolt", ATK))["status"] == "COMMITTED"
    assert send(table, mid, action(table, mid, "Seven-Star Step"))["status"] == "COMMITTED"
    # This lane's existing state grants step movement; suppression belongs to each real committed pass-by.
    engine = reload(tmp_path, mid)
    cid = next(c.candidate_id for c in engine.legal_candidates() if c.display_name == "Move to 3,7")
    if auto_turn:
        result = auto_send(combat, table, mid, cid)
        assert result["status"] == "COMMITTED"
    else:
        result = send(table, mid, cid)
        assert result["status"] == "REACTION_REQUIRED"
        assert result["reaction"]["context"]["reaction_source_id"] == "choice:needle.stars_seven_star"
        assert send(table, mid, cid, [answer(result, selection)])["status"] == "COMMITTED"
    assert bool(has(reload(tmp_path, mid), ATK, "condition:typed.reaction_denied")) == (auto_turn or selection == "USE")


@pytest.mark.parametrize("selection", ["USE", "DECLINE"])
@pytest.mark.parametrize("auto_turn", [False, True])
def test_guiding_star_manual_beneficiary_is_asked_on_another_actors_turn(tmp_path, selection, auto_turn):
    from combat.ext.stars import GUIDE_USED

    combat, table, mid = table_fixture(tmp_path, {
        ALLY: sheet(["RETRIBUTION_BASE_COUNTERSTRIKE"], initiative=100),
        ME: sheet(["STARS_BASE_STARBOLT", "tianxia.talent.stars.guiding_star"], initiative=50, dc=50),
        ATK: sheet(["TAL_ALCHEMY_CALMING_HEART_PILL"], initiative=-50, ac=1),
    }, {ME: (3, 6), ALLY: (4, 7), ATK: (4, 6)})
    until_turn(table, mid, ALLY)
    cid = action(table, mid, "Counterstrike")
    prepared = send(table, mid, cid)
    assert prepared["status"] == "REACTION_REQUIRED"
    prompt = prepared["reaction"]
    selected = next(o["id"] for o in prompt["choice"]["options"] if "targets you" in o["label"])
    assert send(table, mid, cid, [{**prompt["context"], "selection": "USE", "option_ids": [selected]}])["status"] == "COMMITTED"
    end_turn(table, mid)
    until_turn(table, mid, ME)
    assert send(table, mid, action(table, mid, "Guiding Star", ATK))["status"] == "COMMITTED"
    end_turn(table, mid)
    until_turn(table, mid, ATK)
    cid = action(table, mid, "Fu (Short Axe) attack", ALLY)
    responses = []
    seen = []
    before = reload(tmp_path, mid).state.model_dump(mode="json")
    for _ in range(5):
        result = auto_send(combat, table, mid, cid, responses) if auto_turn else send(table, mid, cid, responses)
        if result["status"] == "COMMITTED":
            break
        assert result["status"] == "REACTION_REQUIRED"
        source = result["reaction"]["context"]["reaction_source_id"]
        seen.append(source)
        assert reload(tmp_path, mid).state.model_dump(mode="json") == before
        responses.append(answer(result, selection if source == "choice:needle.stars_guiding_die" else "USE"))
    else:
        raise AssertionError("off-turn choice did not commit")
    assert "choice:needle.stars_guiding_die" in seen
    engine = reload(tmp_path, mid)
    assert bool(engine.state.actors[ME].turn_flags.get(GUIDE_USED + "_given")) == (selection == "USE")


def test_guiding_star_does_not_spend_on_another_stellar_mark(tmp_path):
    other = "actor:factory.c2_other"
    combat, table, mid = table_fixture(tmp_path, {
        ME: sheet(["STARS_BASE_STARBOLT", "tianxia.talent.stars.guiding_star"], initiative=100, dc=50),
        ALLY: sheet(["TAL_ALCHEMY_CALMING_HEART_PILL"], initiative=50, weapon="tianxia.mortal.weapon.gong_jian"),
        ATK: sheet(["TAL_ALCHEMY_CALMING_HEART_PILL"], initiative=-50, ac=1),
        other: sheet(["TAL_ALCHEMY_CALMING_HEART_PILL"], initiative=-100, ac=1),
    }, {ME: (3, 6), ALLY: (3, 7), ATK: (4, 6), other: (5, 6)}, foes=(ATK, other))
    assert send(table, mid, action(table, mid, "Starbolt", other))["status"] == "COMMITTED"
    assert send(table, mid, action(table, mid, "Guiding Star", ATK))["status"] == "COMMITTED"
    end_turn(table, mid)
    until_turn(table, mid, ALLY)
    assert send(table, mid, action(table, mid, "Gong Jian (Bow and Arrow) attack", other))["status"] == "COMMITTED"
    from combat.ext.stars import GUIDE_USED

    assert not reload(tmp_path, mid).state.actors[ME].turn_flags.get(GUIDE_USED + "_given")


@pytest.mark.parametrize("following,auto_attack", [("check", False), ("attack", False), ("attack", True)])
def test_eye_watering_consumes_on_first_actual_perception_roll(tmp_path, following, auto_attack):
    eye = "condition:typed.pp_eye_watering"
    hidden = "actor:factory.c2_hidden"
    hiding_sheet = sheet(["DARK_BASE_DARKNESS", "TAL_THE_HIDDEN_EYE_FAST_STEALTH"], initiative=100)
    # A high stealth fixture keeps the creature hidden after both checks, so the
    # second Search really rolls rather than silently having no target.
    for ability in hiding_sheet["ability_scores_and_statistics"]["abilities"]:
        if ability["ability"] == "DEX":
            ability.update(score=90, modifier=40)
    combat, table, mid = table_fixture(tmp_path, {
        hidden: hiding_sheet,
        ME: sheet(["tianxia.talent.pressure_points.eye_watering_point"], initiative=50,
                  weapon="tianxia.mortal.weapon.gun"),
        ATK: sheet(["TAL_THE_HIDDEN_EYE_SUDDEN_ACUITY"], initiative=-50, ac=1,
                   weapon="tianxia.mortal.weapon.gong_jian"),
    }, {hidden: (3, 8), ME: (4, 6), ATK: (6, 6)}, seed="C2-EYE")
    until_turn(table, mid, hidden)
    engine = reload(tmp_path, mid)
    cid = next(c.candidate_id for c in engine.legal_candidates() if c.display_name == "Darkness at 2,9")
    assert send(table, mid, cid)["status"] == "COMMITTED"
    assert send(table, mid, action(table, mid, "Fast Stealth: Hide"))["status"] == "COMMITTED"
    assert has(reload(tmp_path, mid), hidden, "condition:typed.hidden")
    end_turn(table, mid)
    until_turn(table, mid, ME)
    assert send(table, mid, action(table, mid, "Touch the Point: Eye-Watering Point"))["status"] == "COMMITTED"
    assert send(table, mid, action(table, mid, "Gun (Staff) attack", ATK))["status"] == "COMMITTED"
    assert has(reload(tmp_path, mid), ATK, eye)
    end_turn(table, mid)
    until_turn(table, mid, ATK)
    before = len(reload(tmp_path, mid).events)
    assert send(table, mid, action(table, mid, "Sudden Acuity: Search"))["status"] == "COMMITTED"
    engine = reload(tmp_path, mid)
    checks = [e for e in engine.events[before:] if e.event_type == "CHECK_ROLLED" and e.actor_id == ATK]
    assert len(checks) == 1 and checks[0].payload["actor"]["mode"] == "DISADVANTAGE"
    assert not has(engine, ATK, eye)
    before = len(engine.events)
    if following == "check":
        assert send(table, mid, action(table, mid, "Search"))["status"] == "COMMITTED"
        checks = [e for e in reload(tmp_path, mid).events[before:] if e.event_type == "CHECK_ROLLED" and e.actor_id == ATK]
        assert len(checks) == 1 and checks[0].payload["actor"]["mode"] == "NORMAL"
    else:
        cid = action(table, mid, "Gong Jian (Bow and Arrow) attack", ME)
        result = auto_send(combat, table, mid, cid) if auto_attack else send(table, mid, cid)
        assert result["status"] == "COMMITTED"
        attacks = [e for e in reload(tmp_path, mid).events[before:] if e.event_type == "ATTACK_ROLLED" and e.actor_id == ATK]
        assert len(attacks) == 1 and attacks[0].payload["mode"] == "NORMAL"


def test_guiding_star_requires_visibility_of_its_target_location(tmp_path):
    combat, table, mid = table_fixture(tmp_path, {
        ME: sheet(["STARS_BASE_STARBOLT", "tianxia.talent.stars.guiding_star"], initiative=100, dc=50),
        ATK: sheet(["DARK_BASE_DARKNESS"], initiative=50),
        ALLY: sheet(["TAL_ALCHEMY_CALMING_HEART_PILL"], initiative=-50, weapon="tianxia.mortal.weapon.gong_jian"),
    }, {ME: (3, 6), ATK: (8, 6), ALLY: (3, 7)})
    assert send(table, mid, action(table, mid, "Guiding Star", ATK))["status"] == "COMMITTED"
    end_turn(table, mid)
    until_turn(table, mid, ATK)
    engine = reload(tmp_path, mid)
    cid = next(c.candidate_id for c in engine.legal_candidates() if c.display_name == "Darkness at 8,6")
    assert send(table, mid, cid)["status"] == "COMMITTED"
    end_turn(table, mid)
    until_turn(table, mid, ALLY)
    from combat.stealth import sees

    engine = reload(tmp_path, mid)
    assert not sees(engine, engine.state.actors[ALLY], engine.state.actors[ATK])
    assert send(table, mid, action(table, mid, "Gong Jian (Bow and Arrow) attack", ATK))["status"] == "COMMITTED"
    from combat.ext.stars import GUIDE_USED

    assert not reload(tmp_path, mid).state.actors[ME].turn_flags.get(GUIDE_USED + "_given")


@pytest.mark.parametrize("cl,selection,ai_owner,other_hp", [(10, "USE", False, False), (10, "DECLINE", False, False),
    (10, "USE", True, False), (1, "USE", False, False), (10, "USE", False, True)])
def test_sanguine_unknown_cr_requires_gm_confirmation(tmp_path, cl, selection, ai_owner, other_hp):
    spare = "actor:factory.c2_spare"
    victim = sheet(["TAL_ALCHEMY_CALMING_HEART_PILL"], initiative=-50, ac=1, cl=20)
    victim["ability_scores_and_statistics"]["hit_points"] = {"maximum": 1}
    combat, table, mid = table_fixture(tmp_path, {
        ME: sheet(["TAL_BERSERKER_SANGUINE_INVIGORATION", *([CH, G + "FLUSH_OF_VICTORY"] if other_hp else [])],
                  initiative=100, cl=cl, dc=50),
        ATK: victim,
        spare: sheet(["TAL_ALCHEMY_CALMING_HEART_PILL"], initiative=-100),
    }, {ME: (3, 6), ATK: (4, 6), spare: (12, 6)}, foes=(ATK, spare), seed="C2-SANGUINE")
    until_turn(table, mid, ME)
    if other_hp:
        assert send(table, mid, action(table, mid, "Challenge Practice", ATK))["status"] == "COMMITTED"
    cid = action(table, mid, "Fu (Short Axe) attack", ATK)
    before = reload(tmp_path, mid).state.model_dump(mode="json")
    if ai_owner:
        assert auto_send(combat, table, mid, cid)["status"] == "COMMITTED"
    else:
        result = send(table, mid, cid)
        assert result["status"] == "REACTION_REQUIRED"
        assert result["reaction"]["context"]["reaction_source_id"] == "choice:needle.berserker_sanguine_eligibility"
        text = str(result["reaction"])
        assert ("CR at least 1/2" if cl == 1 else "CR at least 5") in text
        assert reload(tmp_path, mid).state.model_dump(mode="json") == before
        assert send(table, mid, cid, [answer(result, selection)])["status"] == "COMMITTED"
    engine = reload(tmp_path, mid)
    assert engine.state.actors[ATK].current_hp == 0
    assert engine.state.actors[ME].temporary_hp == (cl if selection == "USE" and not ai_owner else 0)
    end_turn(table, mid)
    until_turn(table, mid, ME)
    assert reload(tmp_path, mid).state.actors[ME].temporary_hp == (cl if other_hp else 0)


def test_cold_star_mantle_saved_status_explains_bonus_and_duration(tmp_path):
    combat, table, mid = table_fixture(tmp_path, {
        ME: sheet(["tianxia.talent.stars.cold_star_mantle"], initiative=100),
        ATK: sheet(["TAL_ALCHEMY_CALMING_HEART_PILL"], initiative=-50),
    }, {ME: (3, 6), ATK: (4, 6)})
    assert send(table, mid, action(table, mid, "Cold Star Mantle", ME))["status"] == "COMMITTED"
    from combat.ext.stars import MANTLE

    [status] = has(reload(tmp_path, mid), ME, MANTLE)
    text = status.data["label"]
    assert "once per turn you may add 4" in text and "Radiant, Force or Cold" in text
    assert "1 minute" in text and "concentrates" in text and "no extra cost" in text
    assert "typed." not in text and "see its source" not in text


@pytest.mark.parametrize("auto_turn", [False, True])
def test_dense_body_status_choice_and_real_expiry_after_reload(tmp_path, auto_turn):
    combat, table, mid = table_fixture(tmp_path, {
        ME: sheet(["TAL_GRAVITY_WEIGHT_SHIFT_BASE", "tianxia.talent.gravity.ten_thousand_weight_body"], initiative=100),
        ATK: sheet(["TAL_ALCHEMY_CALMING_HEART_PILL"], initiative=-50),
    }, {ME: (3, 6), ATK: (4, 6)})
    assert send(table, mid, action(table, mid, "Weight Shift: Body Heavying"))["status"] == "COMMITTED"
    end_turn(table, mid)
    until_turn(table, mid, ATK)
    cid = table.state(mid)["menu"]["end_turn"]
    result = auto_send(combat, table, mid, cid) if auto_turn else send(table, mid, cid)
    assert result["status"] == "REACTION_REQUIRED"
    assert result["reaction"]["context"]["reaction_source_id"] == "choice:needle.gravity_ten_thousand"
    responses = [answer(result, "USE")]
    result = auto_send(combat, table, mid, cid, responses) if auto_turn else send(table, mid, cid, responses)
    assert result["status"] == "COMMITTED"
    engine = reload(tmp_path, mid)
    [status] = has(engine, ME, "condition:typed.state.ten_thousand_weight")
    text = status.data["label"]
    assert "melee attackers take 4 Force" in text and "10 feet" in text
    assert "start of your next turn" in text and "Speed" in text and "5 CP or Stamina" in text
    assert engine.state.actors[ME].resources["resource:core.stamina"] == 25
    end_turn(table, mid)
    until_turn(table, mid, ATK)
    end_turn(table, mid)
    engine = reload(tmp_path, mid)
    assert not has(engine, ME, "condition:typed.state.ten_thousand_weight")
    assert engine._effective_speed(engine.state.actors[ME]) == 20
    assert engine.state.actors[ME].movement_remaining_ft == 20
    end_turn(table, mid)
    until_turn(table, mid, ME)
    assert reload(tmp_path, mid).state.actors[ME].movement_remaining_ft == 30


@pytest.mark.parametrize("selection", ["USE", "DECLINE"])
@pytest.mark.parametrize("auto_turn", [False, True])
def test_sanguine_off_turn_gm_confirmation_on_manual_and_ai_turns(tmp_path, selection, auto_turn):
    spare = "actor:factory.c2_spare"
    victim = sheet(["TAL_ALCHEMY_CALMING_HEART_PILL"], initiative=-50, ac=1)
    victim["ability_scores_and_statistics"]["hit_points"] = {"maximum": 1}
    owner = sheet(["TAL_FENCING_PARRY_AND_RIPOSTE", "TAL_BERSERKER_SANGUINE_INVIGORATION"], initiative=100, ac=1)
    for ability in owner["ability_scores_and_statistics"]["abilities"]:
        if ability["ability"] == "STR":
            ability.update(score=90, modifier=40)  # normal weapon damage absorbs the full small hit
    combat, table, mid = table_fixture(tmp_path, {
        ME: owner,
        ATK: victim,
        spare: sheet(["TAL_ALCHEMY_CALMING_HEART_PILL"], initiative=-100),
    }, {ME: (3, 6), ATK: (4, 6), spare: (12, 6)}, foes=(ATK, spare), seed="C2-SANGUINE-OFFTURN")
    end_turn(table, mid)
    until_turn(table, mid, ATK)
    cid = action(table, mid, "Fu (Short Axe) attack", ME)
    responses, sources = [], []
    for _ in range(5):
        result = auto_send(combat, table, mid, cid, responses) if auto_turn else send(table, mid, cid, responses)
        if result["status"] == "COMMITTED":
            break
        assert result["status"] == "REACTION_REQUIRED"
        source = result["reaction"]["context"]["reaction_source_id"]
        sources.append(source)
        responses.append(answer(result, selection if "sanguine_eligibility" in source else "USE"))
    else:
        raise AssertionError("off-turn eligibility did not commit")
    assert "choice:needle.berserker_sanguine_eligibility" in sources
    engine = reload(tmp_path, mid)
    assert engine.state.actors[ME].temporary_hp == (10 if selection == "USE" else 0)
    assert engine.state.actors[ATK].current_hp == 0
