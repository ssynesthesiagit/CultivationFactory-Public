"""AUTO129 / AUTO129r1f1: Shadow That Outlives the Body at the table.

Table/service level: a real fight through CombatService/TabletopService, the ability coming from the
rebuilt typed authority. HP is moved by real damage committed through the service (a reloaded engine is
a fresh copy; writing to it would not persist).

What the printed card says, and what each test pins:

* "Choose one: Drop to 1 HP instead of 0 HP." -- the blow that would kill leaves the creature at 1 HP,
  and a barely lethal blow (the one a 960-damage fixture cannot see) leaves exactly 1 HP, not half of it.
* "Until the end of your next turn: Gain Resistance to all damage except Radiant, Force, and Void
  effects." -- a standing Resistance that lasts the printed time, halves a later hit of a listed kind,
  does not halve the kinds the card excludes, survives a save-and-reload, and ends with the end of the
  owner's next turn.
* "Move up to 60 feet into a visible Shadowed Space" -- the Game Master places the creature: the table
  neither tracks light nor asks for a destination in the middle of a Reaction, so it must not move the
  creature by itself (see the strict xfail at the bottom for the in-trigger Choose One gap).
"""
import json

import pytest

from combat.canonical import canonical_sha256
from combat.factory_compiler import TYPED_AUTHORITY, compile_character
from tests.auto_worker1_support import LEFT, RIGHT, act, fight, reload
from tests.hunt15_support import turn
from tests.test_auto45_metal import settle

OUTLIVES = 'TAL_SHADOW_SHADOW_THAT_OUTLIVES_THE_BODY'
WARD = 'condition:typed.shadow_outlives_resistance'
MOVE_OPTION = 3
WARD_ROW = {"type": "condition", "condition": "shadow_outlives_resistance", "applies_to": "self",
            "condition_label": "Shadow That Outlives the Body: Resistance",
            "duration": "until_end_of_your_next_turn",
            "evidence": "Until the end of your next turn: Gain Resistance to all damage except Radiant, Force, and Void effects.",
            "origin": "auto129"}

MECH = json.loads(TYPED_AUTHORITY.read_bytes())['mechanics'][OUTLIVES]


def hit(amount, damage_types=("slashing",), applies_to="target"):
    return [{"type": "damage", "applies_to": applies_to, "flat": amount, "damage_types": list(damage_types),
             "evidence": "Cause: a blow."}]


MEND_ROW = {"type": "healing", "applies_to": "self", "flat": 500, "evidence": "Mend: regain 500 Hit Points."}
MEND = [MEND_ROW]
# One action that takes the caster to the edge and mends it back: the printed reaction then happens on the
# caster's OWN turn, so "until the end of your next turn" still covers the attacker's very next turn.
STING_AND_MEND = hit(210, ("slashing",), applies_to="self") + [MEND_ROW]


def extra_attacks(*attacks):
    """Give the attacking fighter more named attacks: extra_attacks(("Chip", hit(40, ("psychic",))), ...).

    One committed action per damage test keeps every number real: the fight's "Cause" weakens, then the
    named attack that triggers the printed reaction, then a light one the standing Resistance is read with.
    """
    def edit(bundle):
        if bundle["actor_id"] != RIGHT:
            return
        for label, effects in attacks:
            action_id = f"action:test.worker1.{label.lower()}"
            bundle["actor_template"]["action_ids"].append(action_id)
            bundle["action_catalog"].append({
                "source_definition_id": action_id, "display_name": label, "owner_id": RIGHT,
                "economy": "ACTION", "resolution_kind": "TYPED", "target_kind": "HOSTILE_ENTITY",
                "range_ft": 60, "costs": [],
                "parameters": {"typed": {"effects": effects,
                                         "numbers": {"cl": 15, "pb": 4, "key_mod": 3, "save_dc": 100},
                                         "duration": {"kind": "instant"}, "riders": []}}})
        bundle.pop("bundle_sha256", None)
        bundle["bundle_sha256"] = canonical_sha256(bundle)
    return edit


def answer(text):
    """Answer the printed offer the way a player would, choosing the option whose label carries ``text``."""
    def picker(prompt):
        choice = prompt.get('choice') or {}
        ids = [o['id'] for o in choice.get('options', [])]
        if not ids:                      # the Ask-me offer carries no menu: taking it is the whole answer
            return ["use"]
        labels = {o['id']: str(o.get('label', '')) for o in choice.get('options', [])}
        match = next((i for i in ids if text.lower() in labels.get(i, '').lower()), None)
        return [match] if match else ids[:max(1, choice.get('minimum', 1))]
    return picker


