"""Systems the automation lanes found missing (owner 2026-09-29: "i want everything we can automated, keep going until its
only the non-combat ones left"): choose-one summon forms (Painting Cultivator, Living Painting), and the menus and limits
that follow.  Every ability is compiled on a real character and run through the engine; each test fails without the change.

Overrides: authority/typed_mechanics/reviewed_final.d/sys_menus-forms.json; plug-ins: combat/ext/painting_forms.py.
Non-attack saves use the sheet's technique DC (16, or 50 where the save must fail).
Nine-Bell uses its selected attack ability's DC after merge 6592dcfa; its tests force the target's CON save bonus.
Attacks always hit (foe AC -50).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_auto_lane1 as lane1  # noqa: E402  (the shared harness: sheets built from one authority mechanic)
from combat import summons  # noqa: E402
from combat.ext import menus, painting_forms, target_limits  # noqa: E402
from combat.gate2_runtime_models import ActionIntent, Position  # noqa: E402
from combat.gate4_engine import Gate4ControllerEngine  # noqa: E402

ME, ROOT = lane1.ME, lane1.ROOT
FOE1, FOE2 = "actor:factory.sys_foe1", "actor:factory.sys_foe2"
LIVING_PAINTING = "tianxia.subpath.qi.painting_cultivator.feature.living_painting"
WORLD_OF_DREAMS = "tianxia.talent.dreams.world_of_dreams"
WOD_PSYCHIC = "Enemies entering or starting inside take 3d8 Psychic damage (Wisdom save)"
WOD_REACTIONS, WOD_DIFFICULT = "Enemies cannot take Reactions", "Enemies treat the area as difficult terrain"
WOD_WIS = "Enemies have Disadvantage on Wisdom saving throws"


# ------------------------------------------------------------------------------------------------------- harness


def _foe(actor_id):
    """Any compiled character will do as an opponent: it carries the standing actions (Escape grapple) a bare foe lacks."""
    return lane1._bundle("TAL_ALCHEMY_CALMING_HEART_PILL", actor_id=actor_id)


def _fight(mid=LIVING_PAINTING, *, dc=16, foes=(FOE1,), bundle=None):
    bundle = bundle or lane1._bundle(mid, dc=dc)
    team = {ME: "team:a", **{f: "team:b" for f in foes}}
    engine = Gate4ControllerEngine(
        ROOT, match_seed="SYSFORMS", typed_bundles=(bundle, *(_foe(f) for f in foes)),
        roster_setup={"primary_actor_ids": [ME, *foes], "team_by_actor": team,
                      "starting_positions": {ME: {"x": 3, "y": 6}, **{f: {"x": 12, "y": 6 + i} for i, f in enumerate(foes)}}})
    if engine.state.setup_tasks:
        candidate = engine.legal_candidates()[0]
        engine.execute_intent(ActionIntent(intent_id="test:finish-setup", decision_id=candidate.decision_id,
                                           candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                           actor_id=candidate.actor_id))
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    for f in foes:
        engine.state.actors[f].armor_class = -50
    lane1._ready(engine)
    return engine


def _do(engine, actor, name, *, target=None, destination=None):
    """Runs the legal candidate called ``name`` for ``actor``; returns the events it made."""
    engine.state.current_actor_id = actor.entity_id
    matches = [c for c in engine.legal_candidates() if (c.display_name == name or (destination is not None and c.display_name.startswith(name + " ")))
               and (destination is None or (c.destination and (c.destination.x, c.destination.y) == destination))
               and (target is None or target in (c.target_ids or ()))]
    assert matches, f"{name!r} is not legal for {actor.display_name}; legal: {sorted({c.display_name for c in engine.legal_candidates() if not c.display_name.startswith('Move')})}"
    c, before = matches[0], len(engine.events)
    engine.execute_intent(ActionIntent(intent_id=f"i-{name}", decision_id=c.decision_id, candidate_id=c.candidate_id, state_version=c.state_version,
                                       actor_id=actor.entity_id, target_ids=(target,) if target else (c.target_ids or ()), destination=c.destination))
    return engine.events[before:]


def _names(engine, actor):
    engine.state.current_actor_id = actor.entity_id
    return {c.display_name for c in engine.legal_candidates() if not c.display_name.startswith("Move")}


def _form(engine, form):
    return summons.owned_by(engine, ME, f"living_painting_{form}")[0]


def _call(engine, form):
    """Calls the form, commands it, and ends the summoner's turn so the form's turn is up; returns the form."""
    me = engine.state.actors[ME]
    lane1._ready(engine)
    _do(engine, me, f"Living Painting: {form.title()}")
    creature = _form(engine, form)
    _do(engine, me, "Command Living Painting")
    engine.end_turn()
    assert engine.state.current_actor_id == creature.entity_id
    return creature


def _held(actor, condition_id):
    return [c for c in actor.conditions.values() if c.condition_id == condition_id]


# ------------------------------------------------------------------------------------------- the four forms


def test_living_painting_is_a_menu_of_four_forms_not_one_blank_action():
    """"Choose: Tiger, Crane, Tortoise, Serpent.  You may maintain one Living Painting.": the typing carried no effect at all."""
    engine = _fight()
    me = engine.state.actors[ME]
    names = _names(engine, me)
    assert {f"Living Painting: {form}" for form in ("Tiger", "Crane", "Tortoise", "Serpent")} <= names
    assert [(s.summon["group"], s.summon["status"]) for s in summons.owned_by(engine, ME)] == [
        (f"living_painting_{form}", "waiting") for form in ("tiger", "crane", "tortoise", "serpent")]
    events = _do(engine, me, "Living Painting: Tiger")
    tiger = _form(engine, "tiger")
    assert tiger.active and tiger.summon["status"] == "present" and tiger.team_id == me.team_id
    assert engine.grid.distance_ft(tiger.position, me.position) <= 30  # Range 30 feet
    assert {e.event_type for e in events} >= {"CONCENTRATION_STARTED", "SUMMON_APPEARED"}
    assert "Living Painting: Crane" in _names(engine, me) or not me.action_available  # a second call waits for the next Action


def test_calling_another_form_takes_the_first_away():
    """"You may maintain one Living Painting."""
    engine = _fight()
    me = engine.state.actors[ME]
    _do(engine, me, "Living Painting: Tiger")
    lane1._ready(engine)
    events = _do(engine, me, "Living Painting: Crane")
    tiger, crane = _form(engine, "tiger"), _form(engine, "crane")
    assert not tiger.active and tiger.summon["status"] == "dismissed" and crane.active
    assert any(e.event_type == "SUMMON_DISMISSED" and (e.payload or {}).get("reason") == "REPLACED" for e in events)
    assert len(summons.owned_by(engine, ME)) == 4 and sum(s.active for s in summons.owned_by(engine, ME)) == 1
    engine._end_concentration(me, "TEST")  # it lasts while the summoner concentrates
    assert not crane.active


def test_one_command_serves_whichever_form_is_out():
    engine = _fight()
    me = engine.state.actors[ME]
    assert "Command Living Painting" not in _names(engine, me)
    _do(engine, me, "Living Painting: Serpent")
    assert "Command Living Painting" in _names(engine, me)
    assert sum(1 for a in engine.action_catalog.values() if a.display_name == "Command Living Painting") == 1  # one, not four


# --------------------------------------------------------------------------------------------------- Tiger


def _tiger_strike(closes_ft, gap_ft=5):
    """The tiger, on its turn, runs ``closes_ft`` straight along a row toward a foe that ends ``gap_ft`` short of it, then
    strikes."""
    engine = _fight(dc=50)
    foe = engine.state.actors[FOE1]
    tiger = _call(engine, "tiger")
    start = tiger.position
    steps, gap = closes_ft // 5, gap_ft // 5
    foe.position = Position(x=start.x + steps + gap, y=start.y)
    _do(engine, tiger, "Move to", destination=(start.x + steps, start.y))
    events = _do(engine, tiger, "Painted Strike")
    return engine, tiger, foe, events


def test_tiger_pouncing_stroke_knocks_prone_after_moving_twenty_feet_toward_the_target():
    """"If the Tiger moves at least 20 feet straight toward a creature before hitting it with Painted Strike, the target makes
    a Strength saving throw.  Failed Save: Knocked Prone."  Twenty feet closed is exactly enough."""
    engine, tiger, foe, events = _tiger_strike(20)
    assert any(e.event_type == "DAMAGE_COMMITTED" for e in events)
    assert [p["success"] for p in lane1._payloads(events, "SAVE_ROLLED")] == [False]
    assert _held(foe, "condition:typed.prone")


def test_tiger_moving_less_than_twenty_feet_does_not_pounce():
    engine, tiger, foe, events = _tiger_strike(15)
    assert any(e.event_type == "DAMAGE_COMMITTED" for e in events)
    assert not lane1._payloads(events, "SAVE_ROLLED") and not _held(foe, "condition:typed.prone")


