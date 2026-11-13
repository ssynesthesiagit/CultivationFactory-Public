"""Pressure-Point Strike lasts until the affected creature's next turn, including off-turn hits."""
import pytest

from combat.ext.tabik_ninpo import PPS, STAMINA
from combat.factory_compiler import compile_character
from combat.gate4_engine import Gate4ControllerEngine
from combat.gate5_service import CombatService
from combat.tabletop import ButtonStore
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet, script
from tests.test_lock2_persistence import act

PLAYER, FOE = "actor:factory.11111111", "actor:factory.22222222"
IRON_FIST = "tianxia.path.body_refining.feature.iron_fist"
SOURCE = f"passive:{PPS}"


def pressure_call(call, answers=()):
    """Explicitly accept C7's optional payment before testing LOG1's failed-save menu.

    Every replay carries that answer, including off-turn and AI-turn transport;
    the original effect/expiry/payment/reload assertions remain unchanged.
    """
    # Reviewed retry reservations retain every earlier answer. Resume the
    # saved prompt, then append this helper's payment or the caller's answer.
    result = call([])
    key = lambda row: tuple(row.get(k) for k in ('checkpoint', 'reactor_id', 'reaction_source_id'))
    for _ in range(24):
        if result.get('status') != 'REACTION_REQUIRED':
            return result
        prompt = result["reaction"]
        paid = next((a for a in answers if key(a) == key(prompt['context'])), None)
        if str(prompt['context'].get('reaction_source_id', '')).endswith('pressure_point_strike'):
            assert prompt["choice"]["allow_decline"]
            assert [o["id"] for o in prompt["choice"]["options"]] == ["use"]
            assert "1 Stamina" in prompt["moment"]
            paid = {**prompt["context"], "selection": "USE", "option_ids": ["use"]}
        if paid is None:
            return result
        prior = ((result.get('state') or {}).get('pending_action') or {}).get('reactions') or []
        result = call([*prior, paid])
    raise AssertionError('too many Pressure-Point choices')


def pressure_act(table, *args):
    from tests.iron_fist_support import answering_iron_fist  # the Iron Fist strike's damage-type question (L45)
    prior = (table.state(args[0]).get('pending_action') or {}).get('reactions') or []
    return pressure_call(answering_iron_fist(lambda paid: table.act(*args[:5], paid), initial_answers=prior),
                         args[5] if len(args) > 5 else ())