ACCEPT = answer('use')
DECLINE = lambda prompt: []  # noqa: E731  -- the printed use is offered; the player passes on it


def strike(table, match, label='Probe'):
    """One committed attack from the attacking fighter, answering every offer with the picker given."""
    def send(answers):
        state = table.state(match)
        cid = next(o["candidate_id"] for g in state["menu"]["actions"]
                   if g["label"] == label for o in g["options"]
                   if LEFT in o.get("target_ids", []))
        return table.act(match, cid, state["menu"]["decision_id"], state["menu"]["state_version"],
                         state["last_sequence"], list(answers))
    return send


def table_fight(tmp_path, talents, *, weaken=800, attacks=(("Probe", hit(210)),), prepare=MEND,
                reaction_options=None):
    """A creature brought to ``1000 - weaken`` Hit Points by a real committed blow."""
    combat, table, match = fight(tmp_path, talents, prepare=prepare, prepare_target="SELF",
                                 cause=hit(weaken), reaction_options=reaction_options,
                                 bundle_edit=extra_attacks(*attacks))
    turn(table, match, RIGHT)
    assert act(table, match, 'Cause', target_id=LEFT)['status'] == 'COMMITTED'
    turn(table, match, LEFT)
    turn(table, match, RIGHT)
    assert reload(combat, match).state.actors[LEFT].current_hp == 1000 - weaken
    return combat, table, match


def conditions(engine):
    return sorted(c.condition_id for c in engine.state.actors[LEFT].conditions.values())


# --- the printed Choose One menu the reaction plan carries ------------------
def test_the_printed_menu_is_carried_and_the_first_option_is_the_default():
    assert [option["label"] for option in MECH["options"]] == [
        "Drop to 1 HP",
        "Succeed on the triggering saving throw",
        "Turn the critical hit into a miss",
        "Move up to 60 feet into a Shadowed Space (your Game Master places you)",
        "End a restraint or grapple"]
    assert MECH["options"][0]["effects"][0] == {"type": "hold_at_1hp", "applies_to": "self", "keep": 1,
                                                "evidence": "Drop to 1 HP instead of 0 HP.", "origin": "auto129"}
    for index, option in enumerate(MECH["options"]):
        # "Until the end of your next turn" is printed after the list, so every option carries it.
        if index == MOVE_OPTION:
            assert option["effects"] == []  # the whole move Reaction is GM-resolved
        else:
            assert WARD_ROW in option["effects"], option["label"]
    assert MECH["cost"] == [[{"resource": "cp", "amount": 15, "amount_formula": None}]]
    assert MECH["use_limit"] == "once_per_week"


def test_the_reaction_row_costs_fifteen_cp_and_runs_the_saved_option():
    """The compiled row: 15 CP plus the Reaction, and the option the reaction plan picked."""
    from tests.h1_support import sheet
    from tests.test_carry import KIT

    document = sheet([OUTLIVES], cl=18, kit={"starting_kit": KIT})
    bundle = compile_character(document, actor_id="actor:factory.shadow",
                               reaction_plan={"ask": True, "options": {OUTLIVES: 0}})
    row = next(r for r in bundle["typed_reactions"] if r.get("feature_id") == OUTLIVES)
    assert row["kind"] == "drop_to_zero"
    assert row["costs"] == [{"resource_id": "resource:core.qi", "amount": 15},
                            {"resource_id": f"resource:uses.reaction:typed.{OUTLIVES}", "amount": 1}]
    assert row["use_limit"] == "once_per_week"
    assert [effect["type"] for effect in row["effects"]] == ["hold_at_1hp", "condition"], row["effects"]
    assert row["option"] == 0
    assert row["option_labels"] == [option["label"] for option in MECH["options"]]
    choice = next(c for c in bundle["reaction_plan"]["choices"] if c["id"] == OUTLIVES)
    assert choice["option"] == 0 and len(choice["options"]) == 5
    gm_bundle = compile_character(document, actor_id="actor:factory.shadow",
                                 reaction_plan={"ask": True, "options": {OUTLIVES: MOVE_OPTION}})
    assert not any(r.get("feature_id") == OUTLIVES for r in gm_bundle["typed_reactions"])