def test_tiger_pounce_tests_a_creature_only_once_per_turn():
    """"A creature is tested once per turn."""
    engine, tiger, foe, events = _tiger_strike(20)
    assert tiger.turn_flags[f"pounce_tested:{foe.entity_id}"]
    tiger.action_available = True  # a second hit the same turn (an extra attack)
    again = _do(engine, tiger, "Painted Strike")
    assert not lane1._payloads(again, "SAVE_ROLLED")


def test_tiger_pounce_save_is_the_summoners_cultivation_save_dc():
    engine, tiger, foe, events = _tiger_strike(20)
    assert lane1._payloads(events, "SAVE_ROLLED")[0]["dc"] == 50  # the sheet's technique save DC, not a number of the tiger's own


# ------------------------------------------------------------------------------------------------- Serpent


def _serpent_grip(foes=(FOE1,)):
    engine = _fight(dc=50, foes=foes)
    foe = engine.state.actors[FOE1]
    serpent = _call(engine, "serpent")
    foe.position = Position(x=3, y=7)  # 10 ft: the Serpent's reach
    events = _do(engine, serpent, "Painted Strike", target=FOE1)
    return engine, serpent, foe, events


def test_serpent_coiling_stroke_grapples_until_the_summoners_next_turn():
    """"After hitting a Large or smaller creature, it makes a Strength saving throw.  Failed Save: Grappled by the Serpent until
    the start of your next turn."""
    engine, serpent, foe, events = _serpent_grip()
    assert [p["success"] for p in lane1._payloads(events, "SAVE_ROLLED")] == [False]
    grip = _held(foe, "condition:typed.grappled")
    assert len(grip) == 1 and grip[0].source_actor_id == serpent.entity_id
    assert painting_forms.grappling(engine, serpent) == [foe]
    me = engine.state.actors[ME]
    engine.end_turn()  # the foe's turn: still held
    assert _held(foe, "condition:typed.grappled")
    engine.end_turn()  # back to the summoner: the start of its turn ends the grip
    assert engine.state.current_actor_id == me.entity_id and not _held(foe, "condition:typed.grappled")


def test_a_saved_strength_save_leaves_the_target_free():
    engine = _fight(dc=-40)
    foe = engine.state.actors[FOE1]
    serpent = _call(engine, "serpent")
    foe.position = Position(x=3, y=7)
    events = _do(engine, serpent, "Painted Strike", target=FOE1)
    assert [p["success"] for p in lane1._payloads(events, "SAVE_ROLLED")] == [True] and not _held(foe, "condition:typed.grappled")


def test_the_gripped_creature_repeats_the_save_with_its_action():
    """"The target may use its Action to repeat the saving throw, ending the Grapple on a success."  It is a Strength saving
    throw against the Cultivation Save DC, not the Athletics/Acrobatics check an ordinary grapple asks."""
    engine, serpent, foe, _ = _serpent_grip()
    grip = _held(foe, "condition:typed.grappled")[0]
    grip.data["escape_dc"] = -40  # a save that cannot fail
    events = _do(engine, foe, "Escape grapple")
    assert [p["success"] for p in lane1._payloads(events, "SAVE_ROLLED")] == [True] and not lane1._payloads(events, "CHECK_ROLLED")
    assert not _held(foe, "condition:typed.grappled")


def test_while_grappling_the_serpent_cannot_strike_another_target():
    engine, serpent, foe, _ = _serpent_grip(foes=(FOE1, FOE2))
    other = engine.state.actors[FOE2]
    other.position = Position(x=4, y=5)
    lane1._ready(engine)
    engine.state.current_actor_id = serpent.entity_id
    serpent.action_available = True
    targets = {t for c in engine.legal_candidates() if c.display_name == "Painted Strike" for t in c.target_ids}
    assert targets == {FOE1}


# ------------------------------------------------------------------------------------------------ Tortoise


def test_tortoise_shell_ward_takes_the_proficiency_bonus_off_and_gives_half_cover():
    """"Shell Ward: when an ally within 5 feet takes damage, the Tortoise reduces it by your Proficiency Bonus and the ally
    has Half Cover until the start of its next turn."  (Half Cover counts against ranged attacks only on this table.)"""
    from combat import typed_reactions

    engine = _fight()
    me = engine.state.actors[ME]
    _do(engine, me, "Living Painting: Tortoise")
    tortoise = _form(engine, "tortoise")
    tortoise.position = Position(x=me.position.x, y=me.position.y + 1)
    foe = engine.state.actors[FOE1]
    assert typed_reactions._offer_ally_damaged(engine, me, foe, 20, 0, FOE1) == 16  # PB 4
    assert not tortoise.reaction_available
    ward = _held(me, "condition:typed.shell_ward")
    assert len(ward) == 1 and ward[0].data["cover"] == 2
    assert painting_forms.shell_ward_cover_bonus(engine, foe, me) == 2
    assert painting_forms.shell_ward_cover_bonus(engine, foe, foe) is None
    assert engine._cover_bonus_actor_to_actor(foe, me) >= 2


# --------------------------------------------------------------------------------------------------- Crane


def test_crane_painted_passage_carries_an_ally_up_to_twenty_feet():
    engine = _fight()
    me = engine.state.actors[ME]
    _do(engine, me, "Living Painting: Crane")
    crane = _form(engine, "crane")
    crane.position = Position(x=me.position.x, y=me.position.y - 1)
    _do(engine, me, "Command Living Painting")
    engine.end_turn()
    assert engine.state.current_actor_id == crane.entity_id
    assert any(n.startswith("Painted Passage") for n in _names(engine, crane))
    start = me.position
    events = _do(engine, crane, "Painted Passage", destination=(3, 6 + 4))  # 20 ft south of the summoner
    assert (me.position.x, me.position.y) == (3, 10) and engine.grid.distance_ft(start, me.position) == 20
    assert any(e.event_type == "MOVEMENT_COMMITTED" and e.actor_id == ME for e in events)
    assert not any(e.event_type == "OPPORTUNITY_ATTACK" for e in events)


def test_crane_painted_passage_cannot_go_farther_than_twenty_feet():
    engine = _fight()
    me = engine.state.actors[ME]
    _do(engine, me, "Living Painting: Crane")
    crane = _form(engine, "crane")
    crane.position = Position(x=me.position.x, y=me.position.y - 1)
    _do(engine, me, "Command Living Painting")
    engine.end_turn()
    legal = {(c.destination.x, c.destination.y) for c in engine.legal_candidates() if c.display_name.startswith("Painted Passage")}
    assert (3, 10) in legal and (3, 11) not in legal


# ------------------------------------------------------------------------------ choose-N menu: World of Dreams


def _zone_rules(actor):
    """The rules of the area effects standing on ``actor``: {condition data name: rule}."""
    return {c.data["name"]: c.data["rule"] for c in actor.conditions.values() if c.condition_id == "condition:typed.zone_effect"}


def test_world_of_dreams_is_one_ability_with_ten_options_and_three_chosen():
    """"Choose three effects" (Dreamscape talent, World of Dreams): the ability was typed with no menu, so it either did none of the
    ten options or (had it been typed as effects) all of them."""
    engine = _fight(WORLD_OF_DREAMS)
    me = engine.state.actors[ME]
    names = _names(engine, me)
    assert len([n for n in names if n.startswith("Choose World of Dreams: ")]) == 10
    assert sum(1 for a in engine.action_catalog.values() if a.display_name.startswith("World of Dreams")) == 1  # one cast, not one per option
    assert menus.picks(engine, me, "world_of_dreams") == [WOD_PSYCHIC, WOD_REACTIONS, WOD_DIFFICULT]  # nothing chosen yet: the defaults
    assert all(a.parameters.get("player_only") for a in engine.action_catalog.values() if a.display_name.startswith("Choose World of Dreams: "))


def test_choosing_an_option_replaces_the_one_chosen_longest_ago_and_shows_on_the_actor():
    engine = _fight(WORLD_OF_DREAMS)
    me = engine.state.actors[ME]
    events = _do(engine, me, f"Choose World of Dreams: {WOD_WIS}")
    assert menus.picks(engine, me, "world_of_dreams") == [WOD_REACTIONS, WOD_DIFFICULT, WOD_WIS]  # the psychic default, oldest, is dropped
    assert any(e.event_type == "CONDITION_APPLIED" for e in events)
    _do(engine, me, f"Choose World of Dreams: {WOD_PSYCHIC}")
    assert menus.picks(engine, me, "world_of_dreams") == [WOD_DIFFICULT, WOD_WIS, WOD_PSYCHIC]
    _do(engine, me, f"Choose World of Dreams: {WOD_WIS}")  # already chosen: no change
    assert menus.picks(engine, me, "world_of_dreams") == [WOD_DIFFICULT, WOD_WIS, WOD_PSYCHIC]
    assert len(_held(me, "condition:typed.menu")) == 1  # one marker, replaced each time
    assert "World of Dreams" in next(iter(_held(me, "condition:typed.menu"))).data["label"]