def pressure_fight(tmp_path, monkeypatch, choice, failed, *, owns_pressure=True, miss=False, stamina=30, legacy_pressure=False):
    original = Gate4ControllerEngine._resolve_attack_spec

    def hit(engine, *args, **kwargs):
        script(engine, [19, *([1] * 40)])
        return original(engine, *args, **kwargs)

    monkeypatch.setattr(Gate4ControllerEngine, "_resolve_attack_spec", hit)
    original_save = Gate4ControllerEngine._roll_save

    def save(engine, *args, **kwargs):
        # The attack mastery now owns its DC; this fixture explicitly selects
        # success/failure through the saving die, retaining all effect assertions.
        script(engine, [1 if failed else 20])
        return original_save(engine, *args, **kwargs)

    monkeypatch.setattr(Gate4ControllerEngine, "_roll_save", save)
    doc = sheet([PPS, IRON_FIST] if owns_pressure else [IRON_FIST], dc=100 if failed else -100)
    doc["identity"]["display_name"] = "Pressure Player"
    doc["ability_scores_and_statistics"]["primary_resource"]["definitions"] = [{"name": "Stamina", "max": stamina}]
    foe = sheet([IRON_FIST])
    foe["identity"]["display_name"] = "Pressure Target"
    foe["ability_scores_and_statistics"]["hit_points"]["maximum"] = 500
    if miss:
        foe["ability_scores_and_statistics"]["armor_class"]["base_value"] = 1000
    ButtonStore(tmp_path / "tabletop_buttons").save_reactions("11111111", {"mode": "ask"}, {"opportunity_attack"})
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    player_bundle = compile_character(doc, actor_id=PLAYER, reaction_plan={} if legacy_pressure else {"ask": True})
    if legacy_pressure:
        for row in player_bundle["typed_passives"]:
            row.pop("choice_owner", None)
        assert not any(row.get("ask") for row in player_bundle.get("typed_reactions", []))
    mid = combat._finish_factory_match(
        [player_bundle, compile_character(foe, actor_id=FOE)],
        [PLAYER, FOE], {PLAYER: "team:factory", FOE: "team:opponents"},
        {PLAYER: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [PLAYER], [FOE],
        control_modes={PLAYER: "MANUAL", FOE: "MANUAL"}, match_seed="LOG1-PRESSURE",
        display_name="Pressure expiry regression", maximum_rounds=20)["match_id"]
    while table.state(mid)["menu"]["actor_id"] != PLAYER:
        assert act(table, mid, "end")["status"] == "COMMITTED"
    if owns_pressure:
        action = next(a for a in combat._load_session(mid).engine.action_catalog.values()
                      if a.owner_id == PLAYER and a.source_definition_id.endswith(f".pressure_point.{choice}"))
        assert act(table, mid, action.source_definition_id)["status"] == "COMMITTED"
    return combat, table, mid


def reload(tmp_path, mid):
    combat = CombatService(ROOT, tmp_path)
    return combat, TabletopService(combat, tmp_path), combat._load_session(mid)


def pressure_effects(actor):
    return [e for e in [*actor.conditions.values(), *actor.modifiers.values()]
            if e.source_definition_id == SOURCE]


@pytest.mark.parametrize("choice,failed", [
    ("reactions", True), ("speed", True), ("attack", True),
    ("concentration", True), ("whisper", True), ("attack", False),
])
@pytest.mark.parametrize("off_turn", [False, True])
def test_pressure_expiry_survives_table_reload_until_targets_turn(tmp_path, monkeypatch, choice, failed, off_turn):
    combat, table, mid = pressure_fight(tmp_path, monkeypatch, choice, failed)
    answers = []
    if off_turn:
        assert act(table, mid, "end")["status"] == "COMMITTED"
        assert table.state(mid)["menu"]["actor_id"] == FOE
        state = table.state(mid)
        menu = state["menu"]
        move = next(m for m in menu["moves"] if m["destination"] == {"x": 6, "y": 6})
        args = (mid, move["candidate_id"], menu["decision_id"], menu["state_version"], state["last_sequence"])
        result = pressure_act(table, *args)
        assert result["status"] == "REACTION_REQUIRED"
        assert result["reaction"]["reaction"] == "Opportunity Attack"
        answers = [{**result["reaction"]["context"], "selection": "USE"}]
        result = pressure_act(table, *args, answers)
    else:
        action = next(a for a in combat._load_session(mid).engine.action_catalog.values()
                      if a.owner_id == PLAYER and a.display_name == "Iron Fist attack")
        state = table.state(mid)
        menu = state["menu"]
        group = next(g for g in menu["actions"] if g["source_definition_id"] == action.source_definition_id)
        args = (mid, group["options"][0]["candidate_id"], menu["decision_id"], menu["state_version"], state["last_sequence"])
        result = pressure_act(table, *args)
    if failed:
        assert result["status"] == "REACTION_REQUIRED"
        assert result["reaction"]["reaction"] == "Pressure-Point Strike"
        answers.append({**result["reaction"]["context"], "selection": "USE", "option_ids": [choice]})
        result = pressure_act(table, *args, answers)
    assert result["status"] == "COMMITTED"

    combat, table, loaded = reload(tmp_path, mid)
    target = loaded.engine.state.actors[FOE]
    before_turn = target.turns_started
    effects = pressure_effects(target)
    assert len(effects) == 1
    # Modifiers are filed under the current actor; conditions under their applier.
    expected = ("START_OF_SOURCE_NEXT_TURN" if off_turn and failed and choice in {"speed", "attack"}
                else f"START_OF_TURN_AT:{FOE}:{before_turn + 1}")
    assert effects[0].expires_on == expected
    assert loaded.engine.state.actors[PLAYER].resources[STAMINA] == 29
    saves = [e for e in combat.history(mid)["boundaries"][-1]["events"]
             if e["event_type"] == "SAVE_ROLLED" and e["source_definition_id"] == SOURCE]
    assert len(saves) == 1
    reaction_denied = not failed or choice == "reactions"
    # Reaction denial disables availability; the target's next turn restores it.
    assert target.reaction_available == (not reaction_denied)
    assert loaded.engine._reaction_usable(FOE, "test:reaction") == (not reaction_denied)
    if failed and choice == "attack":
        assert effects[0].target_field == "attack_mode" and effects[0].value == "DISADVANTAGE"
        assert effects[0].applies_to == "NEXT_ATTACK"
    if failed and choice == "speed":
        assert effects[0].target_field == "speed_ft" and effects[0].value == -10
        assert loaded.engine._effective_speed(target) == 20
    if failed and choice == "concentration":
        assert effects[0].condition_id == "condition:typed.concentration_mode"
        assert effects[0].data["rule"] == {"concentration_mode": "DISADVANTAGE", "next": True}
    if failed and choice == "whisper":
        assert effects[0].condition_id == "condition:typed.silenced"
    if not failed:
        assert effects[0].condition_id == "condition:typed.reaction_denied"

    if off_turn:
        # The source's next turn comes first: it must NOT end the target's disruption.
        assert act(table, mid, "end")["status"] == "COMMITTED"
        combat, table, loaded = reload(tmp_path, mid)
        assert loaded.engine.state.current_actor_id == PLAYER
        assert len(pressure_effects(loaded.engine.state.actors[FOE])) == 1
        assert loaded.engine._reaction_usable(FOE, "test:reaction") == (not reaction_denied)
    assert act(table, mid, "end")["status"] == "COMMITTED"
    _, _, loaded = reload(tmp_path, mid)
    target = loaded.engine.state.actors[FOE]
    assert loaded.engine.state.current_actor_id == FOE
    assert target.turns_started == before_turn + 1
    assert not pressure_effects(target)
    assert target.reaction_available and loaded.engine._reaction_usable(FOE, "test:reaction")
    assert loaded.engine._effective_speed(target) == 30
    assert loaded.mechanical.replay()["status"] == "PASS"