def test_drop_to_one_hp_replaces_zero(tmp_path):
    """Printed: "Drop to 1 HP instead of 0 HP." -- the creature ends at 1, not 0."""
    combat, table, match = table_fight(tmp_path, [OUTLIVES], attacks=(("Probe", hit(960)),))
    _, prompts = settle(strike(table, match), ACCEPT)
    assert reload(combat, match).state.actors[LEFT].current_hp == 1
    assert prompts, "the printed reaction was never offered"


@pytest.mark.parametrize("damage_type", ["slashing", "radiant", "force", "void"])
def test_a_barely_lethal_blow_also_leaves_exactly_one_hit_point(tmp_path, damage_type):
    """A barely lethal hit: the case a 960-damage fixture cannot see.

    A bare 'resistance' row in a damage reaction is read as an immediate halving of the very blow it
    answers (combat/typed_reactions._generic_damage_reduction), so this used to leave half the creature's
    Hit Points instead of 1.
    """
    combat, table, match = table_fight(tmp_path, [OUTLIVES], weaken=960,
                                      attacks=(("Probe", hit(50, (damage_type,))),))
    before = reload(combat, match).state.actors[LEFT]
    cp = before.resources["resource:core.qi"]
    settle(strike(table, match), ACCEPT)
    after = reload(combat, match).state.actors[LEFT]
    assert after.current_hp == 1
    assert after.resources["resource:core.qi"] == cp - 15
    assert not after.reaction_available
    assert after.resources[f"resource:uses.reaction:typed.{OUTLIVES}"] == 0


def test_an_unowned_shadow_is_inert(tmp_path):
    """Nobody else gets this reaction: the same blow still drops them to 0."""
    combat, table, match = table_fight(tmp_path, [])
    _, prompts = settle(strike(table, match), ACCEPT)
    engine = reload(combat, match)
    assert engine.state.actors[LEFT].current_hp == 0
    assert not prompts
    assert WARD not in conditions(engine)


def test_declining_the_reaction_leaves_the_printed_result(tmp_path):
    combat, table, match = table_fight(tmp_path, [OUTLIVES])
    settle(strike(table, match), DECLINE)
    assert reload(combat, match).state.actors[LEFT].current_hp == 0
    assert WARD not in conditions(reload(combat, match))


def test_the_offer_names_the_ability_in_plain_words(tmp_path):
    """Item 9: the prompt names the ability and says what it does."""
    _, table, match = table_fight(tmp_path, [OUTLIVES])
    _, prompts = settle(strike(table, match), ACCEPT)
    assert 'Shadow That Outlives the Body' in str(prompts), prompts
    assert '15' in str(prompts), prompts


def test_an_ai_owner_survives_without_asking_the_player(tmp_path):
    combat, table, match = table_fight(tmp_path, [OUTLIVES], weaken=960,
                                      attacks=(("Probe", hit(50)),))
    combat.set_controller_mode(match, actor_id=LEFT, controller_mode="LOCAL_AUTO")
    _, prompts = settle(strike(table, match), ACCEPT)
    engine = reload(combat, match)
    assert not prompts
    assert engine.state.actors[LEFT].current_hp == 1
    assert engine.state.actors[LEFT].resources["resource:core.qi"] == 85
    assert WARD in conditions(engine)


# --- "Until the end of your next turn: Gain Resistance ..." -----------------
def test_the_resistance_lands_and_survives_a_save_and_reload(tmp_path):
    combat, table, match = table_fight(tmp_path, [OUTLIVES])
    settle(strike(table, match), ACCEPT)
    engine = reload(combat, match)          # reload() cold-loads and replays the committed fight
    assert WARD in conditions(engine)
    held = engine.state.actors[LEFT].conditions[next(
        i for i, c in engine.state.actors[LEFT].conditions.items() if c.condition_id == WARD)]
    assert held.expires_on == f"END_OF_SOURCE_TURN_AT:{int(engine.state.actors[LEFT].turns_started) + 1}", held.expires_on
    pill = next(c for actor in table.state(match)["presentation"]["actors"]
                if actor["entity_id"] == LEFT for c in actor["conditions"] if c["condition_id"] == WARD)
    assert "until the end of your next turn" in pill["rule_text"]
    assert "Radiant, Force and Void damage are not resisted" in pill["rule_text"]
    assert "It takes half damage from Acid, Bludgeoning" in pill["rule_text"]
    assert "reviewed_final" not in pill["rule_text"]