def test_world_of_dreams_area_carries_the_chosen_options_only():
    engine = _fight(WORLD_OF_DREAMS)
    me, foe = engine.state.actors[ME], engine.state.actors[FOE1]
    events = _do(engine, me, "World of Dreams", destination=(8, 6))
    zone = next(iter(engine.state.zones.values()))
    assert zone.trigger_profile["difficult"] == "hostile"  # "Enemies treat the area as difficult terrain"
    assert set(_zone_rules(foe)) == {"World of Dreams: no Reactions"}  # not the Wisdom option: it was not chosen
    assert [t["name"] for t in zone.trigger_profile["triggers"]] == ["World of Dreams"]
    line = next(e.payload["rider"] for e in events if e.event_type == "GM_RIDER" and "Choose three effects" in e.payload["rider"])
    assert WOD_REACTIONS in line and WOD_WIS not in line


def test_world_of_dreams_wisdom_option_is_a_disadvantage_on_saves_inside():
    engine = _fight(WORLD_OF_DREAMS)
    me, foe = engine.state.actors[ME], engine.state.actors[FOE1]
    _do(engine, me, f"Choose World of Dreams: {WOD_WIS}")
    _do(engine, me, "World of Dreams", destination=(8, 6))
    zone = next(iter(engine.state.zones.values()))
    assert _zone_rules(foe)["World of Dreams: no Reactions"] == {"no_reactions": True}
    assert {"save_mode": {"WIS": "DISADVANTAGE"}} in _zone_rules(foe).values()
    assert zone.trigger_profile["difficult"] == "hostile"
    assert zone.trigger_profile["triggers"] == []  # the psychic option is now the one dropped


def test_world_of_dreams_psychic_option_hurts_an_enemy_at_the_start_of_its_turn():
    """"Enemies that enter or start their turn inside take 3d8 Psychic damage (Wisdom save)": a failed save is the full 3d8."""
    engine = _fight(WORLD_OF_DREAMS, dc=50)
    me, foe = engine.state.actors[ME], engine.state.actors[FOE1]
    _do(engine, me, "World of Dreams", destination=(8, 6))
    hp = foe.current_hp
    engine.end_turn()
    assert engine.state.current_actor_id == FOE1
    hurt = [e for e in engine.events if e.event_type == "DAMAGE_COMMITTED" and e.payload.get("damage_type") == "PSYCHIC"]
    assert hurt and foe.current_hp == hp - hurt[-1].payload["hp_damage"] and foe.current_hp < hp


def test_world_of_dreams_without_the_psychic_option_does_not_hurt():
    engine = _fight(WORLD_OF_DREAMS, dc=50)
    me, foe = engine.state.actors[ME], engine.state.actors[FOE1]
    _do(engine, me, f"Choose World of Dreams: {WOD_WIS}")  # drops the psychic default
    _do(engine, me, "World of Dreams", destination=(8, 6))
    hp = foe.current_hp
    engine.end_turn()
    assert foe.current_hp == hp


def test_menu_condition_has_hover_text():
    from combat import condition_text

    assert "chosen" in condition_text.all_conditions()["menu"]["reading"]


# ------------------------------------------------------------------------------ the other choose-N abilities
# Severing Fate ("Failed Save: Choose three"), One Sword, Ten Thousand Cuts ("Then choose two"), Strip the Battlefield Bare
# ("Choose two different consequences") and The Fist That Taught Heaven to Flinch ("Choose three consequences"): typed with
# every consequence at once (or none), and Ten Thousand Cuts as two "choose one" actions that hit for nothing.

SEVERING_FATE, TEN_THOUSAND_CUTS = "TAL_SWORD_SEVERING_FATE", "TAL_SWORD_ONE_SWORD_TEN_THOUSAND_CUTS"
STRIP_BARE, FIST_FLINCH = "TAL_SCOUNDREL_STRIP_THE_BATTLEFIELD_BARE", "tianxia.talent.iron_fist.the_fist_that_taught_heaven_to_flinch"


def _strong_fight(mid, *, dc, foes=(FOE1,), near=True):
    """A fight whose foes have enough hit points to survive the ability; the first foe stands next to the caster."""
    engine = _fight(mid, dc=dc, foes=foes)
    for f in foes:
        foe = engine.state.actors[f]
        foe.maximum_hp = 900
        foe.current_hp = 900
    if near:
        engine.state.actors[FOE1].position = Position(x=4, y=6)
    return engine


def _held_ids(actor):
    return {c.condition_id.removeprefix("condition:typed.") for c in actor.conditions.values()}


def _fields(actor):
    return {m.target_field for m in actor.modifiers.values()}


def _pick(engine, menu, *options):
    me = engine.state.actors[ME]
    for option in options:
        _do(engine, me, f"Choose {menu}: {option}")


def test_severing_fate_failed_save_applies_the_three_chosen_consequences_only():
    """Default picks: Stunned, Reactions, Speed 0 -- not "cannot regain HP" (which is not one of the three chosen)."""
    engine = _strong_fight(SEVERING_FATE, dc=50)
    me, foe = engine.state.actors[ME], engine.state.actors[FOE1]
    assert len([n for n in _names(engine, me) if n.startswith("Choose Severing Fate: ")]) == 7
    _do(engine, me, "Severing Fate", target=FOE1)
    assert {"stunned", "reaction_denied"} <= _held_ids(foe)
    assert "speed_ft" in _fields(foe)  # Speed 0 (Stunned alone would also stop it)
    assert "healing_reduction" not in _fields(foe)
    assert foe.current_hp < 900


def test_severing_fate_choosing_cannot_regain_hp_replaces_the_oldest_pick():
    engine = _strong_fight(SEVERING_FATE, dc=50)
    me, foe = engine.state.actors[ME], engine.state.actors[FOE1]
    _pick(engine, "Severing Fate", "Cannot regain HP until the end of your next turn")  # drops the oldest: Stunned
    _do(engine, me, "Severing Fate", target=FOE1)
    assert "stunned" not in _held_ids(foe) and "reaction_denied" in _held_ids(foe)
    assert {"healing_reduction", "speed_ft"} <= _fields(foe)


def test_severing_fate_successful_save_leaves_one_consequence():
    """"Successful Save: Choose one.": the first of the picks in printed order (here Stunned)."""
    engine = _strong_fight(SEVERING_FATE, dc=1)
    me, foe = engine.state.actors[ME], engine.state.actors[FOE1]
    _do(engine, me, "Severing Fate", target=FOE1)
    assert _held_ids(foe) == {"stunned"} and not _fields(foe)  # not Speed 0, not the Reactions


def test_ten_thousand_cuts_is_one_action_that_hits_and_chooses_two():
    """It was two "choose one" actions with no attack in them (the parsed "Choose two"/"choose one" read as forms)."""
    engine = _strong_fight(TEN_THOUSAND_CUTS, dc=50)
    me, foe = engine.state.actors[ME], engine.state.actors[FOE1]
    assert [n for n in _names(engine, me) if n.startswith("One Sword")] == ["One Sword, Ten Thousand Cuts"]
    _do(engine, me, "One Sword, Ten Thousand Cuts", target=FOE1)
    assert foe.current_hp < 900
    assert {"reaction_denied", "stunned"} <= _held_ids(foe)  # the default two: Reactions, and the Constitution save (failed)
    assert "healing_reduction" not in _fields(foe) and "speed_ft" not in _fields(foe)


def test_ten_thousand_cuts_a_miss_deals_half_damage_and_leaves_one_choice():
    engine = _strong_fight(TEN_THOUSAND_CUTS, dc=50)
    me, foe = engine.state.actors[ME], engine.state.actors[FOE1]
    foe.armor_class = 99
    _do(engine, me, "One Sword, Ten Thousand Cuts", target=FOE1)
    hurt = [e.payload["hp_damage"] for e in engine.events if e.event_type == "DAMAGE_COMMITTED"]
    assert hurt and 900 - foe.current_hp == sum(hurt) and 5 <= 900 - foe.current_hp <= 50  # half of 10d10, not 10d10 (10-100)
    assert _held_ids(foe) == {"reaction_denied"}  # the first pick in printed order


def test_strip_the_battlefield_bare_two_chosen_consequences_for_every_foe_in_the_area():
    engine = _strong_fight(STRIP_BARE, dc=50, foes=(FOE1, FOE2), near=False)
    me = engine.state.actors[ME]
    _pick(engine, "Strip the Battlefield Bare", "Prevent it from taking Reactions until the end of your next turn")  # drops "Prone"
    _do(engine, me, "STRIP THE BATTLEFIELD BARE")
    for f in (FOE1, FOE2):
        foe = engine.state.actors[f]
        assert _held_ids(foe) == {"reaction_denied"} and "speed_ft" in _fields(foe) and "prone" not in _held_ids(foe)


def test_strip_the_battlefield_bare_move_option_shoves_the_creature_twenty_feet():
    engine = _strong_fight(STRIP_BARE, dc=50, near=False)
    me, foe = engine.state.actors[ME], engine.state.actors[FOE1]
    _pick(engine, "Strip the Battlefield Bare", "Move it up to 20 feet along the ground if it is Huge or smaller")
    x = foe.position.x
    _do(engine, me, "STRIP THE BATTLEFIELD BARE")
    assert abs(foe.position.x - x) == 4  # 20 feet, away from the caster


def test_strip_the_battlefield_bare_successful_save_skips_stealing_and_suppressing():
    """"Successful Save: Choose one consequence other than stealing worn equipment or suppressing a temporary effect."""
    engine = _strong_fight(STRIP_BARE, dc=1, near=False)
    me, foe = engine.state.actors[ME], engine.state.actors[FOE1]
    _pick(engine, "Strip the Battlefield Bare", "Steal one accessible held or worn object", "Reduce each of its Speeds to 0 until the end of your next turn")
    _do(engine, me, "STRIP THE BATTLEFIELD BARE")
    assert _held_ids(foe) == set() and _fields(foe) == {"speed_ft"}  # picks are [Prone->dropped, Speed 0, Steal]: Speed 0 stands
    engine2 = _strong_fight(STRIP_BARE, dc=50, near=False)
    _pick(engine2, "Strip the Battlefield Bare", "Steal one accessible held or worn object")
    events = _do(engine2, engine2.state.actors[ME], "STRIP THE BATTLEFIELD BARE")
    assert any(e.event_type == "GM_RIDER" and "Steal one accessible held or worn object" in e.payload["rider"] for e in events)  # said as a GM line


def test_fist_that_taught_heaven_to_flinch_strikes_and_chooses_three_consequences():
    engine = _strong_fight(FIST_FLINCH, dc=50)
    me, foe = engine.state.actors[ME], engine.state.actors[FOE1]
    assert len([n for n in _names(engine, me) if n.startswith("Choose The Fist That Taught Heaven to Flinch: ")]) == 8
    _do(engine, me, "The Fist That Taught Heaven to Flinch", target=FOE1)
    assert foe.current_hp < 900 - 12  # 12d10 or more
    assert {"stunned", "reaction_denied"} <= _held_ids(foe) and "speed_ft" in _fields(foe)
    assert "prone" not in _held_ids(foe)


def test_fist_that_taught_heaven_to_flinch_successful_save_is_never_stunned():
    engine = _strong_fight(FIST_FLINCH, dc=1)
    me, foe = engine.state.actors[ME], engine.state.actors[FOE1]
    _do(engine, me, "The Fist That Taught Heaven to Flinch", target=FOE1)
    assert "stunned" not in _held_ids(foe) and "reaction_denied" in _held_ids(foe)  # "other than Stunned": the next pick in printed order
    assert "speed_ft" not in _fields(foe)  # only one consequence


# ------------------------------------------------------------------------------------- chosen afflictions that last together
# Symptom Cascade, Five-Venom Formula, Nine-Bell Meridian Palm: "Choose two symptoms ... repeats the saving throw, ending both on
# a success" -- the picks are ONE condition (combat/ext/afflictions.py) so one repeat saving throw ends them (or one of them).

SYMPTOM_CASCADE, FIVE_VENOM = "tianxia.talent.disease.symptom_cascade", "tianxia.talent.poison.five_venom_formula"
NINE_BELL, FIRST_DAWN = "TAL_IRON_FIST_NINE_BELL_MERIDIAN_PALM", "tianxia.talent.radiance.first_dawn_before_falsehood"


def _affliction(actor):
    found = [c for c in actor.conditions.values() if c.condition_id == "condition:typed.affliction"]
    return found[0] if found else None


def _dose_marked_fight(mid, dc):
    from combat.typed_executor import mark_condition_id

    engine = _strong_fight(mid, dc=dc)
    engine._apply_condition(engine.state.actors[FOE1], mark_condition_id("Dose Mark", ME), "test", ME, expires_on="UNTIL_REMOVED")
    return engine


def test_symptom_cascade_failed_save_puts_two_symptoms_on_one_condition_until_concentration_ends():
    engine = _strong_fight(SYMPTOM_CASCADE, dc=50)
    me, foe = engine.state.actors[ME], engine.state.actors[FOE1]
    assert len([n for n in _names(engine, me) if n.startswith("Choose Symptom Cascade: ")]) == 9
    _pick(engine, "Symptom Cascade", "Coughing", "Fatigue")  # the two chosen longest ago (Fever, Coughing) -> Coughing stays, Fatigue joins
    _do(engine, me, "Symptom Cascade", target=FOE1)
    held = [c for c in foe.conditions.values() if c.condition_id == "condition:typed.affliction"]
    assert len(held) == 1 and held[0].data["picks"] == ["Coughing", "Fatigue"]
    assert held[0].expires_on == "CONCENTRATION_END" and held[0].data["repeat_save"]["ability"] == "CON"
    assert not foe.reaction_available  # Coughing
    assert engine._effective_speed(foe) == 10  # Fatigue: -20 ft from its 30


def test_symptom_cascade_repeat_save_ends_both_symptoms_at_once():
    engine = _strong_fight(SYMPTOM_CASCADE, dc=50)
    me, foe = engine.state.actors[ME], engine.state.actors[FOE1]
    _do(engine, me, "Symptom Cascade", target=FOE1)
    condition = _affliction(foe)
    engine.end_turn()
    assert engine.state.current_actor_id == FOE1 and _affliction(foe) is condition  # a failed repeat save (DC 50) leaves it
    condition.data["repeat_save"]["dc"] = -40  # a repeat save that cannot fail
    engine.end_turn()
    assert _affliction(foe) is None and "reaction_denied" not in _held_ids(foe)  # both symptoms gone together


def test_symptom_cascade_fever_burns_at_the_start_of_each_of_its_turns():
    engine = _strong_fight(SYMPTOM_CASCADE, dc=50)
    me, foe = engine.state.actors[ME], engine.state.actors[FOE1]
    _do(engine, me, "Symptom Cascade", target=FOE1)
    before = foe.current_hp
    engine.end_turn()  # the foe's turn starts: Fever's 2d8
    assert engine.state.current_actor_id == FOE1 and 2 <= before - foe.current_hp <= 16


def test_symptom_cascade_rot_reduces_healing_by_the_proficiency_bonus():
    from combat import typed_executor as te

    engine = _strong_fight(SYMPTOM_CASCADE, dc=50)
    me, foe = engine.state.actors[ME], engine.state.actors[FOE1]
    _pick(engine, "Symptom Cascade", "Rot")
    _do(engine, me, "Symptom Cascade", target=FOE1)
    pb = _affliction(foe).data["pb"]
    assert pb > 0 and te._reduced_healing(engine, foe, 10) == 10 - pb


def test_symptom_cascade_successful_save_leaves_one_symptom_until_the_casters_next_turn():
    engine = _strong_fight(SYMPTOM_CASCADE, dc=1)
    me, foe = engine.state.actors[ME], engine.state.actors[FOE1]
    _do(engine, me, "Symptom Cascade", target=FOE1)
    condition = _affliction(foe)
    assert condition is not None and len(condition.data["picks"]) == 1 and "repeat_save" not in condition.data
    assert condition.data["picks"] == ["Fever"] and condition.expires_on == "START_OF_SOURCE_NEXT_TURN" and foe.reaction_available  # Coughing is not the one left


def test_five_venom_formula_needs_a_dose_mark_then_puts_serpent_and_scorpion_on_one_condition():
    engine = _strong_fight(FIVE_VENOM, dc=50)
    me, foe = engine.state.actors[ME], engine.state.actors[FOE1]
    assert "Five-Venom Formula" not in _names(engine, me)  # the printed "Dose Mark or Toxin Burden from you" (combat/ext/life_poison.py)
    engine = _dose_marked_fight(FIVE_VENOM, 50)
    me, foe = engine.state.actors[ME], engine.state.actors[FOE1]
    _do(engine, me, "Five-Venom Formula", target=FOE1)
    condition = _affliction(foe)
    assert condition.data["picks"] == ["Serpent", "Scorpion"] and not foe.reaction_available
    before = foe.current_hp
    engine.end_turn()
    assert 2 <= before - foe.current_hp <= 16  # Serpent's 2d8 Poison at the start of its turn


def test_five_venom_formula_spider_and_corrosive_slime_slow_it_and_soften_its_armour():
    engine = _dose_marked_fight(FIVE_VENOM, 50)
    me, foe = engine.state.actors[ME], engine.state.actors[FOE1]
    ac = engine._ac_modifier(foe)
    _pick(engine, "Five-Venom Formula", "Spider", "Corrosive Slime")
    _do(engine, me, "Five-Venom Formula", target=FOE1)
    assert engine._effective_speed(foe) == 10 and engine._ac_modifier(foe) == ac - 1


def test_five_venom_formula_successful_save_leaves_the_first_venom_effect_only():
    engine = _dose_marked_fight(FIVE_VENOM, 1)
    me, foe = engine.state.actors[ME], engine.state.actors[FOE1]
    _do(engine, me, "Five-Venom Formula", target=FOE1)
    condition = _affliction(foe)
    assert condition.data["picks"] == ["Serpent"] and foe.reaction_available and "repeat_save" not in condition.data