@pytest.mark.parametrize(("listed", "excluded"), [(("psychic",), ("force", "radiant", "void"))])
def test_the_resistance_halves_a_later_hit_but_not_the_kinds_the_card_excludes(tmp_path, listed, excluded):
    """Listed kinds are halved while the printed Resistance lasts; Force and Radiant are printed as excluded."""
    chip = hit(40, listed) + [row for kind in excluded for row in hit(40, (kind,))]
    combat, table, match = table_fight(tmp_path, [OUTLIVES], prepare=STING_AND_MEND, attacks=(("Chip", chip),))
    turn(table, match, LEFT)                       # the caster's own turn: it takes the lethal blow itself
    settle(lambda answers: act(table, match, 'Prepare', answers=list(answers)), ACCEPT)
    engine = reload(combat, match)
    assert engine.state.actors[LEFT].current_hp == 501, engine.state.actors[LEFT].current_hp
    assert WARD in conditions(engine)
    turn(table, match, RIGHT)
    settle(strike(table, match, label='Chip'), ACCEPT)
    assert reload(combat, match).state.actors[LEFT].current_hp == 501 - 20 - 120


def test_the_resistance_ends_with_the_end_of_your_next_turn(tmp_path):
    """Item 8: the printed duration is a name the engine removes, and nothing lasts by accident."""
    combat, table, match = table_fight(tmp_path, [OUTLIVES])
    settle(strike(table, match), ACCEPT)
    assert WARD in conditions(reload(combat, match))
    turn(table, match, LEFT)                # the owner's next turn begins
    turn(table, match, RIGHT)               # ... and ends
    assert WARD not in conditions(reload(combat, match))


# --- the printed Shadowed-Space move ---------------------------------------
def test_the_shadowed_space_move_is_the_game_masters_and_the_table_does_not_move_itself(tmp_path):
    """A reaction_move row picks a square itself and never asks (combat/typed_executor.block_reaction_move),
    so the printed move must not be typed as one: the Game Master places the creature."""
    combat, table, match = table_fight(tmp_path, [OUTLIVES], reaction_options={OUTLIVES: MOVE_OPTION})
    actor = reload(combat, match).state.actors[LEFT]
    before = actor.position.model_dump(mode="json")
    resources = dict(actor.resources)
    _, prompts = settle(strike(table, match), ACCEPT)
    engine = reload(combat, match)
    assert not prompts, "the GM-resolved option must not spend an automated Reaction"
    assert engine.state.actors[LEFT].position.model_dump(mode="json") == before
    assert not [e for e in engine.events if e.event_type == "MOVEMENT_COMMITTED"]
    assert WARD not in conditions(engine)
    assert engine.state.actors[LEFT].resources == resources


def test_the_move_option_says_who_places_the_creature():
    label = MECH["options"][MOVE_OPTION]["label"]
    assert "Game Master" in label, label
    rider = " ".join(MECH["options"][MOVE_OPTION]["riders"])
    assert "Game Master resolves this Reaction" in rider and "places your creature" in rider, rider
    assert "15 CP" in rider and "shadow corpse" in rider, rider


# --- the tracked gap ------------------------------------------------------
@pytest.mark.xfail(
    strict=True,
    reason="AUTO90 S6 (recorded lock work): the reaction hook fires with no moment to pick, so a "
           "'Choose one' reaction runs the option its reaction plan saved (combat/factory_compiler."
           "_default_reaction_option) instead of asking. life_state.survival_consent (a plug-in) presents "
           "a plain yes/no on the 0 HP trigger. When the in-trigger menu lands this must pass.",
)
def test_the_printed_choose_one_menu_is_offered_on_the_zero_hp_trigger(tmp_path):
    """The printed card says "Choose one"; on the 0 HP trigger the table still asks a plain yes/no.

    Teaching that consent to present the printed menu is the fix; this strict expected failure must start
    passing when it does, so the gap cannot regress silently.
    """
    _, table, match = table_fight(tmp_path, [OUTLIVES])
    _, prompts = settle(strike(table, match), answer('move up to 60 feet'))
    labels = ' '.join(str(o.get('label', '')) for prompt in prompts
                      for o in ((prompt.get('choice') or {}).get('options') or []))
    assert 'Move up to 60 feet' in labels, prompts
    assert 'Succeed on the triggering saving throw' in labels, prompts