def test_nine_bell_meridian_palm_hits_then_seals_three_things_for_a_minute():
    """Merge 6592dcfa uses the attack DC; force CON failure rather than sheet DC."""
    engine = _strong_fight(NINE_BELL, dc=50)
    me, foe = engine.state.actors[ME], engine.state.actors[FOE1]
    foe.saving_throws["CON"] = -100
    assert len([n for n in _names(engine, me) if n.startswith("Choose Nine-Bell Meridian Palm: ")]) == 4
    events = _do(engine, me, "Nine-Bell Meridian Palm", target=FOE1)
    save = next(e for e in events if e.event_type == "SAVE_ROLLED" and e.actor_id == FOE1)
    assert save.payload["dc"] == 14 and not save.payload["success"]
    assert foe.current_hp < 900 - 6  # the strike and 6d10
    seals = _affliction(foe)
    assert seals.data["picks"] == ["Leg Seal", "Breath Seal", "Voice Seal"] and "repeat_one" in seals.data
    assert seals.expires_on == "START_OF_SLOT_AT:11:0"  # ten rounds: one minute
    assert me.resources["resource:core.martial_focus"] == 0
    assert engine._effective_speed(foe) == 15 and not foe.reaction_available and "silenced" in _held_ids(foe)


def test_nine_bell_meridian_palm_repeat_save_ends_one_seal_and_keeps_the_rest():
    """Use actual failed/successful CON saves at merge 6592dcfa's attack DC."""
    engine = _strong_fight(NINE_BELL, dc=50)
    me, foe = engine.state.actors[ME], engine.state.actors[FOE1]
    foe.saving_throws["CON"] = -100
    _do(engine, me, "Nine-Bell Meridian Palm", target=FOE1)
    initial_dc = _affliction(foe).data["repeat_one"]["dc"]
    assert initial_dc == 14
    foe.saving_throws["CON"] = 100
    before = len(engine.events)
    engine.end_turn()
    engine.end_turn()  # the foe's turn ends: the repeat save succeeds
    save = next(e for e in engine.events[before:] if e.event_type == "SAVE_ROLLED" and e.actor_id == FOE1)
    assert save.payload["dc"] == initial_dc and save.payload["success"]
    seals = _affliction(foe)
    assert seals.data["picks"] == ["Breath Seal", "Voice Seal"] and engine._effective_speed(foe) == 30  # Leg Seal is gone
    assert "silenced" in _held_ids(foe)


def test_nine_bell_meridian_palm_successful_save_leaves_one_seal_until_the_end_of_its_next_turn():
    """Force success independently of the sheet DC after merge 6592dcfa."""
    engine = _strong_fight(NINE_BELL, dc=1)
    me, foe = engine.state.actors[ME], engine.state.actors[FOE1]
    foe.saving_throws["CON"] = 100
    events = _do(engine, me, "Nine-Bell Meridian Palm", target=FOE1)
    save = next(e for e in events if e.event_type == "SAVE_ROLLED" and e.actor_id == FOE1)
    assert save.payload["dc"] == 14 and save.payload["success"]
    assert _affliction(foe).data["picks"] == ["Leg Seal"] and engine._effective_speed(foe) == 15 and foe.reaction_available
    assert _affliction(foe).expires_on == f"END_OF_TURN_AT:{FOE1}:1"
    engine.end_turn()
    assert _affliction(foe) is not None  # it lasts through the target's turn
    engine.end_turn()
    assert _affliction(foe) is None and engine._effective_speed(foe) == 30


def test_first_dawn_before_falsehood_failed_save_is_damage_and_two_more_of_the_chosen_consequences():
    engine = _strong_fight(FIRST_DAWN, dc=50, near=False)
    me, foe = engine.state.actors[ME], engine.state.actors[FOE1]
    assert len([n for n in _names(engine, me) if n.startswith("Choose First Dawn Before Falsehood: ")]) == 8
    _do(engine, me, "First Dawn Before Falsehood", target=ME)
    assert foe.current_hp <= 900 - 8  # 8d10 Radiant
    assert {"blinded", "reaction_denied"} <= _held_ids(foe)


def test_first_dawn_before_falsehood_gives_the_caster_temporary_hit_points_and_a_save_still_costs_one_consequence():
    engine = _strong_fight(FIRST_DAWN, dc=1, near=False)
    me, foe = engine.state.actors[ME], engine.state.actors[FOE1]
    _do(engine, me, "First Dawn Before Falsehood", target=ME)
    assert me.temporary_hp > 0
    assert foe.current_hp < 900 and not (_held_ids(foe) & {"blinded", "reaction_denied"})  # the one consequence a success leaves: the damage


def test_affliction_condition_has_hover_text():
    from combat import condition_text

    assert "last together" in condition_text.all_conditions()["affliction"]["reading"]


# ------------------------------------------------------------------------------- Samsara Wheel: Echoes of Former Lives

from combat.ext import mantles  # noqa: E402
from combat.factory_compiler import compile_character  # noqa: E402

JIAN = {"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.jian", "name": "Jian", "quantity": 1}]}}
QI = "resource:core.qi"


def _samsara(*, weapon=True, ally=False):
    """A Samsara Wheel Cultivator with a jian, a foe next to her (900 HP, AC -50: every swing hits) and, optionally, a second friendly creature."""
    sheet = lane1._sheet(mantles.FEATURE, dc=16)
    if weapon:
        sheet["equipment"] = [JIAN]
    engine = _fight(bundle=compile_character(sheet, actor_id=ME), foes=(FOE1, FOE2) if ally else (FOE1,))
    for f in (FOE1, FOE2) if ally else (FOE1,):
        engine.state.actors[f].maximum_hp = engine.state.actors[f].current_hp = 900
    engine.state.actors[FOE1].position = Position(x=4, y=6)
    if ally:
        engine.state.actors[FOE2].team_id = engine.state.actors[ME].team_id
        engine.state.actors[FOE2].position = Position(x=3, y=7)
    engine.state.actors[ME].resources[QI] = 10
    return engine


def _slugged(name):
    return f"Turn the Memory: {name}"


def test_echoes_of_former_lives_is_a_menu_of_eight_mantles_three_known():
    engine = _samsara()
    me = engine.state.actors[ME]
    assert list(mantles.MANTLES) == menus.catalog(engine)[mantles.MENU_ID]["options"] and len(mantles.MANTLES) == 8
    assert mantles.known(engine, me) == list(mantles.MANTLES)[:3]
    # Printed replacement requires a rest/session and meditation, never a combat toggle.
    assert not [n for n in _names(engine, me) if n.startswith("Choose Former-Life Mantles: ")]
    assert mantles.known(engine, me) == list(mantles.MANTLES)[:3]


def test_uncontrolled_engine_defaults_to_first_known_mantle_during_scene_setup():
    engine = _samsara()  # The direct engine has no manual controller; service tests cover the player choice.
    me = engine.state.actors[ME]
    assert mantles.active(me) == ["Warrior of a Fallen Age"] == mantles.known(engine, me)[:1]
    assert "Warrior of a Fallen Age" in [c.data["mantles"][0] for c in me.conditions.values() if c.condition_id == mantles.ACTIVE]
    assert not engine.state.setup_tasks
    events = list(engine.events)
    application = next(i for i, e in enumerate(events) if e.event_type == "CONDITION_APPLIED"
                       and e.payload.get("condition_id") == mantles.ACTIVE)
    assert application < next(i for i, e in enumerate(events) if e.event_type == "FIGHT_SETUP_COMPLETED")


def test_turning_the_memory_is_a_bonus_action_for_one_qi_and_only_to_a_known_other_mantle():
    engine = _samsara()
    me = engine.state.actors[ME]
    mantles._set_active(engine, me, ["Warrior of a Fallen Age"], "test")
    names = _names(engine, me)
    assert _slugged("Wandering Sword-Saint") in names and _slugged("Forgotten Scholar") in names
    assert _slugged("Warrior of a Fallen Age") not in names  # it is the active one
    assert _slugged("Court Diplomat") not in names  # not one of the three known
    qi = me.resources[QI]
    _do(engine, me, _slugged("Forgotten Scholar"))
    assert mantles.active(me) == ["Forgotten Scholar"] and me.resources[QI] == qi - 1
    assert not me.bonus_action_available


def test_wandering_sword_saint_adds_ten_feet_and_the_arrival_step_does_not_provoke():
    engine = _samsara()
    me = engine.state.actors[ME]
    mantles._set_active(engine, me, ["Warrior of a Fallen Age"], "test")
    speed, moving = engine._effective_speed(me), me.movement_remaining_ft
    _do(engine, me, _slugged("Wandering Sword-Saint"))
    assert engine._effective_speed(me) == speed + 10 and me.movement_remaining_ft == moving + 10 + 10  # the Speed, and the Arrival move
    assert me.turn_flags.get("oa_free_ft") == 10


def test_opportunity_attacks_against_the_wandering_sword_saint_have_disadvantage():
    from combat import ext

    class Ctx:  # the hook reads only the attacker and the engine's record of the Opportunity Attack being made
        engine = _samsara()
        actor = None

    ctx = Ctx()
    me, foe = ctx.engine.state.actors[ME], ctx.engine.state.actors[FOE1]
    ctx.actor = foe
    mantles._set_active(ctx.engine, me, ["Wandering Sword-Saint"], "test")
    ctx.engine._typed_oa_attacker = FOE1
    assert "DISADVANTAGE" in ext.run("attack_mode", ctx, me)
    ctx.engine._typed_oa_attacker = None
    assert "DISADVANTAGE" not in ext.run("attack_mode", ctx, me)  # an ordinary attack is unchanged
    mantles._set_active(ctx.engine, me, ["Forgotten Scholar"], "test")
    ctx.engine._typed_oa_attacker = FOE1
    assert "DISADVANTAGE" not in ext.run("attack_mode", ctx, me)


def test_court_diplomat_has_advantage_on_saves_against_charmed_only():
    from combat import ext

    engine = _samsara()
    me = engine.state.actors[ME]
    mantles._set_active(engine, me, ["Court Diplomat"], "test")
    assert any("ADVANTAGE" in extra.get("modes", ()) for extra in ext.run("save", None, me, "WIS", {"charmed"}))
    assert not any("ADVANTAGE" in extra.get("modes", ()) for extra in ext.run("save", None, me, "WIS", {"frightened"}))
    mantles._set_active(engine, me, ["Forgotten Scholar"], "test")
    assert not any("ADVANTAGE" in extra.get("modes", ()) for extra in ext.run("save", None, me, "WIS", {"charmed"}))


def test_road_born_wanderer_ignores_difficult_terrain_and_stands_up_free_on_arrival():
    from combat.typed_executor import condition_rules

    engine = _samsara()
    me = engine.state.actors[ME]
    engine._apply_condition(me, "condition:typed.prone", "test", FOE1, expires_on="UNTIL_REMOVED", data={"label": "Prone"})
    mantles._set_active(engine, me, ["Warrior of a Fallen Age"], "test")
    menus.pick(engine, me, mantles.MENU_ID, "Road-Born Wanderer", "test:character-preparation")
    assert not any(row.get("ignore_difficult") for row in condition_rules(me))
    _do(engine, me, _slugged("Road-Born Wanderer"))
    assert any(row.get("ignore_difficult") for row in condition_rules(me))
    assert "prone" not in _held_ids(me)  # "Stand from Prone" for free
    assert me.turn_flags.get("oa_free_ft") == 5


def test_battlefield_physician_arrival_gives_a_creature_within_reach_temporary_hit_points_equal_to_pb():
    engine = _samsara(ally=True)
    me, friend = engine.state.actors[ME], engine.state.actors[FOE2]
    mantles._set_active(engine, me, ["Warrior of a Fallen Age"], "test")
    menus.pick(engine, me, mantles.MENU_ID, "Battlefield Physician", "test:character-preparation")
    _do(engine, me, _slugged("Battlefield Physician"), target=FOE2)
    assert friend.temporary_hp == 4 and me.temporary_hp == 0  # Proficiency Bonus 4 on the sheet


def _committed(events):
    return [(e.payload["hp_damage"], e.payload["damage_type"]) for e in events if e.event_type == "DAMAGE_COMMITTED"]


def test_warrior_of_a_fallen_age_adds_pb_to_one_weapon_hit_each_turn():
    engine = _samsara()
    me, foe = engine.state.actors[ME], engine.state.actors[FOE1]
    mantles._set_active(engine, me, ["Warrior of a Fallen Age"], "test")
    first = _do(engine, me, "Jian (Straight Sword) attack", target=FOE1)
    dealt = _committed(first)
    assert len(dealt) == 2 and dealt[1] == (4, "PIERCING")  # the jian's own hit, then Proficiency Bonus 4 more of the weapon's type
    assert me.turn_flags.get("mantle_warrior") is True
    lane1._ready(engine)
    second = _do(engine, me, "Jian (Straight Sword) attack", target=FOE1)
    assert len(_committed(second)) == 1  # once per turn: the second hit is the jian's alone


def test_a_weapon_hit_with_no_mantle_adds_nothing():
    engine = _samsara()
    me = engine.state.actors[ME]
    mantles._set_active(engine, me, [], "test")
    dealt = _committed(_do(engine, me, "Jian (Straight Sword) attack", target=FOE1))
    assert len(dealt) == 1 and not me.turn_flags.get("mantle_warrior") and not me.turn_flags.get("mantle_saint")


def test_wandering_sword_saint_steps_five_feet_free_after_a_weapon_hit_once_a_turn():
    engine = _samsara()
    me = engine.state.actors[ME]
    mantles._set_active(engine, me, ["Wandering Sword-Saint"], "test")
    _do(engine, me, "Jian (Straight Sword) attack", target=FOE1)
    assert me.turn_flags.get("mantle_saint") is True and me.turn_flags.get("oa_free_ft") == 5
    before = me.movement_remaining_ft
    lane1._ready(engine)
    _do(engine, me, "Jian (Straight Sword) attack", target=FOE1)
    assert me.turn_flags.get("oa_free_ft") == 5 and me.movement_remaining_ft == before  # once per turn


def test_mantle_condition_has_hover_text():
    from combat import condition_text

    assert "Former-Life Mantle" in condition_text.all_conditions()["mantle"]["reading"]


# ------------------------------------------------------------------------------------- per-creature use limits

SOUL_SUNDER, QUIVERING = "TAL_BRUTE_SOUL_SUNDER", "TAL_IRON_FIST_QUIVERING_GATE_STRIKE"
SUNDER_ROW = "Brutal Shove + Soul Sunder"


def _two_foes(mid, dc):
    """Two foes next to the caster; each printed limit is once per creature, so both should be met with it once."""
    engine = _strong_fight(mid, dc=dc, foes=(FOE1, FOE2))
    engine.state.actors[FOE2].position = Position(x=3, y=7)
    return engine


def _offered(engine, prefix):
    engine.state.current_actor_id = ME
    return {t for c in engine.legal_candidates() if c.display_name.startswith(prefix) for t in c.target_ids or ()}


def test_soul_sunder_once_per_creature_not_once_per_fight():
    """"Use Limit: Once per creature per long rest": the compiler read it as one use per fight, so a second foe was never met."""
    engine = _two_foes(SOUL_SUNDER, dc=50)
    me = engine.state.actors[ME]
    assert _offered(engine, SUNDER_ROW) == {FOE1, FOE2}
    _do(engine, me, SUNDER_ROW, target=FOE1)
    lane1._ready(engine)
    assert _offered(engine, SUNDER_ROW) == {FOE2}  # not the creature it was used on, still the other one
    _do(engine, me, SUNDER_ROW, target=FOE2)
    lane1._ready(engine)
    assert _offered(engine, SUNDER_ROW) == set()


def test_soul_sunder_use_counter_is_widened_and_the_ledger_names_the_creatures():
    engine = _two_foes(SOUL_SUNDER, dc=50)
    me = engine.state.actors[ME]
    counter = next(key for key in me.resource_maximums if key.startswith(target_limits.USES) and key.endswith(SOUL_SUNDER))
    assert me.resource_maximums[counter] == target_limits.PER_TARGET_USES and target_limits.is_per_target(me, counter)
    _do(engine, me, SUNDER_ROW, target=FOE1)
    assert target_limits.used_on(me, counter, engine.state.actors[FOE1]) and not target_limits.used_on(me, counter, engine.state.actors[FOE2])
    ledger = _held(me, target_limits.condition_id())
    # The pill is a sentence the player reads, naming the creature, the ability and when it recharges. It used to
    # read "Used on: <ability>: <creature>" and fell back to the ability's code name when no display name was
    # known, which put an internal id in front of a player (mmx45 2026-10-02, owner checklist item 13).
    reason = ledger[0].data["label"] if ledger else ""
    assert len(ledger) == 1, reason
    assert reason.startswith("Already used on ") and engine.state.actors[FOE1].display_name in reason, reason
    assert "comes back after a Long Rest" in reason, reason
    assert "TAL_" not in reason and "resource:" not in reason, f"the reason leaks an internal id: {reason!r}"


def test_a_miss_still_spends_the_use_on_that_creature():
    engine = _two_foes(SOUL_SUNDER, dc=50)
    me = engine.state.actors[ME]
    engine.state.actors[FOE1].armor_class = 90  # the shove misses
    _do(engine, me, SUNDER_ROW, target=FOE1)
    lane1._ready(engine)
    assert _offered(engine, SUNDER_ROW) == {FOE2}


def test_the_plain_once_per_fight_limit_is_unchanged():
    """A limit that names no creature keeps its counter at 1: the widening is for "once per creature" / "once per target" only."""
    import test_cost_alternatives as ca

    sword = ca._bundle(ca.SWORD, ["TAL_SWORD_FATAL_STRIKE", "TAL_SWORD_MERIDIAN_CUTTING_STRIKE"], ca.AXE_KIT, cl=15)
    counters = {row["resource_id"]: (row["initial"], row["maximum"]) for row in sword["actor_template"]["resources"] if row["resource_id"].startswith("resource:uses.")}
    assert counters["resource:uses.TAL_SWORD_FATAL_STRIKE"] == (1, 1)  # "Once per scene"
    assert counters["resource:uses.TAL_SWORD_MERIDIAN_CUTTING_STRIKE"] == (target_limits.PER_TARGET_USES,) * 2  # "Once per creature per short rest"


def test_per_target_limit_reads_the_printed_words():
    for text in ("text:once per creature per long rest", "text:Once per target per scene", "text:once_per_creature_per_short_rest"):
        assert target_limits.per_target_limit({"use_limit": text}), text
    for text in ("text:once per scene", "text:once per long rest", "", None):
        assert not target_limits.per_target_limit({"use_limit": text}), text


def test_target_uses_condition_has_hover_text():
    from combat import condition_text

    assert "once per creature" in condition_text.all_conditions()["target_uses"]["reading"].lower()


# --------------------------------------------------------------------------------------- Quivering Gate Strike


def _quivering(dc):
    engine = _two_foes(QUIVERING, dc=dc)
    return engine, engine.state.actors[ME]


def _refocus(me):
    """The strike expends the Martial Focus; a second one in the same fight needs it back."""
    me.resources["resource:core.martial_focus"] = 1


def _release_targets(engine):
    return _offered(engine, "Release Quivering Gate Mark")


def test_quivering_gate_strike_hits_and_leaves_a_hidden_mark_it_does_not_detonate():
    """Printed: "Make one Unarmed Strike. Hit: normal damage and a hidden quivering mark for 1 minute" -- the typing was an immediate 10d10."""
    engine, me = _quivering(dc=50)
    foe = engine.state.actors[FOE1]
    assert _release_targets(engine) == set()  # nothing to release yet
    events = _do(engine, me, "Quivering Gate Strike", target=FOE1)
    assert any(c.condition_id.startswith("condition:typed.mark.quivering_gate") for c in foe.conditions.values())
    assert foe.current_hp > 800 and not any(e.event_type == "DAMAGE_ROLLED" and "10d10" in str(e.payload) for e in events)
    lane1._ready(engine)
    _refocus(me)
    assert _release_targets(engine) == {FOE1}  # only the creature that bears the mark
    assert _offered(engine, "Quivering Gate Strike") == {FOE2}  # once per creature


def test_release_failed_save_is_ten_d_ten_force_and_stunned_and_ends_the_mark():
    engine, me = _quivering(dc=50)
    foe = engine.state.actors[FOE1]
    _do(engine, me, "Quivering Gate Strike", target=FOE1)
    lane1._ready(engine)
    before = foe.current_hp
    events = _do(engine, me, "Release Quivering Gate Mark", target=FOE1)
    assert any(e.event_type == "DAMAGE_ROLLED" and "10d10" in e.payload["expression"] for e in events)
    assert foe.current_hp < before - 9 and "stunned" in _held_ids(foe)
    assert not any(c.condition_id.startswith("condition:typed.mark.quivering_gate") for c in foe.conditions.values())  # the mark ends after release
    lane1._ready(engine)
    _refocus(me)
    assert _release_targets(engine) == set()
    assert _offered(engine, "Quivering Gate Strike") == {FOE2}  # releasing does not give the use back


def test_release_successful_save_is_half_damage_and_no_reactions_not_stunned():
    engine, me = _quivering(dc=1)
    foe = engine.state.actors[FOE1]
    _do(engine, me, "Quivering Gate Strike", target=FOE1)
    lane1._ready(engine)
    before = foe.current_hp
    _do(engine, me, "Release Quivering Gate Mark", target=FOE1)
    assert "stunned" not in _held_ids(foe) and "reaction_denied" in _held_ids(foe)
    taken = before - foe.current_hp
    assert 5 <= taken <= 50  # half of 10d10 (5..50), not the whole roll


def test_release_is_only_offered_within_120_feet_of_a_marked_creature():
    engine, me = _quivering(dc=50)
    _do(engine, me, "Quivering Gate Strike", target=FOE1)
    lane1._ready(engine)
    engine.state.actors[FOE1].position = Position(x=3 + 25, y=6)  # 125 ft away
    assert _release_targets(engine) == set()
    engine.state.actors[FOE1].position = Position(x=3 + 20, y=6)  # 100 ft away
    assert _release_targets(engine) == {FOE1}


# ------------------------------------------------------------------------------- System 4: Jester (Proposition, Foil, Punchline)

JESTER = "tianxia.talent.jester."
ALLY = "actor:factory.sys_ally"
PUNCHLINES = ("excellent_idea", "after_you_honored_guest", "applaud_the_master", "the_audience_chooses_the_hero")


def _jester_bundle(talents=PUNCHLINES, dc=16):
    from combat.factory_compiler import compile_character

    sheet = lane1._sheet(JESTER + talents[0], cl=12, dc=dc)
    sheet["spheres_and_talents"]["learned_talent_record_ids"] = [JESTER + name for name in talents]
    return compile_character(sheet, actor_id=ME)


def _jester_fight(talents=PUNCHLINES, *, foes=(FOE1,), ally_ac=None, dc=16):
    """A Jester at (3,6), its foes far off at (12,6..), and -- if ``ally_ac`` -- an ally of the Jester's next to foe one."""
    bundles = [_jester_bundle(talents, dc), *(_foe(f) for f in foes)]
    team = {ME: "team:a", **{f: "team:b" for f in foes}}
    places = {ME: {"x": 3, "y": 6}, **{f: {"x": 12, "y": 6 + 2 * i} for i, f in enumerate(foes)}}
    ids = [ME, *foes]
    if ally_ac is not None:
        bundles.append(lane1._bundle("TAL_ALCHEMY_CALMING_HEART_PILL", actor_id=ALLY))
        team[ALLY], places[ALLY] = "team:a", {"x": 12, "y": 7}
        ids.append(ALLY)
    engine = Gate4ControllerEngine(ROOT, match_seed="SYSFORMS", typed_bundles=tuple(bundles),
                                   roster_setup={"primary_actor_ids": ids, "team_by_actor": team, "starting_positions": places})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    lane1._ready(engine)
    for actor_id in [*foes, *([ALLY] if ally_ac is not None else [])]:
        engine.state.actors[actor_id].maximum_hp = engine.state.actors[actor_id].current_hp = 900
    if ally_ac is not None:
        engine.state.actors[ALLY].armor_class = ally_ac
    return engine


def _turn_of(engine, actor_id):
    engine.state.current_actor_id = actor_id
    engine.state.actors[actor_id].reaction_available = True
    return engine.state.actors[actor_id]


def _foils(engine, foe_id):
    return sorted(c.condition_id.split(".")[2] for c in engine.state.actors[foe_id].conditions.values() if ".mark.foil_" in c.condition_id)


def _swing(engine, foe_id, target):
    """The foe picks up a stick and swings it at ``target``; returns the events of the swing."""
    foe = _turn_of(engine, foe_id)
    _do(engine, foe, "Grab an improvised weapon")
    foe.reaction_available = True
    return _do(engine, foe, "Improvised weapon attack", target=target)


def test_set_the_scene_is_four_buttons_one_per_proposition():
    engine = _jester_fight()
    names = _names(engine, engine.state.actors[ME])
    assert {f"Set the Scene: {p}" for p in ("Come Closer", "Strike the Fool", "Ignore the Fool", "Show Your Hand")} <= names


def test_set_the_scene_marks_the_foil_with_its_proposition():
    engine = _jester_fight()
    _do(engine, engine.state.actors[ME], "Set the Scene: Show Your Hand", target=FOE1)
    assert _foils(engine, FOE1) == ["foil_show_your_hand"]


def test_a_jester_has_only_one_foil_at_a_time():
    engine = _jester_fight(foes=(FOE1, FOE2))
    me = engine.state.actors[ME]
    _do(engine, me, "Set the Scene: Show Your Hand", target=FOE1)
    lane1._ready(engine)
    _do(engine, me, "Set the Scene: Come Closer", target=FOE2)
    assert _foils(engine, FOE1) == [] and _foils(engine, FOE2) == ["foil_come_closer"]


def test_excellent_idea_answers_a_supernatural_technique_from_the_show_your_hand_foil():
    engine = _jester_fight(dc=50)
    me = engine.state.actors[ME]
    _do(engine, me, "Set the Scene: Show Your Hand", target=FOE1)
    foe = _turn_of(engine, FOE1)
    events = _do(engine, foe, "Calming Heart Pill")
    assert any(e.event_type == "SAVE_ROLLED" and e.payload["reason"] == f"SAVE:{JESTER}excellent_idea:WIS" for e in events)
    assert {"flustered", "concentration_mode"} <= _held_ids(foe)
    assert foe.reaction_available is False and me.reaction_available is False  # both spent theirs: the Jester's Reaction, the Foil's by Flustered
    assert _foils(engine, FOE1) == []  # "after you deliver a Punchline, Set the Scene ends"


def test_excellent_idea_successful_save_only_denies_reactions():
    engine = _jester_fight(dc=1)
    _do(engine, engine.state.actors[ME], "Set the Scene: Show Your Hand", target=FOE1)
    foe = _turn_of(engine, FOE1)
    _do(engine, foe, "Calming Heart Pill")
    assert "flustered" not in _held_ids(foe) and "reaction_denied" in _held_ids(foe)


def test_a_punchline_answers_only_its_own_proposition():
    engine = _jester_fight(dc=50)
    _do(engine, engine.state.actors[ME], "Set the Scene: Strike the Fool", target=FOE1)
    foe = _turn_of(engine, FOE1)
    events = _do(engine, foe, "Calming Heart Pill")
    assert not any(e.event_type == "SAVE_ROLLED" and "excellent_idea" in e.payload["reason"] for e in events)
    assert _foils(engine, FOE1) == ["foil_strike_the_fool"] and "flustered" not in _held_ids(foe)


def test_only_the_foil_fulfils_a_proposition():
    engine = _jester_fight(foes=(FOE1, FOE2), dc=50)
    _do(engine, engine.state.actors[ME], "Set the Scene: Show Your Hand", target=FOE1)
    other = _turn_of(engine, FOE2)
    events = _do(engine, other, "Calming Heart Pill")
    assert not any(e.event_type == "SAVE_ROLLED" and "excellent_idea" in e.payload["reason"] for e in events)
    assert _foils(engine, FOE1) == ["foil_show_your_hand"]


def test_after_you_honored_guest_steps_away_and_topples_a_foil_that_came_closer():
    engine = _jester_fight(dc=50)
    me = engine.state.actors[ME]
    _do(engine, me, "Set the Scene: Come Closer", target=FOE1)
    foe = _turn_of(engine, FOE1)
    before = (me.position.x, me.position.y)
    events = _do(engine, foe, "Move", destination=(8, 6))
    assert any(e.event_type == "SAVE_ROLLED" and e.payload["reason"] == f"SAVE:{JESTER}after_you_honored_guest:DEX" for e in events)
    assert (me.position.x, me.position.y) != before  # the Jester's ten-foot step came first
    assert "prone" in _held_ids(foe) and _foils(engine, FOE1) == []


def test_after_you_honored_guest_does_not_answer_a_foil_that_stays_put():
    engine = _jester_fight(dc=50)
    _do(engine, engine.state.actors[ME], "Set the Scene: Come Closer", target=FOE1)
    foe = _turn_of(engine, FOE1)
    _do(engine, foe, "Move", destination=(13, 6))  # one square back: away from the Jester
    assert "prone" not in _held_ids(foe) and _foils(engine, FOE1) == ["foil_come_closer"]


def test_applaud_the_master_makes_the_foils_swing_at_an_ally_miss_and_flusters_it():
    engine = _jester_fight(("applaud_the_master",), ally_ac=16)  # the foe's swing is a 16: it would hit AC 16 but not 18
    _do(engine, engine.state.actors[ME], "Set the Scene: Ignore the Fool", target=FOE1)
    foe = engine.state.actors[FOE1]
    events = _swing(engine, FOE1, ALLY)
    assert any(e.event_type == "ATTACK_ROLLED" for e in events) and not any(e.event_type == "DAMAGE_COMMITTED" for e in events)
    assert "flustered" in _held_ids(foe) and foe.reaction_available is False
    assert not [c for c in engine.state.actors[ALLY].conditions.values() if c.condition_id.endswith("jester_applause")]  # the watch is spent


def test_applaud_the_master_does_not_flustered_a_foil_whose_attack_hits_anyway():
    engine = _jester_fight(("applaud_the_master",), ally_ac=-50)
    _do(engine, engine.state.actors[ME], "Set the Scene: Ignore the Fool", target=FOE1)
    events = _swing(engine, FOE1, ALLY)
    assert any(e.event_type == "DAMAGE_COMMITTED" for e in events)
    assert "flustered" not in _held_ids(engine.state.actors[FOE1])


def test_the_audience_chooses_the_hero_gives_the_ally_temporary_hit_points_and_ends_the_scene():
    engine = _jester_fight(("the_audience_chooses_the_hero",), ally_ac=14)  # the swing is a 16: only the +2 AC (and not Applaud's watch) can turn it
    ally = engine.state.actors[ALLY]
    _do(engine, engine.state.actors[ME], "Set the Scene: Ignore the Fool", target=FOE1)
    events = _swing(engine, FOE1, ALLY)
    assert ally.temporary_hp > 0  # 2 x Proficiency Bonus
    assert not any(e.event_type == "DAMAGE_COMMITTED" and e.payload.get("hp_damage") for e in events)  # the temporary hit points soak it, or the +2 AC turned it
    assert _foils(engine, FOE1) == []


def test_flustered_gives_disadvantage_on_the_next_attack_roll_only():
    engine = _jester_fight(dc=50)
    _do(engine, engine.state.actors[ME], "Set the Scene: Show Your Hand", target=FOE1)
    foe = _turn_of(engine, FOE1)
    _do(engine, foe, "Calming Heart Pill")
    assert "flustered" in _held_ids(foe)
    from combat.ext import jester

    class Ctx:  # what the attack_mode hook is given: the attacker and the engine (a real roll needs no more)
        pass
    ctx = Ctx()
    ctx.actor, ctx.engine, ctx.source = foe, engine, "test"
    assert jester.flustered_disadvantage(ctx, engine.state.actors[ME]) == "DISADVANTAGE"
    # The Jester packets answer the mode query without spending it: a declared-attack reaction can still
    # cancel that attack, so only the real roll receipt spends it (6ee4d599; tests/test_auto65_jester.py
    # proves the same at the table). A second query must therefore still report Disadvantage.
    assert jester.flustered_disadvantage(ctx, engine.state.actors[ME]) == "DISADVANTAGE"
    jester.flustered_check_used(engine, "ATTACK_ROLLED",
        {"payload": {"actor_id": foe.entity_id, "reason": "ATTACK:test.flustered", "natural_result": 10}})
    assert jester.flustered_disadvantage(ctx, engine.state.actors[ME]) is None  # "After that roll, the Disadvantage portion ends"
    assert "flustered" in _held_ids(foe)  # ... but the creature still cannot take Reactions until the condition ends


def test_flustered_ends_at_the_start_of_the_jesters_next_turn():
    engine = _jester_fight(dc=50)
    me = engine.state.actors[ME]
    _do(engine, me, "Set the Scene: Show Your Hand", target=FOE1)
    foe = _turn_of(engine, FOE1)
    _do(engine, foe, "Calming Heart Pill")
    assert "flustered" in _held_ids(foe)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    assert "flustered" not in _held_ids(foe)


def test_flustered_and_the_applause_have_hover_text():
    from combat import condition_text

    for condition in ("flustered", "jester_applause"):
        assert condition_text.READING.get(condition), condition


def test_the_ai_sets_the_scene_only_for_a_proposition_it_has_a_punchline_for():
    from combat.ext import jester

    engine = _jester_fight(("excellent_idea",))
    me = engine.state.actors[ME]
    allowed = {}
    for candidate in engine.legal_candidates():
        if candidate.display_name.startswith("Set the Scene"):
            action = engine.action_catalog[candidate.source_definition_id]
            allowed[candidate.display_name] = jester.only_a_proposition_with_a_punchline(engine, me, candidate, action)
    assert set(allowed) == {f"Set the Scene: {p}" for p in ("Come Closer", "Strike the Fool", "Ignore the Fool", "Show Your Hand")}  # a player is offered all four
    assert allowed["Set the Scene: Show Your Hand"] is True  # Excellent Idea answers it
    assert not any(allowed[name] for name in allowed if not name.endswith("Show Your Hand"))


def test_absurd_agreement_failed_save_takes_the_chosen_option_speed_by_default():
    engine = _jester_fight(("absurd_agreement",), dc=50)
    me = engine.state.actors[ME]
    assert any(n.startswith("Choose Absurd Agreement:") for n in _names(engine, me))  # a Reaction's menu still gets its buttons
    _do(engine, me, "Set the Scene: Show Your Hand", target=FOE1)
    foe = _turn_of(engine, FOE1)
    events = _do(engine, foe, "Calming Heart Pill")
    assert any(e.event_type == "MODIFIER_APPLIED" and e.payload["target_field"] == "speed_ft" and e.payload["value"] == -10 for e in events)
    assert "flustered" not in _held_ids(foe)


def test_absurd_agreement_chosen_option_flusters_instead():
    engine = _jester_fight(("absurd_agreement",), dc=50)
    me = engine.state.actors[ME]
    _do(engine, me, "Set the Scene: Show Your Hand", target=FOE1)
    lane1._ready(engine)
    _do(engine, me, "Choose Absurd Agreement: It becomes Flustered")
    foe = _turn_of(engine, FOE1)
    events = _do(engine, foe, "Calming Heart Pill")
    assert "flustered" in _held_ids(foe)
    assert not any(e.event_type == "MODIFIER_APPLIED" and e.payload["target_field"] == "speed_ft" for e in events)
