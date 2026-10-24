"""AUTO13 (r25): the printed Weather Sign effects of Sky Mantle and Cloud Shroud, at the table.

Every test here plays a real match through TabletopService: each commit is followed by a fresh saved-fight load and
a replay check (``tests/test_hunt27_table.commit``), so a printed effect that only survives in memory fails here.
The printed Weather Sign rows live in ``combat/ext/weather_signs.py``; the rules the tests quote are the owner's
Sphere Compendium, "Sphere of Weather" (also APP/authority/typed_mechanics/rules_text.json).
"""
from __future__ import annotations

import json
import zipfile

import pytest

from combat.ext import weather_mantle, weather_signs
from combat.ext.weather_mantle import MANTLE
from combat.ext.weather_shroud import SHROUD, sign_of as shroud_sign
from tests.h1_support import ROOT, sheet
from tests.test_carry import KIT

ME, ALLY, FOE, FOE2 = ["actor:factory.a13" + n for n in ("probe", "ally", "foe", "foe2")]
#: Any Weather talent grants the Weather sphere, whose base abilities the sheet then carries automatically.
SPHERE = ["TAL_WEATHER_FOUNDATION_WEATHER_FIELD"]
SHROUD_TALENTS = [*SPHERE, "TAL_WEATHER_PERSISTENT_SHROUD", "TAL_WEATHER_PRESSURE_CRACKING_SHROUD",
                  "TAL_WEATHER_LIGHTNING_CHOOSES_THE_ROD"]
MANTLE_TALENTS = [*SPHERE, "TAL_WEATHER_QUICK_MANTLE", "TAL_WEATHER_WEATHERPROOF_MANTLE", "TAL_WEATHER_WEATHER_BACKLASH",
                  "TAL_WEATHER_SHARED_WEATHER_FAVOR"]


def arena(tmp_path, talents, topic, *, manual=True, owner_mode=None, cl=20, dc=22, maximum_rounds=6, ask_actors=(), ally_ac=None,
          foe_pb=None, foe_cl=None, positions=None, foe_talents=()):
    """The hunt27 arena with a settable save DC, so a test can force failures (dc 40) or successes (dc 2).

    ``foe_talents`` gives the east foe its own real abilities, for a save that some other sphere's technique causes.
    """
    from combat.factory_compiler import compile_character
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService

    ids = [ME, ALLY, FOE, FOE2]
    docs = [sheet(talents, cl=cl, dc=dc, kit={"starting_kit": KIT})] + [
        sheet(list(foe_talents) if aid == FOE else [], cl=cl, dc=dc, kit={"starting_kit": KIT})
        for aid in ids[1:]]
    for aid, doc, name in zip(ids, docs, ("You", "Ally", "East foe", "West foe")):
        doc["identity"]["display_name"] = name
        doc["ability_scores_and_statistics"]["hit_points"]["maximum"] = 200
        doc["ability_scores_and_statistics"]["primary_resource"]["maximum"] = 100
        if ally_ac is not None and aid == ALLY:
            # A melee trigger test needs its hits to land; the mantled ally wears almost no armour.
            doc["ability_scores_and_statistics"]["armor_class"]["base_value"] = ally_ac
        if aid == FOE and foe_pb is not None:
            # "your Proficiency Bonus" is the Mantle owner's, so the attacker must not share it.
            doc["identity"]["proficiency_bonus"] = foe_pb
        if aid == FOE and foe_cl is not None:
            doc["identity"]["cultivation_level"] = foe_cl
        folder = tmp_path / "portable_characters" / aid.removeprefix("actor:factory.")
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(doc))
    combat = CombatService(ROOT, tmp_path)
    bundles = [compile_character(doc, actor_id=aid, reaction_plan={"ask": True} if aid == ME or aid in ask_actors else None)
               for aid, doc in zip(ids, docs)]
    mid = combat._finish_factory_match(
        bundles, ids, {ME: "team:factory", ALLY: "team:factory", FOE: "team:opponents", FOE2: "team:opponents"},
        {**{ME: {"x": 3, "y": 6}, ALLY: {"x": 3, "y": 7}, FOE: {"x": 4, "y": 6}, FOE2: {"x": 5, "y": 6}},
         **(positions or {})},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [ME, ALLY], [FOE, FOE2],
        control_modes={ME: owner_mode or ("MANUAL" if manual else "LOCAL_AUTO"), **{aid: "MANUAL" for aid in ask_actors}},
        match_seed=f"A13-{topic}-0", maximum_rounds=maximum_rounds,
        display_name="AUTO13 Weather regression")["match_id"]
    return combat, TabletopService(combat, tmp_path), mid


def commit(combat, table, mid, tmp_path, cid=None, choose=None, prompts=None):
    """Play one action to its end, reloading and replaying after every commit.

    ``prompts``, when a list is given, collects the raw reaction payloads exactly as the table presented them, so a test
    can assert on the words a player reads rather than only on the routing keys ``answers`` carries.
    """
    from combat.gate5_service import CombatService

    view = table.state(mid)
    menu = view["menu"]
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    answers = []
    for _ in range(40):
        result = (table.act(mid, cid or menu["end_turn"], menu["decision_id"], menu["state_version"],
                            view["last_sequence"], answers)
                  if menu.get("manual") else table.auto_step(mid, view["last_sequence"], answers))
        if result["status"] != "REACTION_REQUIRED":
            break
        assert CombatService(ROOT, tmp_path)._load_session(mid).engine.state.model_dump(mode="json") == before
        prompt = result["reaction"]
        if prompts is not None:
            prompts.append(prompt)
        answer = {**prompt["context"], "selection": "USE"}
        if prompt.get("choice"):
            choice = prompt["choice"]
            selected = (choose(prompt) if choose else
                        [o["id"] for o in choice["options"][:choice.get("minimum", 1)]])
            answer["option_ids"] = selected or []
            if selected is None:
                answer["selection"] = "DECLINE"
        assert answer not in answers
        answers.append(answer)
    assert result["status"] == "COMMITTED", result
    expected = combat._load_session(mid).engine.state.model_dump(mode="json")
    fresh = CombatService(ROOT, tmp_path)._load_session(mid)
    assert fresh.engine.state.model_dump(mode="json") == expected
    assert fresh.mechanical.replay()["status"] == "PASS"
    return answers


def next_owner_turn(combat, table, mid, tmp_path):
    """End whatever turn it is and idle everyone until the owner is back, so a second Action is available."""
    engine = combat._load_session(mid).engine
    if engine.state.current_actor_id == ME:
        commit(combat, table, mid, tmp_path,
               next(c.candidate_id for c in engine.legal_candidates() if c.kind.value == "END_TURN"))
    owner_turn(combat, table, mid, tmp_path, idle=True)


def owner_turn(combat, table, mid, tmp_path, idle=False):
    for _ in range(60):
        if combat._load_session(mid).engine.state.current_actor_id == ME:
            return
        cid = next((c.candidate_id for c in combat._load_session(mid).engine.legal_candidates()
                    if c.kind.value == "END_TURN"), None) if idle else None
        commit(combat, table, mid, tmp_path, cid)
    pytest.fail("owner never reached its turn")


def action(combat, mid, name, target=ME):
    return next(c.candidate_id for c in combat._load_session(mid).engine.legal_candidates()
                if (c.display_name.startswith(name) if target is None else c.display_name == name)
                and (target is None or target in c.target_ids))


def shroud_of(engine, who=FOE):
    return [c for c in engine.state.actors[who].conditions.values() if c.condition_id == SHROUD]


def mantle_of(engine, who):
    return [c for c in engine.state.actors[who].conditions.values() if c.condition_id == MANTLE]


def legal_candidates(engine):
    """The engine's own candidates, empty once the fight is over (the loops below stop there)."""
    return engine.legal_candidates() if engine.state.terminal_result is None else ()


def logs(engine, kind="PASSIVE_TRIGGERED"):
    return [str(e.payload.get("log") or "") for e in engine.events if e.event_type == kind]


def choose_shroud(sign_id):
    def chooser(prompt):
        options = [o["id"] for o in (prompt.get("choice") or {}).get("options", [])]
        picked = [o for o in options if o == sign_id]
        return picked or options[:1]
    return chooser


def choose_mantle(sign_id, mode="active"):
    def chooser(prompt):
        options = [o["id"] for o in (prompt.get("choice") or {}).get("options", [])]
        wanted = f"{sign_id}:{mode}"
        picked = [o for o in options if o == wanted] or [o for o in options if o.endswith(":" + mode)]
        return picked or options[:1]
    return chooser


def choose_source(choice_id):
    """Answer exactly one kind of question (by its reaction_source_id), so a test can prove it was asked once."""
    def chooser(prompt):
        if prompt["context"]["reaction_source_id"] != choice_id:
            return [o["id"] for o in (prompt.get("choice") or {}).get("options", [])]
        return [o["id"] for o in prompt["choice"]["options"][:1]]
    return chooser


def mantle_chooser(sign_id, mode="active", *, purchase=None, extra=None, tally=None):
    """Answer Sky Mantle's sign menu, its one-sign-per-purchase Weatherproof question, and a recipient's consent.

    ``purchase`` is the sign the owner's one Weatherproof purchase covers (the Mantle's own sign unless a test wants the
    purchase spent elsewhere). ``extra`` is the entity the Shared Weather Favor question picks (a list) or None to decline
    it. Every question is recorded in ``tally`` so a test can count them.
    """
    bought = purchase or sign_id

    def chooser(prompt):
        source = prompt["context"]["reaction_source_id"]
        if tally is not None:
            tally.setdefault("seen", []).append(source)
        options = [o["id"] for o in (prompt.get("choice") or {}).get("options", [])]
        if source == "choice:willing.consent":
            return ["accept"]
        if source == "choice:willing.targets":
            return list(extra) if extra else None
        if source == weather_mantle.WEATHERPROOF_SIGN_CHOICE:
            return [bought]
        return choose_mantle(sign_id, mode)(prompt)
    return chooser


# ------------------------------------------------------------------------------- the printed sign table itself
def test_printed_sign_table_is_the_compendium_text():
    """The six signs, their printed saving throws and their realm steps, exactly as the compendium prints them."""
    assert weather_signs.names() == ["wind", "rain", "cold", "heat", "dry", "thunder"]
    assert weather_signs.sign("wind")["shroud"]["ability"] == "STR"
    for sign_id in ("rain", "cold", "heat", "dry", "thunder"):
        assert weather_signs.sign(sign_id)["shroud"]["ability"] == "CON"
    # "The damage becomes 2d6 at Foundation Realm, 3d6 at Core Formation, and 4d6 at Nascent Soul."
    assert weather_signs.by_realm({"base": [1, 6], "Foundation Realm": [2, 6], "Core Formation": [3, 6],
                                   "Nascent Soul": [4, 6]}, 3) == [1, 6]
    assert weather_signs.by_realm({"base": [1, 6], "Foundation Realm": [2, 6], "Core Formation": [3, 6],
                                   "Nascent Soul": [4, 6]}, 7) == [2, 6]
    assert weather_signs.by_realm({"base": [1, 6], "Foundation Realm": [2, 6], "Core Formation": [3, 6],
                                   "Nascent Soul": [4, 6]}, 12) == [3, 6]
    assert weather_signs.by_realm({"base": [1, 6], "Foundation Realm": [2, 6], "Core Formation": [3, 6],
                                   "Nascent Soul": [4, 6]}, 17) == [4, 6]
    # "At Foundation Realm, the Speed bonus becomes +15 feet. At Core Formation, it becomes +20 feet."
    speed = weather_signs.sign("wind")["mantle"]["speed_ft"]
    assert [weather_signs.by_realm(speed, cl) for cl in (1, 5, 10, 15, 20)] == [10, 15, 20, 30, 30]
    # Four-Season Reversal's printed opposing pairs.
    assert weather_signs.opposes("cold", "heat") and weather_signs.opposes("rain", "dry")
    assert not weather_signs.opposes("wind", "rain")
    # Every Shroud row is engine-vocabulary: the printed rows resolve as ordinary typed effects.
    rows = weather_signs.shroud_rows("thunder", 20)
    assert rows["save"] == "CON" and rows["fail"][0]["type"] == "damage"
    assert rows["fail"][0]["damage_types"] == ["thunder"]


# ------------------------------------------------------------------------------- Cloud Shroud
def test_thunder_shroud_failed_save_hurts_and_deafens(tmp_path):
    """A failed Constitution save against a Thunder Shroud deals thunder damage and Deafens until its next turn."""
    combat, table, mid = arena(tmp_path, list(SPHERE), "shroud-thunder", dc=40)
    owner_turn(combat, table, mid, tmp_path, idle=True)
    before = combat._load_session(mid).engine.state.actors[FOE].current_hp
    commit(combat, table, mid, tmp_path, action(combat, mid, "Cloud Shroud (any creature)", FOE),
           choose=choose_shroud("thunder"))
    engine = combat._load_session(mid).engine
    foe = engine.state.actors[FOE]
    assert foe.current_hp < before
    assert any(c.condition_id == "condition:typed.deafened" for c in foe.conditions.values())
    shrouds = shroud_of(engine)
    assert len(shrouds) == 1 and shroud_sign(shrouds[0]) == "thunder"
    assert shrouds[0].data["save"] == "CON"
    assert any("Thunder Sign Shroud" in line for line in logs(engine))


@pytest.mark.parametrize(("sign_id", "condition_id"), [
    ("dry", "condition:typed.poisoned"),
    ("heat", None),
])
def test_shroud_failure_runs_that_signs_printed_effect(tmp_path, sign_id, condition_id):
    """Each sign's Shroud effect runs on the printed saving throw: Dry Poisons, Heat scalds for 1d6 + key modifier."""
    combat, table, mid = arena(tmp_path, list(SPHERE), f"shroud-{sign_id}", dc=40)
    owner_turn(combat, table, mid, tmp_path, idle=True)
    before = combat._load_session(mid).engine.state.actors[FOE].current_hp
    commit(combat, table, mid, tmp_path, action(combat, mid, "Cloud Shroud (any creature)", FOE),
           choose=choose_shroud(sign_id))
    engine = combat._load_session(mid).engine
    foe = engine.state.actors[FOE]
    assert shroud_sign(shroud_of(engine)[0]) == sign_id
    if condition_id:
        assert any(c.condition_id == condition_id for c in foe.conditions.values())
    else:  # 1d6 + the Weather key ability modifier, minimum 1 damage at CL 20
        assert foe.current_hp < before


def test_wind_shroud_pushes_ten_feet(tmp_path):
    """"it is pushed 10 feet in a direction you choose" on a failed Strength save."""
    combat, table, mid = arena(tmp_path, list(SPHERE), "shroud-wind", dc=40)
    owner_turn(combat, table, mid, tmp_path, idle=True)
    start = combat._load_session(mid).engine.state.actors[FOE].position
    commit(combat, table, mid, tmp_path, action(combat, mid, "Cloud Shroud (any creature)", FOE),
           choose=choose_shroud("wind"))
    engine = combat._load_session(mid).engine
    assert engine.state.actors[FOE].position != start, "a failed Strength save pushes the target 10 feet"
    assert shroud_sign(shroud_of(engine)[0]) == "wind"


def test_shroud_repeats_at_the_end_of_each_turn_and_a_success_keeps_it(tmp_path):
    """The saving throw repeats at the end of each of its turns; a success prevents that round's effect and stays."""
    combat, table, mid = arena(tmp_path, list(SPHERE), "shroud-repeat", dc=2, maximum_rounds=60)
    owner_turn(combat, table, mid, tmp_path, idle=True)
    commit(combat, table, mid, tmp_path, action(combat, mid, "Cloud Shroud (any creature)", FOE),
           choose=choose_shroud("thunder"))
    engine = combat._load_session(mid).engine
    assert shroud_of(engine)[0].data["successes"] == 1
    for _ in range(32):
        engine = combat._load_session(mid).engine
        if not legal_candidates(engine) or int(shroud_of(engine)[0].data["successes"]) >= 2:
            break
        commit(combat, table, mid, tmp_path)
    held = shroud_of(combat._load_session(mid).engine)
    assert held, "a successful save must not end an ordinary Shroud"
    assert int(held[0].data["successes"]) >= 2, "the throw repeats at the end of each of its turns"
    assert not any(c.condition_id == "condition:typed.deafened" for c in engine.state.actors[FOE].conditions.values())


def test_one_shroud_from_the_same_owner_per_creature(tmp_path):
    """"A creature can be under only one of your Cloud Shrouds at a time. Placing a second ... ends the first."""
    combat, table, mid = arena(tmp_path, list(SPHERE), "shroud-one", dc=40, maximum_rounds=10)
    owner_turn(combat, table, mid, tmp_path, idle=True)
    for sign_id in ("thunder", "cold"):
        next_owner_turn(combat, table, mid, tmp_path)
        commit(combat, table, mid, tmp_path, action(combat, mid, "Cloud Shroud (any creature)", FOE),
               choose=choose_shroud(sign_id))
    engine = combat._load_session(mid).engine
    held = shroud_of(engine)
    assert len(held) == 1 and shroud_sign(held[0]) == "cold"


# ------------------------------------------------------------------------------- Persistent Shroud
def test_persistent_shroud_needs_no_concentration_and_ends_after_three_successes(tmp_path):
    """Persistent Shroud: no Concentration, and "ends after the target succeeds on three saving throws against it"."""
    combat, table, mid = arena(tmp_path, SHROUD_TALENTS, "persistent", dc=2, maximum_rounds=12)
    owner_turn(combat, table, mid, tmp_path, idle=True)
    before_concentration = combat._load_session(mid).engine.state.actors[ME].concentration
    commit(combat, table, mid, tmp_path, action(combat, mid, "Cloud Shroud (any creature) + Persistent Shroud", FOE),
           choose=choose_shroud("thunder"))
    engine = combat._load_session(mid).engine
    held = shroud_of(engine)
    assert held and held[0].data["persistent"] == 1
    assert held[0].expires_on == "UNTIL_REMOVED"
    after = engine.state.actors[ME].concentration
    assert (after is None) == (before_concentration is None), \
        "a Persistent Shroud never takes Concentration"
    for _ in range(24):
        engine = combat._load_session(mid).engine
        if not legal_candidates(engine) or not shroud_of(engine):
            break
        if engine.state.current_actor_id != FOE:
            commit(combat, table, mid, tmp_path)
            continue
        commit(combat, table, mid, tmp_path,
               next(c.candidate_id for c in engine.legal_candidates() if c.kind.value == "END_TURN"))
    assert not shroud_of(combat._load_session(mid).engine), "three successful saves end a Persistent Shroud"


def test_only_one_persistent_shroud_at_mortal_realm(tmp_path):
    """"You may have only one Persistent Shroud active at a time at Mortal Realm. If you create another, the previous one ends"."""
    combat, table, mid = arena(tmp_path, SHROUD_TALENTS, "persistent-one", cl=3, dc=40, maximum_rounds=16)
    owner_turn(combat, table, mid, tmp_path, idle=True)
    commit(combat, table, mid, tmp_path, action(combat, mid, "Cloud Shroud (any creature) + Persistent Shroud", FOE),
           choose=choose_shroud("thunder"))
    assert shroud_sign(shroud_of(combat._load_session(mid).engine)[0]) == "thunder"
    next_owner_turn(combat, table, mid, tmp_path)
    cast = action(combat, mid, "Cloud Shroud (any creature) + Persistent Shroud", FOE2)
    answers = commit(combat, table, mid, tmp_path, cast, choose=choose_shroud("cold"))
    engine = combat._load_session(mid).engine
    # "You may have only one Persistent Shroud active at a time at Mortal Realm. If you create another, the previous
    # one ends": the new Shroud replaces the old one (AUTO13f1: a limit on what is active, not a one-use allowance
    # that is spent and refused), so the second cast succeeds and the first ends.
    assert shroud_sign(shroud_of(engine, FOE2)[0]) == "cold", "the new Persistent Shroud is placed"
    assert not shroud_of(engine, FOE), "creating another ends the owner's previous Persistent Shroud"
    assert any("earlier Persistent Shroud ends" in line for line in logs(engine))


# ------------------------------------------------------------------------------- Pressure-Cracking Shroud
def test_pressure_cracking_shroud_takes_away_resistance(tmp_path):
    """"you may spend 2 CP to crack its resistance": the target loses Resistance to the Shroud's damage type."""
    combat, table, mid = arena(tmp_path, [*SHROUD_TALENTS, "TAL_WEATHER_CORE_WEATHER_FIELD"], "cracking", dc=40, maximum_rounds=8)
    # Matching weather is now state, rather than the old verbal confirmation.
    from tests.test_a2_weather import gather, choices
    gather(combat, table, mid, tmp_path, "wind", "rain")
    next_owner_turn(combat, table, mid, tmp_path)
    owner_turn(combat, table, mid, tmp_path, idle=True)
    # The printed setup: give the foe thunder Resistance through the engine's own modifier path, then shroud it.
    engine = combat._load_session(mid).engine
    engine._add_modifier(engine.state.actors[FOE], "system:test", "damage_resistance", "ADD", "THUNDER", "SELF",
                         expires_on="UNTIL_REMOVED")
    cp = engine.state.actors[ME].resources["resource:core.qi"]
    commit(combat, table, mid, tmp_path,
           action(combat, mid, "Cloud Shroud (any creature) + Pressure-Cracking Shroud", FOE),
           choose=choose_shroud("thunder"))
    engine = combat._load_session(mid).engine
    assert engine.state.actors[ME].resources["resource:core.qi"] == cp - 3, "2 Cultivation Points for the crack"
    assert not any(m.target_field == "damage_resistance" and str(m.value) == "THUNDER"
                   for m in engine.state.actors[FOE].modifiers.values() if not m.consumed)
    assert any("Pressure-Cracking" in line for line in logs(engine))


# ------------------------------------------------------------------------------- Lightning Chooses the Rod
def test_lightning_chooses_the_rod_moves_the_thunder_shroud_once_per_round(tmp_path):
    """The Thunder Shroud moves to another creature within 30 feet without an action; the new target saves at once."""
    combat, table, mid = arena(tmp_path, SHROUD_TALENTS, "rod", dc=40, maximum_rounds=10)
    owner_turn(combat, table, mid, tmp_path, idle=True)
    commit(combat, table, mid, tmp_path, action(combat, mid, "Cloud Shroud (any creature)", FOE),
           choose=choose_shroud("thunder"))
    engine = combat._load_session(mid).engine
    move = action(combat, mid, "Move Thunder Shroud", FOE2)
    commit(combat, table, mid, tmp_path, move)
    engine = combat._load_session(mid).engine
    assert not shroud_of(engine, FOE), "the Shroud moved off its original target"
    assert shroud_sign(shroud_of(engine, FOE2)[0]) == "thunder", "the Shroud moved to the new target"
    assert any(c.condition_id == "condition:typed.deafened"
               for c in engine.state.actors[FOE2].conditions.values()), "the new target saved immediately"
    # "You may do this once per round": the rest of the same round offers nothing more.
    assert not [c for c in engine.legal_candidates() if c.display_name == "Move Thunder Shroud"], "once per round"


# ------------------------------------------------------------------------------- Sky Mantle's printed sign benefits
def test_wind_mantle_gives_the_printed_speed(tmp_path):
    """"A creature with your Wind Mantle gains +10 feet Speed" (Core Formation: +20)."""
    combat, table, mid = arena(tmp_path, MANTLE_TALENTS, "mantle-wind", cl=10, ask_actors=(ALLY,), maximum_rounds=8)

    def consenting(prompt):
        if prompt["context"]["reaction_source_id"] == "choice:willing.consent":
            return ["accept"]
        return choose_mantle("wind")(prompt)

    owner_turn(combat, table, mid, tmp_path, idle=True)
    plain = combat._load_session(mid).engine._effective_speed(combat._load_session(mid).engine.state.actors[ALLY])
    commit(combat, table, mid, tmp_path, action(combat, mid, "Sky Mantle", ALLY), choose=consenting)
    engine = combat._load_session(mid).engine
    mantles = mantle_of(engine, ALLY)
    assert len(mantles) == 1
    assert mantles[0].data["sign"] == "wind" and int(mantles[0].data["speed_ft"]) == 20
    assert engine._effective_speed(engine.state.actors[ALLY]) == plain + 20
    assert "Speed" in mantles[0].data["label"]


def test_rain_mantle_resists_fire_only_while_the_sign_is_forced(tmp_path):
    """"Resistance to fire damage ... while the weather around it is Precipitation severity 1 or higher, or while you
    force the sign with Cultivation Points": the forced half runs; there is no gathered-weather state for the other."""
    combat, table, mid = arena(tmp_path, MANTLE_TALENTS, "mantle-rain", ask_actors=(ALLY,), maximum_rounds=10)
    owner_turn(combat, table, mid, tmp_path, idle=True)
    commit(combat, table, mid, tmp_path, action(combat, mid, "Sky Mantle", ALLY),
           choose=mantle_chooser("rain", purchase="cold"))
    engine = combat._load_session(mid).engine
    assert not (mantle_of(engine, ALLY)[0].data["rule"].get("damage_resistances") or []), \
        "an active Rain Mantle has no fire Resistance unless the weather is actually Precipitation"
    next_owner_turn(combat, table, mid, tmp_path)
    commit(combat, table, mid, tmp_path, action(combat, mid, "Refresh Mantle", ALLY),
           choose=mantle_chooser("rain", "force", purchase="cold"))
    engine = combat._load_session(mid).engine
    data = mantle_of(engine, ALLY)[0].data
    assert data["rule"]["damage_resistances"] == ["FIRE"], "a forced Rain Mantle resists fire"
    from combat.ext.standard_conditions import condition_defenses

    rows = [r for r in condition_defenses(engine, engine.state.actors[ALLY], "FIRE", {}, None)]
    assert rows, "the forced sign's fire Resistance is read by the shared damage_defenses path"


def test_heat_mantle_grants_temporary_hit_points_at_the_start_of_each_turn(tmp_path):
    """"gains temporary hit points equal to your Proficiency Bonus at the start of each of its turns"."""
    combat, table, mid = arena(tmp_path, MANTLE_TALENTS, "mantle-heat", maximum_rounds=12)

    def consenting(prompt):
        if prompt["context"]["reaction_source_id"] == "choice:willing.consent":
            return ["accept"]
        return choose_mantle("heat")(prompt)

    owner_turn(combat, table, mid, tmp_path, idle=True)
    # The caster wears its own Mantle, so its own next turn start is one step away.
    commit(combat, table, mid, tmp_path, action(combat, mid, "Sky Mantle", ME), choose=consenting)
    engine = combat._load_session(mid).engine
    held = mantle_of(engine, ME)
    assert held and int(held[0].data["temp_hp"]) == engine.state.actors[ME].proficiency_bonus
    assert engine.state.actors[ME].temporary_hp == 0
    commit(combat, table, mid, tmp_path,
           next(c.candidate_id for c in engine.legal_candidates() if c.kind.value == "END_TURN"))
    owner_turn(combat, table, mid, tmp_path, idle=True)
    engine = combat._load_session(mid).engine
    assert engine.state.actors[ME].temporary_hp == engine.state.actors[ME].proficiency_bonus, \
        "Flame Zephyr grants Temporary Hit Points at the start of its bearer's turn"


def test_shared_weather_favor_mantles_a_second_willing_creature(tmp_path):
    """"you may spend 1 additional CP to target one additional willing creature within 30 feet" on the same sign."""
    combat, table, mid = arena(tmp_path, MANTLE_TALENTS, "shared-favor", ask_actors=(ALLY,), maximum_rounds=8)

    def consenting(prompt):
        if prompt["context"]["reaction_source_id"] == "choice:willing.consent":
            return ["accept"]
        if prompt["context"]["reaction_source_id"] == "choice:willing.targets":
            return [ALLY]  # the printed extra recipient
        return choose_mantle("wind")(prompt)


    owner_turn(combat, table, mid, tmp_path, idle=True)
    shared = next(c for c in combat._load_session(mid).engine.legal_candidates()
                  if "Shared Weather Favor (one more)" in c.display_name and ME in c.target_ids)
    commit(combat, table, mid, tmp_path, shared.candidate_id, choose=consenting)
    engine = combat._load_session(mid).engine
    assert mantle_of(engine, ME), "the aimed creature is mantled"
    assert mantle_of(engine, ALLY), "the printed extra willing recipient is mantled too"
    assert weather_mantle.sign_of(mantle_of(engine, ALLY)[0]) == weather_mantle.sign_of(mantle_of(engine, ME)[0]), \
        "'All targets must receive the same Weather Sign'"


# ------------------------------------------------------------------------------- the printed Mantle talents
def test_weatherproof_mantle_adds_the_signs_resistance(tmp_path):
    """Weatherproof Mantle: the purchased sign's Mantle effect "also grants Resistance to one damage type while active"."""
    combat, table, mid = arena(tmp_path, MANTLE_TALENTS, "weatherproof", ask_actors=(ALLY,), maximum_rounds=8)
    owner_turn(combat, table, mid, tmp_path, idle=True)
    commit(combat, table, mid, tmp_path, action(combat, mid, "Sky Mantle", ALLY),
           choose=mantle_chooser("cold"))
    engine = combat._load_session(mid).engine
    data = mantle_of(engine, ALLY)[0].data
    assert "COLD" in data["rule"]["damage_resistances"], "Cold Sign's Weatherproof Resistance"
    assert weather_mantle._weatherproof_signs(engine, engine.state.actors[ME]) == ["cold"], \
        "the purchase is recorded as the one sign it covers"


def test_weather_backlash_burns_a_melee_attacker_once_per_round(tmp_path):
    """"a creature with your Sky Mantle is hit by a melee attack ... the attacker takes damage equal to your Proficiency Bonus"."""
    # The attacker is made MANUAL so the requested Unarmed Strike is really the action played: an AI attacker's own
    # policy chooses its action and the printed "is hit by a melee attack" trigger would never be reached.
    combat, table, mid = arena(tmp_path, MANTLE_TALENTS, "backlash", ask_actors=(ALLY, FOE), ally_ac=6,
                               maximum_rounds=60)

    def consenting(prompt):
        if prompt["context"]["reaction_source_id"] == "choice:willing.consent":
            return ["accept"]
        return choose_mantle("heat")(prompt)

    owner_turn(combat, table, mid, tmp_path, idle=True)
    commit(combat, table, mid, tmp_path, action(combat, mid, "Sky Mantle", ALLY), choose=consenting)
    engine = combat._load_session(mid).engine
    pb = engine.state.actors[ME].proficiency_bonus
    # The attacker is the only creature that loses hit points here, so its own loss is the printed backlash.
    losses = []
    for _ in range(40):
        engine = combat._load_session(mid).engine
        if engine.state.terminal_result is not None or not legal_candidates(engine):
            break
        if engine.state.current_actor_id != FOE:
            commit(combat, table, mid, tmp_path)
            continue
        strikes = [c.candidate_id for c in engine.legal_candidates()
                   if c.display_name == "Unarmed Strike" and ALLY in c.target_ids]
        if not strikes:
            commit(combat, table, mid, tmp_path)
            continue
        before = engine.state.actors[FOE].current_hp
        commit(combat, table, mid, tmp_path, strikes[0])
        losses.append(before - combat._load_session(mid).engine.state.actors[FOE].current_hp)
        if any(loss >= pb for loss in losses):
            break
    assert any(loss >= pb for loss in losses), \
        f"a melee hit on the mantled creature burns the attacker for the Proficiency Bonus ({pb}); attacker losses: {losses}"
    assert any("Weather Backlash" in line for line in logs(combat._load_session(mid).engine))


# ------------------------------------------------------------------ AUTO13f1 regressions for the review findings
def test_dry_shroud_still_poisons_a_poison_resistant_creature(tmp_path):
    """"creatures immune to poison are immune to the Poisoned condition from this Shroud": immunity, not Resistance.

    A creature that merely *resists* poison is still poisoned by the dust, so a Resistance must not be read as the
    printed immunity.
    """
    combat, table, mid = arena(tmp_path, list(SPHERE), "shroud-dry-resistant", dc=40)
    owner_turn(combat, table, mid, tmp_path, idle=True)
    engine = combat._load_session(mid).engine
    engine._add_modifier(engine.state.actors[FOE], "system:test", "damage_resistance", "ADD", "POISON", "SELF",
                         expires_on="UNTIL_REMOVED")
    commit(combat, table, mid, tmp_path, action(combat, mid, "Cloud Shroud (any creature)", FOE),
           choose=choose_shroud("dry"))
    engine = combat._load_session(mid).engine
    assert any(c.condition_id == "condition:typed.poisoned"
               for c in engine.state.actors[FOE].conditions.values()), \
        "poison Resistance alone does not make a creature immune to the Dry Shroud's dust"


@pytest.mark.parametrize(("field", "poisoned"), [("damage_resistance", True), ("damage_immunity", False)])
def test_dry_shroud_poison_reads_immunity_not_resistance(tmp_path, field, poisoned):
    """The Dry Shroud's own printed failure row, on a real engine: only a poison Immunity withholds the Poisoned.

    The saved-fight table path cannot hold an in-memory Immunity (a commit reloads the fight from saved state), so
    this runs the Shroud's real failure rows through the real typed pipeline against a real engine instead, which is
    where the printed "immune to poison are immune" reader lives.
    """
    from combat import typed_executor as te
    from combat.ext import weather_shroud

    combat, table, mid = arena(tmp_path, list(SPHERE), f"shroud-dry-imm-{field}", dc=40)
    engine = combat._load_session(mid).engine
    target = engine.state.actors[FOE]
    engine._add_modifier(target, "system:test", field, "ADD", "POISON", "SELF", expires_on="UNTIL_REMOVED")
    # Dry's Shroud rows carry no realm step (only Heat's and Thunder's scale), so any Cultivation Level prints them.
    printed = weather_signs.shroud_rows("dry", 1)
    source = next(sid for sid, act in engine.action_catalog.items()
                  if ((act.parameters or {}).get("typed") or {}).get("source") == weather_shroud.BASE)
    ctx = weather_shroud._context(engine, engine.state.actors[ME], source, target, "dry")
    te.run_effects(ctx, list(printed["fail"]))
    has = any(c.condition_id == "condition:typed.poisoned" for c in target.conditions.values())
    assert has is poisoned, f"poison {field} must {'not' if poisoned else ''} withhold the Dry Shroud's Poisoned"


def test_weatherproof_thunder_resistance_is_the_chosen_type_and_survives_reload(tmp_path):
    """"Thunder grants Resistance to lightning or thunder damage, chosen when the Mantle is placed"."""
    from combat.gate5_service import CombatService
    from tests.h1_support import ROOT

    combat, table, mid = arena(tmp_path, MANTLE_TALENTS, "weatherproof-thunder", ask_actors=(ALLY,), maximum_rounds=8)
    picked = {}
    tally = {}

    def consenting(prompt):
        source = prompt["context"]["reaction_source_id"]
        tally.setdefault("seen", []).append(source)
        if source == "choice:willing.consent":
            return ["accept"]
        if source == weather_mantle.WEATHERPROOF_SIGN_CHOICE:
            return ["thunder"]
        options = [o["id"] for o in (prompt.get("choice") or {}).get("options", [])]
        offered = [o for o in options if o in ("LIGHTNING", "THUNDER")]
        if offered:
            picked["value"] = offered[0]
            return [offered[0]]
        return choose_mantle("thunder")(prompt)

    owner_turn(combat, table, mid, tmp_path, idle=True)
    commit(combat, table, mid, tmp_path, action(combat, mid, "Sky Mantle", ALLY), choose=consenting)
    # Reloaded from the saved fight, so the stored Resistance is a committed integer/string, not memory.
    data = mantle_of(CombatService(ROOT, tmp_path)._load_session(mid).engine, ALLY)[0].data
    assert data["weatherproof"] == picked["value"], "the printed choice is stored on the Mantle"
    assert data["weatherproof"] in data["rule"]["damage_resistances"], "and granted as its Resistance"
    other = "THUNDER" if data["weatherproof"] == "LIGHTNING" else "LIGHTNING"
    assert other not in data["rule"]["damage_resistances"], "only the chosen one is granted"


@pytest.mark.parametrize(("cl", "three_more"), [(3, False), (5, True)])
def test_shared_weather_favor_compiles_the_printed_recipients(tmp_path, cl, three_more):
    """"1 additional CP to target one additional willing creature", three more at Foundation Realm and above."""
    combat, table, mid = arena(tmp_path, MANTLE_TALENTS, f"favor-cl{cl}", cl=cl, maximum_rounds=6)
    owner_turn(combat, table, mid, tmp_path, idle=True)
    names = [c.display_name for c in combat._load_session(mid).engine.legal_candidates()]
    assert "Sky Mantle + Shared Weather Favor (one more)" in names
    assert ("Sky Mantle + Shared Weather Favor (three more)" in names) is three_more

# ------------------------------------------------- AUTO13r1 regressions: one cast, one sign; the printed subjects
def _shared_favor_cast(combat, mid, label="one more"):
    return next(c for c in combat._load_session(mid).engine.legal_candidates()
                if f"Shared Weather Favor ({label})" in c.display_name and ME in c.target_ids).candidate_id


def test_shared_weather_favor_resolves_the_sign_once_for_the_whole_cast(tmp_path):
    """"All targets must receive the same Weather Sign": one cast asks once, and both recipients get that one sign."""
    combat, table, mid = arena(tmp_path, MANTLE_TALENTS, "favor-once", ask_actors=(ALLY,), maximum_rounds=8)
    tally = {}

    def chooser(prompt):
        source = prompt["context"]["reaction_source_id"]
        tally.setdefault("seen", []).append(source)
        if source == weather_mantle.WEATHERPROOF_SIGN_CHOICE:
            return ["wind"]
        if source == "choice:willing.targets":
            return [ALLY]
        if source == "choice:willing.consent":
            return ["accept"]
        # A second sign question would be answered Heat, so a recipient on Heat proves it was asked twice.
        return choose_mantle("wind" if source == weather_mantle.SIGN_CHOICE else "heat")(prompt)

    owner_turn(combat, table, mid, tmp_path, idle=True)
    commit(combat, table, mid, tmp_path, _shared_favor_cast(combat, mid), choose=chooser)
    engine = combat._load_session(mid).engine
    assert tally["seen"].count(weather_mantle.SIGN_CHOICE) == 1, \
        f"one cast asks for its sign once, not once per recipient: {tally['seen']}"
    assert mantle_of(engine, ME), "the chosen recipient is mantled"
    assert mantle_of(engine, ALLY), "the printed extra willing recipient is mantled too"
    assert weather_mantle.sign_of(mantle_of(engine, ME)[0]) == "wind"
    assert weather_mantle.sign_of(mantle_of(engine, ALLY)[0]) == "wind", "'All targets must receive the same Weather Sign'"
    held = engine.state.actors[ME].concentration
    assert held is not None, "the cast holds Concentration"
    assert mantle_of(engine, ME)[0].data["concentration_started_sequence"] == held.started_sequence
    assert mantle_of(engine, ALLY)[0].data["concentration_started_sequence"] == held.started_sequence, \
        "both Mantles ride the one Concentration the cast started"


def test_shared_weather_favor_pays_the_forced_sign_point_once(tmp_path):
    """"Use an active sign or spend 1 additional Cultivation Point to force it": once per cast, not once per recipient."""
    combat, table, mid = arena(tmp_path, MANTLE_TALENTS, "favor-force", ask_actors=(ALLY,), maximum_rounds=8)
    owner_turn(combat, table, mid, tmp_path, idle=True)
    engine = combat._load_session(mid).engine
    before = engine.state.actors[ME].resources["resource:core.qi"]
    commit(combat, table, mid, tmp_path, _shared_favor_cast(combat, mid),
           choose=mantle_chooser("wind", "force", extra=[ALLY]))
    engine = combat._load_session(mid).engine
    # 1 CP for the cast, 1 more for the forced sign, 1 more for Shared Weather Favor's extra recipient.
    assert engine.state.actors[ME].resources["resource:core.qi"] == before - 3, \
        "the forced sign costs 1 Cultivation Point however many recipients the cast reaches"
    assert all(int(mantle_of(engine, who)[0].data["forced"]) == 1 for who in (ME, ALLY))


def test_shared_weather_favor_declined_extra_reaches_only_the_first_recipient(tmp_path):
    """A refused extra recipient costs nothing further and the first recipient still has its Mantle."""
    combat, table, mid = arena(tmp_path, MANTLE_TALENTS, "favor-decline", ask_actors=(ALLY,), maximum_rounds=8)
    owner_turn(combat, table, mid, tmp_path, idle=True)
    commit(combat, table, mid, tmp_path, _shared_favor_cast(combat, mid), choose=mantle_chooser("wind", extra=None))
    engine = combat._load_session(mid).engine
    assert weather_mantle.sign_of(mantle_of(engine, ME)[0]) == "wind", "the chosen recipient keeps its Mantle"
    assert not mantle_of(engine, ALLY), "a declined extra recipient is not wrapped"


def test_weatherproof_purchase_covers_one_sign_only(tmp_path):
    """"Choose one Weather Sign talent you know ... choosing a different Weather Sign each time": one sign per purchase."""
    combat, table, mid = arena(tmp_path, MANTLE_TALENTS, "weatherproof-one", ask_actors=(ALLY,), maximum_rounds=10)
    tally = {}
    owner_turn(combat, table, mid, tmp_path, idle=True)
    commit(combat, table, mid, tmp_path, action(combat, mid, "Sky Mantle", ALLY), choose=mantle_chooser("cold", tally=tally))
    engine = combat._load_session(mid).engine
    assert weather_mantle._weatherproof_signs(engine, engine.state.actors[ME]) == ["cold"]
    next_owner_turn(combat, table, mid, tmp_path)
    # A second cast on another sign: owning the talent must not hand that sign's Resistance out as well.
    commit(combat, table, mid, tmp_path, action(combat, mid, "Sky Mantle", ALLY), choose=mantle_chooser("rain", tally=tally))
    engine = combat._load_session(mid).engine
    assert tally["seen"].count(weather_mantle.WEATHERPROOF_SIGN_CHOICE) == 1, \
        "the purchase's sign is chosen once and kept, not asked again for a different sign"
    assert weather_mantle.sign_of(mantle_of(engine, ALLY)[0]) == "rain"
    assert not (mantle_of(engine, ALLY)[0].data["rule"].get("damage_resistances") or []), \
        "a Rain Mantle gains nothing from a purchase already spent on Cold Sign"


def test_weatherproof_wind_resists_nonmagical_ranged_weapon_damage_only(tmp_path):
    """Wind's Weatherproof benefit names the attack, so it must not become a blanket Resistance."""
    combat, table, mid = arena(tmp_path, MANTLE_TALENTS, "weatherproof-wind", ask_actors=(ALLY,), maximum_rounds=8)
    owner_turn(combat, table, mid, tmp_path, idle=True)
    commit(combat, table, mid, tmp_path, action(combat, mid, "Sky Mantle", ALLY), choose=mantle_chooser("wind"))
    engine = combat._load_session(mid).engine
    ally = engine.state.actors[ALLY]
    shot, melee = _weapon_actions(engine)
    assert weather_mantle.weatherproof_defense(engine, ally, "PIERCING", shot, FOE), \
        "Resistance to nonmagical ranged weapon damage"
    assert not weather_mantle.weatherproof_defense(engine, ally, "PIERCING", melee, FOE), \
        "a melee weapon attack is not covered"
    assert not weather_mantle.weatherproof_defense(engine, ally, "PIERCING", {**shot, "mundane": False}, FOE), \
        "a magical ranged weapon attack is not covered"
    assert not weather_mantle.weatherproof_defense(engine, ally, "PIERCING",
                                                   {**shot, "effects": [{"type": "attack", "attack_kind": "spell"}]}, FOE), \
        "a ranged spell is not a ranged weapon attack"
    from combat import typed_reactions

    source = next(sid for sid, action in engine.action_catalog.items()
                  if ((action.parameters or {}).get("typed") or {}) is shot)
    assert typed_reactions.defend(engine, ally, 10, "PIERCING", source, FOE) == 5, \
        "the printed Resistance really halves a nonmagical ranged weapon hit"
    assert not (mantle_of(engine, ALLY)[0].data["rule"].get("damage_resistances") or []), \
        "Wind's benefit is not stored as a whole damage-type Resistance"
    # RESISTR8: the Defences card lists the real Wind benefit with its printed qualifier, and only for the wearer
    card = typed_reactions.defense_display(engine, ally)
    [row] = [r for r in card["resistances"] if "ranged weapon" in (r.get("note") or "")]
    assert row["damage_type"] == "All damage types", "every type a qualifying attack deals, fire arrows included"
    assert row["note"] == "only against nonmagical ranged weapon attacks"
    assert not any("ranged weapon" in (r.get("note") or "")
                   for r in typed_reactions.defense_display(engine, engine.state.actors[FOE])["resistances"])


def _weapon_actions(engine):
    """The fight's own real weapon attacks: one thrown (ranged) and the same weapon's melee blow."""
    ranged = melee = None
    for action in engine.action_catalog.values():
        typed = ((action.parameters or {}).get("typed") or {})
        if not typed.get("weapon"):
            continue
        if int(typed.get("range_ft") or 0) > 5 and ranged is None:
            ranged = typed
        elif not typed.get("range_ft") and melee is None:
            melee = typed
    assert ranged is not None and melee is not None, "the kit's dagger is both thrown and melee"
    return ranged, melee


def test_thunder_mantle_advantage_only_on_its_printed_hazards(tmp_path):
    """"saves against being Deafened, Stunned or knocked Prone by thunder, lightning or storm effects" -- and no others."""
    combat, table, mid = arena(tmp_path, MANTLE_TALENTS, "mantle-thunder-saves", ask_actors=(ALLY,), maximum_rounds=8)
    owner_turn(combat, table, mid, tmp_path, idle=True)
    commit(combat, table, mid, tmp_path, action(combat, mid, "Sky Mantle", ALLY), choose=mantle_chooser("thunder"))
    engine = combat._load_session(mid).engine
    ally = engine.state.actors[ALLY]
    ordinary = _save_ctx(engine)  # a save from outside the Weather sphere: only the sign's own printed benefit can answer it
    storm = _save_ctx(engine, "thunder")
    # The same save, from an effect that names itself a thunder, lightning or storm effect -- the printed line's limit.
    named_thunder = _save_ctx(engine, source="SPELL_THUNDEROUS_CURSE")
    lightning = _save_ctx(engine, source="SPELL_LIGHTNING_LASH")

    def advantage(ctx, named):
        return (weather_mantle.defensive_weather(ctx, ally, "CON", named) or {}).get("modes") or []

    # Positive: the printed hazards, from a source that is thunder, lightning or storm.
    assert "ADVANTAGE" in advantage(named_thunder, {"deafened"}), "a save that a thunder effect would Deafen"
    assert "ADVANTAGE" in advantage(named_thunder, {"stunned"}), "a save that a thunder effect would Stun"
    assert "ADVANTAGE" in advantage(lightning, {"stunned"}), "a save that lightning would Stun"
    assert "ADVANTAGE" in advantage(_save_ctx(engine, source="SPELL_STORM_CALL"), {"prone_by_storm"}), \
        "a save that a storm effect would knock Prone"
    assert "ADVANTAGE" in advantage(named_thunder, {"deafened", "damage:lightning"}), \
        "an effect that deals lightning damage and would Deafen is Deafening by lightning"
    # Negative: an effect from elsewhere that would Deafen, Stun or knock Prone is none of the printed hazards.
    assert "ADVANTAGE" not in advantage(ordinary, {"deafened"}), \
        "a save an unrelated effect would Deafen is not Deafened by thunder, lightning or storm"
    assert "ADVANTAGE" not in advantage(ordinary, {"stunned"}), \
        "a save an unrelated effect would Stun is not Stunned by thunder, lightning or storm"
    assert "ADVANTAGE" in advantage(ordinary, {"prone_by_storm"}), \
        "prone_by_storm is the engine's own storm marker, so it names a storm knockdown and is covered by name"
    assert "ADVANTAGE" not in advantage(ordinary, {"damage:lightning"}), \
        "a plain save against lightning damage does none of those things"
    assert "ADVANTAGE" not in advantage(ordinary, {"damage:fire"}), "and nothing else either"
    # Defensive Weather is a different printed line: a Weather effect whose sign matches the Mantle's.
    assert "ADVANTAGE" in advantage(storm, {"damage:lightning"}), \
        "a Lightning Sign Shroud's save matches the Thunder Mantle's sign"


def test_heat_weatherproof_cold_weather_advantage_is_not_every_cold_save(tmp_path):
    """"Advantage on saves against cold weather hazards": cold *weather*, not an ordinary cold-damage spell."""
    combat, table, mid = arena(tmp_path, MANTLE_TALENTS, "mantle-heat-coldweather", cl=12, ask_actors=(ALLY,),
                               maximum_rounds=8)
    owner_turn(combat, table, mid, tmp_path, idle=True)
    commit(combat, table, mid, tmp_path, action(combat, mid, "Sky Mantle", ALLY), choose=mantle_chooser("heat"))
    engine = combat._load_session(mid).engine
    ally = engine.state.actors[ALLY]
    assert "cold_weather" in (mantle_of(engine, ALLY)[0].data.get("save_advantage") or ()), \
        "Heat's Weatherproof benefit names the cold-weather saves on the Mantle it placed"

    def advantage(ctx, named):
        return (weather_mantle.defensive_weather(ctx, ally, "CON", named) or {}).get("modes") or []

    ordinary = _save_ctx(engine)
    blizzard = _save_ctx(engine, source="SPELL_BLIZZARD")
    assert "ADVANTAGE" in advantage(blizzard, {"damage:cold"}), "a save against cold weather is covered"
    assert "ADVANTAGE" in advantage(blizzard, {"cold_weather"}), "and so is one the engine named as a cold-weather hazard"
    assert "ADVANTAGE" not in advantage(ordinary, {"damage:cold"}), \
        "an ordinary cold-damage spell is not a cold-weather hazard"
    # The printed line names cold *weather*, so an ordinary technique whose own name merely contains one of those words
    # is not one: a blizzard is weather, "Frost Bolt", "Freezing Touch" and "Glacial Edge" are three techniques that
    # happen to deal cold damage.
    for source, name in (("SPELL_FROST_BOLT", "Frost Bolt"), ("SPELL_FREEZING_TOUCH", "Freezing Touch"),
                         ("SPELL_GLACIAL_EDGE", "Glacial Edge"), ("SPELL_FROST_SHEATHE", "Frost-Sheathed Guard")):
        assert "ADVANTAGE" not in advantage(_save_ctx(engine, source=source), {"damage:cold"}), \
            f"{name} deals cold damage but is not cold weather"
        assert "cold_weather" not in weather_signs.source_kinds(source, name), \
            f"{name} must not be read as a cold-weather hazard from its own words"
    for word in ("blizzard", "ice storm", "cold front", "freezing wind"):
        assert "cold_weather" in weather_signs.source_kinds(f"SPELL_{word.upper().replace(' ', '_')}", word), \
            f"an unambiguous hazard phrase, {word}, is cold weather"
    # A rider is judged on its own cause, not on a weather-named parent action it hangs off.
    assert "ADVANTAGE" not in advantage(_save_ctx(engine, source="SPELL_FROST_LANCE", display_name="Gather Storm"),
                                        {"damage:cold"}), \
        "a rider under a parent called Gather Storm is still only a cold-damage save"
    # A Cold Sign effect is the other printed line (Heat's Mantle at Core Formation), and the two do not merge: the sign
    # line answers a save that names the Cold Sign, while the Weatherproof line stays limited to cold-weather sources.
    cold_sign = _save_ctx(engine, "cold")
    assert "ADVANTAGE" in advantage(cold_sign, {"damage:cold"}), \
        "the Cold Sign line still covers a Cold Sign Shroud's own throw"
    assert weather_signs.hazard_matches(["cold_sign"], {"damage:cold"}, save_sign="cold"), \
        "a save that names the Cold Sign is a Cold Sign effect"
    assert not weather_signs.hazard_matches(["cold_weather"], {"damage:cold"}, save_sign="cold"), \
        "naming the Cold Sign is not by itself naming cold weather, so it must not pick up the Weatherproof line"
    # A printed Cold Sign Shroud *is* cold weather, and that is provenance the engine can read on its own context. This
    # is the isolated regression for the cold-weather *category* path: the save is given no condition and no damage type
    # at all, so ``hazard_matches`` can only answer it through its ``category`` branch reading ``source_kinds``. Remove
    # either half and this fails here, which no service-level test can show, because Defensive Weather would still hand
    # the same real save its Advantage.
    assert weather_signs.hazard_matches(["cold_weather"], set(), save_sign="cold",
                                        kinds=weather_signs.source_kinds("action:weather.cloud_shroud",
                                                                        "Cloud Shroud (any creature)",
                                                                        "cold", set(), weather_source=True)), \
        "a Cold Sign Shroud's own throw is a cold-weather hazard, so Heat's Weatherproof benefit covers it"


#: A rider that causes a save and carries no weather of its own. Neither id contains any word the classifier reads, so
#: the only thing that could put either save in a printed hazard family is the *parent* action's name.
NEUTRAL_COLD_RIDER, NEUTRAL_DEAFENING_RIDER = "SPELL_PALE_LANCE", "SPELL_HUSHING_WHISPER"


def test_a_cold_damage_rider_does_not_borrow_cold_weather_from_a_parent_called_blizzard_prayer(tmp_path):
    """A rider is judged on its own cause: a parent called "Blizzard Prayer" does not make its rider cold weather.

    Heat's Weatherproof benefit is printed as "Advantage on saves against cold weather hazards", and
    ``weather_signs.source_kinds`` is what decides whether a pending save is against cold weather. A save caused by a
    named rider carries *that rider's* id as its source, so the parent action's display name is never read: the
    cold-damage lance below is still only a cold-damage save, even though the action it hangs off is called
    "Blizzard Prayer" and "blizzard" is one of the printed cold-weather phrases.

    The premise assertion below is what makes this an independent regression rather than another cold-damage case: it
    shows the parent's name really is enough to place a source in the cold-weather family. Restore the parent-name
    suppression alone -- the ``ability = "" if rider else ...`` line in ``weather_mantle._cause`` -- and the negative
    assertion below turns into an Advantage. The positive is here too, so a classifier that simply refused every source
    would fail this test as well.
    """
    combat, table, mid = arena(tmp_path, MANTLE_TALENTS, "rider-provenance-cold", cl=12, ask_actors=(ALLY,),
                               maximum_rounds=8)
    owner_turn(combat, table, mid, tmp_path, idle=True)
    commit(combat, table, mid, tmp_path, action(combat, mid, "Sky Mantle", ALLY),
           choose=mantle_chooser("heat", purchase="heat"))
    engine = combat._load_session(mid).engine
    ally = engine.state.actors[ALLY]

    def advantage(ctx, named):
        return (weather_mantle.defensive_weather(ctx, ally, "CON", named) or {}).get("modes") or []

    # Premise: the rider's own words say nothing, and the parent's words are exactly what borrowing would have read.
    assert weather_signs.source_kinds(NEUTRAL_COLD_RIDER, "") == set(), \
        "the rider's own id names no cold weather, so it is in no printed hazard family"
    assert weather_signs.source_kinds(NEUTRAL_COLD_RIDER, "Blizzard Prayer") == {"cold_weather"}, \
        "the parent's name is a printed cold-weather phrase, which is precisely the borrowing the fix refuses"
    # Positive: a rider that is itself a blizzard is a cold-weather hazard, parent or no parent.
    assert "ADVANTAGE" in advantage(_save_ctx(engine, source="SPELL_BLIZZARD"), {"damage:cold"}), \
        "a save caused by an actual blizzard is a cold-weather hazard"
    assert "ADVANTAGE" in advantage(_save_ctx(engine, source="SPELL_BLIZZARD", display_name="Blizzard Prayer"),
                                    {"damage:cold"}), \
        "and its own cause is still what says so, whatever the parent action happens to be called"
    # Negative: the rider causes the save, so the parent's weather is not the save's weather.
    assert "ADVANTAGE" not in advantage(_save_ctx(engine, source=NEUTRAL_COLD_RIDER, display_name="Blizzard Prayer"),
                                        {"damage:cold"}), \
        "a cold-damage rider under a parent called Blizzard Prayer is still only a cold-damage save"


def test_a_deafening_rider_does_not_borrow_thunder_from_a_parent_called_gather_storm(tmp_path):
    """The same provenance rule on Thunder's printed line: "by thunder, lightning or storm effects".

    Thunder's Mantle benefit covers a save against being Deafened "by thunder, lightning or storm effects", and
    ``weather_signs.source_kinds`` places a source in that thunder family from the words of the effect that caused the
    save. A rider that merely *would* Deafen says nothing about thunder, and the parent action it hangs off does not
    speak for it either: "Gather Storm" contains "storm", so reading the parent's name here would wrongly hand the
    rider Thunder's printed Advantage. Restore the parent-name suppression in ``weather_mantle._cause`` alone and the
    negative assertion below fails.
    """
    combat, table, mid = arena(tmp_path, MANTLE_TALENTS, "rider-provenance-deafened", ask_actors=(ALLY,),
                               maximum_rounds=8)
    owner_turn(combat, table, mid, tmp_path, idle=True)
    commit(combat, table, mid, tmp_path, action(combat, mid, "Sky Mantle", ALLY), choose=mantle_chooser("thunder"))
    engine = combat._load_session(mid).engine
    ally = engine.state.actors[ALLY]

    def advantage(ctx, named):
        return (weather_mantle.defensive_weather(ctx, ally, "CON", named) or {}).get("modes") or []

    # Premise: the rider's own words say nothing about thunder, and the parent's name is all it would take.
    assert weather_signs.source_kinds(NEUTRAL_DEAFENING_RIDER, "") == set(), \
        "the rider's own id names no thunder, lightning or storm effect, so it is in no printed hazard family"
    assert weather_signs.source_kinds(NEUTRAL_DEAFENING_RIDER, "Gather Storm") == {"thunder"}, \
        "'Gather Storm' contains 'storm', which is exactly the parent-name borrowing the fix refuses"
    # Positive: an effect that really is thunder is covered, whether or not it hangs off a grand-named parent.
    assert "ADVANTAGE" in advantage(_save_ctx(engine, source="SPELL_THUNDEROUS_CURSE"), {"deafened"}), \
        "a save caused by an actual thunder effect is Deafened by thunder"
    # Negative: an unrelated effect that would Deafen is left alone, however its parent action is named.
    assert "ADVANTAGE" not in advantage(_save_ctx(engine, source=NEUTRAL_DEAFENING_RIDER, display_name="Gather Storm"),
                                        {"deafened"}), \
        "a save an unrelated effect would Deafen is not Deafened by a storm it never heard of"
    assert "ADVANTAGE" not in advantage(_save_ctx(engine, source=NEUTRAL_DEAFENING_RIDER,
                                                  display_name="Call the Storm Down"), {"deafened"}), \
        "and the rule is about the cause, not about which weather words the parent happens to use"


def _save_ctx(engine, sign_id="", source="", display_name=""):
    """A typed context for a pending save, as weather_shroud builds it for a Shroud's throw.

    With no sign (and no Weather sphere on it) the save is one from somewhere else, so a sign's own printed benefit is the
    only thing that can answer it. ``source`` names the effect causing the save, which is what the printed thunder and
    cold-weather benefits are limited to ("by thunder, lightning or storm effects", "cold weather hazards"): it becomes
    the context's ``effect_source``, so it is exactly the "a named rider caused this save" case -- a parent action's own
    display name then means nothing. ``display_name`` renames the parent action, which is how the other half is checked:
    a rider is not given its parent's weather just because the parent is called something grand.
    """
    from combat import typed_executor as te
    from combat.ext import weather_shroud

    owner = engine.state.actors[ME]
    if sign_id:
        action = engine.action_catalog[weather_shroud_action(engine)]
    else:
        action = next(a for a in engine.action_catalog.values()
                      if ((a.parameters or {}).get("typed") or {}).get("weapon"))
    if display_name:
        action = action.model_copy(update={"display_name": display_name})
    typed = {"source": action.source_definition_id, "effects": [], "weapon": None,
             "numbers": dict(((action.parameters or {}).get("typed") or {}).get("numbers") or {}),
             "duration": {"kind": "instant"}, "riders": []}
    if sign_id:
        typed.update(sphere=weather_signs.SPHERE, weather_sign=sign_id)
    return te.Context(engine, owner, action, None, typed, [], None, effect_source=str(source or ""))


def weather_shroud_action(engine):
    from combat.ext import weather_shroud

    return next(sid for sid, action in engine.action_catalog.items()
                if ((action.parameters or {}).get("typed") or {}).get("source") == weather_shroud.BASE)


def _saves(engine, who, source):
    """Every SAVE_ROLLED the fight recorded for one creature from one source ability, in order."""
    return [e for e in engine.events if e.event_type == "SAVE_ROLLED" and e.actor_id == who
            and str(e.source_definition_id).split("#")[0] == str(source).split("#")[0]]


def _own_save_action(engine, who, name):
    """The catalog source id of one named action in one creature's own bundle (the fight's real compiled action)."""
    return next(sid for sid, action in engine.action_catalog.items()
                if action.owner_id == who and action.display_name == name)


def test_thunder_sign_saves_reach_a_real_deafening_thunder_save_and_nothing_else(tmp_path):
    """"saves against being Deafened, Stunned or knocked Prone by thunder, lightning or storm effects", for real.

    The saving throw here is the fight's own: the east foe, a Brute, claps Thunderous Clap and the mantled ally makes
    the Constitution save that print describes, at the table, committed and reloaded after every step. Nothing about
    that save is Weather -- a Brute technique that deals thunder damage and Deafens -- so Sky Mantle's own
    "Advantage if the Mantle's sign matches or opposes the effect's sign" cannot answer it, and only the Thunder Sign's
    printed saves can. The same fight then has the owner wrap the ally in a Cold Sign Shroud, whose save is a real save
    of the mantled creature's own that gets nothing from the Thunder Mantle.
    """
    from combat.gate5_service import CombatService
    from tests.h1_support import ROOT

    combat, table, mid = arena(tmp_path, MANTLE_TALENTS, "mantle-thunder-real-save", ask_actors=(ALLY, FOE), dc=2,
                               maximum_rounds=14, foe_talents=["TAL_BRUTE_THUNDEROUS_CLAP"])
    engine = combat._load_session(mid).engine
    clap = _own_save_action(engine, FOE, "Thunderous Clap")
    shroud = weather_shroud_action(engine)
    owner_turn(combat, table, mid, tmp_path, idle=True)
    commit(combat, table, mid, tmp_path, action(combat, mid, "Sky Mantle", ALLY), choose=mantle_chooser("thunder"))
    next_owner_turn(combat, table, mid, tmp_path)
    commit(combat, table, mid, tmp_path, action(combat, mid, "Cloud Shroud", ALLY), choose=choose_shroud("cold"))
    claps = clapper(combat, table, mid, tmp_path)
    assert claps, "the east foe never got to clap in this fight"
    engine = CombatService(ROOT, tmp_path)._load_session(mid).engine
    deafening = _saves(engine, ALLY, clap)
    assert deafening, "the Thunderous Clap's Constitution save was rolled against the mantled ally"
    assert [e.payload.get("mode") for e in deafening] == ["ADVANTAGE"] * len(deafening), (
        "'against being Deafened ... by thunder, lightning or storm effects': a real thunder save is answered by the "
        f"Thunder Mantle: {[(e.payload.get('mode'), e.payload.get('reason')) for e in deafening]}")
    # The same source grants no Advantage to the other recipients wearing no
    # Thunder Mantle: the benefit follows the Mantle, not the roll.
    # Owner area-recipient override: harmful martial areas affect enemies,
    # excluding the user and its ally. Both hostile recipients still save.
    for spared in (FOE, FOE2):
        assert not _saves(engine, spared, clap)
    for other in (ME,):
        same = _saves(engine, other, clap)
        assert same, f"{other} stands in the clap's area and makes the same real save"
        assert all(e.payload.get("mode") != "ADVANTAGE" for e in same), \
            f"no Thunder Mantle, no Thunder benefit: {[e.payload.get('mode') for e in same]}"
    cold = _saves(engine, ALLY, shroud)
    assert cold, "the Cold Sign Shroud's own throw was rolled against the same creature"
    assert all(e.payload.get("mode") != "ADVANTAGE" for e in cold), (
        "a Cold Sign Shroud's throw is neither a thunder, lightning nor storm effect, so the Thunder Mantle's printed "
        f"saves do not touch it: {[e.payload.get('mode') for e in cold]}")


def _typed_rows(node, wanted_type):
    """Every row of one effect type anywhere inside a compiled mechanic's typed tree."""
    found = []
    if isinstance(node, dict):
        if node.get("type") == wanted_type:
            found.append(node)
        for value in node.values():
            found.extend(_typed_rows(value, wanted_type))
    elif isinstance(node, list):
        for value in node:
            found.extend(_typed_rows(value, wanted_type))
    return found


def test_every_rolled_condition_save_names_the_deafening_it_would_inflict():
    """"saves against being Deafened ... by thunder, lightning or storm effects" needs to see a rolled Deafening.

    A pending saving throw is named after the conditions its failure branch would inflict. The engine reads that
    naming off ordinary ``condition`` rows; a plug-in effect that applies a condition under its own row type says so
    through ``pending_effects`` (see combat/ext/__init__.py, "Custom-effect consequence metadata"). Thunderous Clap
    rolls how long its Deafening lasts with ``rolled_condition_rounds``, so its row is not an ordinary condition row:
    with nothing declared, the save is named nothing, the Thunder Mantle cannot recognise the Deafening it prints
    against, and the table rolls a real thunder save NORMAL. That is true of the whole effect type, not of one
    talent, so every row of it in the built authority is checked here.
    """
    from combat.ext import weather_signs
    from combat.factory_compiler import TYPED_AUTHORITY

    authority = json.loads(TYPED_AUTHORITY.read_text())
    rows = _typed_rows(authority.get("mechanics"), "rolled_condition_rounds")
    assert rows, "the built authority no longer holds a rolled_condition_rounds row to check"

    thunder = weather_signs.sign("thunder")["mantle"]
    for row in rows:
        condition = str(row.get("condition") or "")
        # Named exactly the way combat.typed_executor.typed_save_modifiers names a pending save.
        declared = [str(preview.get("condition") or "")
                    for preview in row.get("pending_effects") or [] if preview.get("type") == "condition"]
        assert condition and condition in declared, (
            f"a rolled {condition or 'condition'} save must declare it in pending_effects, or nothing that reads the "
            f"save's consequences can see it; this row declares {declared}")
        # ...and the Thunder Mantle does answer a thunder save named for that condition, which is the printed line.
        thunder_saves = [str(value).lower() for value in thunder.get("save_advantage") or ()]
        kinds = weather_signs.source_kinds(row.get("evidence") or "", weather_source=False)
        assert weather_signs.hazard_matches(thunder_saves, {condition}, kinds=kinds | {"thunder"}), (
            f"the Thunder Mantle's printed {thunder_saves} must answer a thunder save named {condition}")


def clapper(combat, table, mid, tmp_path, *, limit=40):
    """Have the east foe spend its Thunderous Clap, on its own turn, until the ability is used."""
    for _ in range(limit):
        engine = combat._load_session(mid).engine
        if engine.state.terminal_result is not None or not legal_candidates(engine):
            break
        if engine.state.current_actor_id == FOE:
            # The button names who else the area catches, so it is matched by its leading words.
            cid = next((c.candidate_id for c in engine.legal_candidates()
                        if c.display_name.startswith("Thunderous Clap")), None)
            if cid is not None:
                commit(combat, table, mid, tmp_path, cid)
                return True
        commit(combat, table, mid, tmp_path)
    return False


def test_heat_weatherproof_cold_weather_answers_a_real_cold_sign_save_after_a_reload(tmp_path):
    """"Advantage on saves against cold weather hazards" -- on a real saving throw, through a commit and a reload.

    Cultivation Level 4, which is the Mortal realm, so the Heat Mantle's *own* printed benefit stores no saving
    throws (its Cold Sign line begins at Core Formation) and the stored list is the Weatherproof purchase's line on its
    own. The saving throw is the fight's own: the owner's Cold Sign Cloud Shroud, whose effect is cold weather, thrown
    on the creature wearing the Heat Mantle.

    This is an integration test of that whole chain -- stored benefit, a real throw, the recorded roll, and a fresh load
    of the saved fight -- and deliberately *not* an isolated test of the cold-weather category. Defensive Weather is a
    second printed line that answers this very save ("the Mantle's sign matches or opposes the effect's sign", and heat
    opposes cold), so the Advantage recorded here does not by itself prove which line granted it. The category path is
    isolated on its own, against the shared sign table, by
    ``test_heat_weatherproof_cold_weather_advantage_is_not_every_cold_save``; this test adds the part that table-level
    check cannot: that a real rolled save survives a table commit and a reload with the benefit still attached.
    """
    from combat.gate5_service import CombatService
    from tests.h1_support import ROOT

    combat, table, mid = arena(tmp_path, MANTLE_TALENTS, "weatherproof-heat-real-save", cl=4, ask_actors=(ALLY,),
                               dc=2, maximum_rounds=12)
    owner_turn(combat, table, mid, tmp_path, idle=True)
    commit(combat, table, mid, tmp_path, action(combat, mid, "Sky Mantle", ALLY),
           choose=mantle_chooser("heat", purchase="heat"))
    engine = CombatService(ROOT, tmp_path)._load_session(mid).engine
    assert mantle_of(engine, ALLY)[0].data["save_advantage"] == ["cold_weather"], \
        "Mortal Realm: the Heat Mantle's own printed benefit adds no saves, so the stored list is the purchase's line"
    next_owner_turn(combat, table, mid, tmp_path)
    commit(combat, table, mid, tmp_path, action(combat, mid, "Cloud Shroud", ALLY), choose=choose_shroud("cold"))
    engine = CombatService(ROOT, tmp_path)._load_session(mid).engine
    throws = _saves(engine, ALLY, weather_shroud_action(engine))
    assert throws, "the Cold Sign Shroud's own throw was rolled against the mantled ally"
    assert all(e.payload.get("mode") == "ADVANTAGE" for e in throws), (
        "the whole chain works end to end -- a Cold Sign Shroud's throw is cold weather, so the Heat Mantle buys an "
        f"Advantage with it, and it is still there after the reload: "
        f"{[e.payload.get('mode') for e in throws]}")


def test_heat_weatherproof_cold_weather_ignores_a_real_ice_technique_save(tmp_path):
    """An ordinary cold-damage technique is not cold weather, even when it deals cold damage from a save of its own.

    The east foe is a real Ice cultivator and casts Crystal Weather Script on the creature wearing a Heat Mantle whose
    Weatherproof purchase covers the Heat Sign: a hostile creature starting its turn in that lattice makes a real
    Constitution save the engine names "damage:cold". The technique's own name contains "Weather", which is exactly why
    the printed line says cold *weather hazards* and not cold damage -- and this save must be made with no Advantage.
    """
    from combat.gate5_service import CombatService
    from tests.h1_support import ROOT

    combat, table, mid = arena(tmp_path, MANTLE_TALENTS, "weatherproof-heat-ice-save", cl=4, ask_actors=(ALLY, FOE),
                               dc=2, maximum_rounds=14, foe_talents=["TAL_ICE_CRYSTAL_WEATHER_SCRIPT"])
    engine = combat._load_session(mid).engine
    lattice = _own_save_action(engine, FOE, "Crystal Weather Script")
    owner_turn(combat, table, mid, tmp_path, idle=True)
    commit(combat, table, mid, tmp_path, action(combat, mid, "Sky Mantle", ALLY),
           choose=mantle_chooser("heat", purchase="heat"))
    engine = CombatService(ROOT, tmp_path)._load_session(mid).engine
    assert mantle_of(engine, ALLY)[0].data["save_advantage"] == ["cold_weather"]
    cast = False
    ally_square = None
    for _ in range(30):
        engine = combat._load_session(mid).engine
        if engine.state.terminal_result is not None or not legal_candidates(engine):
            break
        if engine.state.current_actor_id == FOE:
            spot = engine.state.actors[ALLY].position
            ally_square = (spot.x, spot.y)
            # The lattice is placed on a chosen square, so the button for the mantled creature's own square is the one
            # whose area will actually catch it.
            cid = next((c.candidate_id for c in engine.legal_candidates()
                        if c.display_name.startswith("Crystal Weather Script") and c.destination is not None
                        and (c.destination.x, c.destination.y) == ally_square), None)
            if cid is not None:
                commit(combat, table, mid, tmp_path, cid)
                cast = True
                continue
        if cast and _saves(combat._load_session(mid).engine, ALLY, lattice):
            break
        commit(combat, table, mid, tmp_path)
    assert cast, f"the Ice technique was never placed on the mantled creature's square {ally_square}"
    engine = CombatService(ROOT, tmp_path)._load_session(mid).engine
    throws = _saves(engine, ALLY, lattice)
    assert throws, (
        "the Ice technique's own hostile-start save was rolled against the mantled ally: "
        f"{[(e.source_definition_id, e.actor_id) for e in engine.events if e.event_type == 'SAVE_ROLLED']}")
    assert all(e.payload.get("mode") != "ADVANTAGE" for e in throws), (
        "'saves against cold weather hazards' does not cover an ordinary technique that deals cold damage: "
        f"{[e.payload.get('mode') for e in throws]}")


def test_heat_mantle_core_formation_advantage_on_a_real_cold_sign_save(tmp_path):
    """"at Core Formation it also has Advantage on saves against Cold Sign effects", including a Cold Sign Shroud's throw."""
    combat, table, mid = arena(tmp_path, MANTLE_TALENTS, "mantle-heat-coldsign", cl=12, ask_actors=(ALLY,),
                               maximum_rounds=10)
    owner_turn(combat, table, mid, tmp_path, idle=True)
    # The Heat Mantle and the Cold Shroud are on the same creature: "it also has Advantage on saves against Cold Sign
    # effects" is the mantled creature's own save.
    commit(combat, table, mid, tmp_path, action(combat, mid, "Sky Mantle", ALLY), choose=mantle_chooser("heat"))
    engine = combat._load_session(mid).engine
    assert "cold_sign" in mantle_of(engine, ALLY)[0].data["save_advantage"], "Core Formation adds the Cold Sign saves"
    next_owner_turn(combat, table, mid, tmp_path)
    commit(combat, table, mid, tmp_path, action(combat, mid, "Cloud Shroud", ALLY), choose=choose_shroud("cold"))
    engine = combat._load_session(mid).engine
    source = weather_shroud_action(engine).split("#")[0]
    throws = [e for e in engine.events if e.event_type == "SAVE_ROLLED"
              and str(e.source_definition_id).split("#")[0] == source and e.actor_id == ALLY
              and e.payload.get("mode") == "ADVANTAGE"]
    assert throws, ("a Cold Sign Shroud's throw names no condition, so its own sign is what identifies the save: "
                    + str([(e.source_definition_id, e.payload.get("mode")) for e in engine.events
                           if e.event_type == "SAVE_ROLLED"][:6]))


def test_cold_mantle_terrain_benefit_is_the_table_s_not_a_blanket_rule(tmp_path):
    """"difficult terrain caused by ice, snow, mud, shallow water, frost or slick ground": not every kind of difficult ground."""
    combat, table, mid = arena(tmp_path, MANTLE_TALENTS, "mantle-cold-terrain", ask_actors=(ALLY,), maximum_rounds=8)
    owner_turn(combat, table, mid, tmp_path, idle=True)
    commit(combat, table, mid, tmp_path, action(combat, mid, "Sky Mantle", ALLY), choose=mantle_chooser("cold"))
    engine = combat._load_session(mid).engine
    rule = mantle_of(engine, ALLY)[0].data["rule"]
    assert "ignore_difficult" not in rule, \
        "the engine's difficult-terrain reader answers yes or no for a creature, so it must not be granted for every surface"
    riders = " ".join(str(e.payload.get("rider") or "") for e in engine.events if e.event_type == "GM_RIDER")
    assert "ice, snow, mud, shallow water, frost or slick ground" in riders, \
        "the table is told which ground the printed benefit covers"
    assert "10 feet faster" in riders, "and about the printed bonus on top of it"


def test_forced_rain_mantle_resists_real_fire_damage_and_survives_reload(tmp_path):
    """"Resistance to fire damage ... while you force the sign with Cultivation Points", checked on a real damage packet.

    The one Weatherproof Mantle purchase is spent on the Cold Sign, so no talent hands the mantled creature fire
    Resistance: the halved fire packet below can only come from the forced Rain Mantle's own printed benefit.
    """
    from combat.gate5_service import CombatService
    from tests.h1_support import ROOT

    combat, table, mid = arena(tmp_path, MANTLE_TALENTS, "mantle-forced-rain", cl=12, maximum_rounds=10)
    owner_turn(combat, table, mid, tmp_path, idle=True)
    commit(combat, table, mid, tmp_path, action(combat, mid, "Sky Mantle", ME),
           choose=mantle_chooser("rain", "force", purchase="cold"))
    engine = CombatService(ROOT, tmp_path)._load_session(mid).engine
    data = mantle_of(engine, ME)[0].data
    assert "FIRE" in data["rule"]["damage_resistances"], "the forced sign carries its own printed Resistance"
    bought = {str(m.value) for m in engine.state.actors[ME].modifiers.values()
              if m.target_field == weather_mantle.WEATHERPROOF_FIELD}
    assert bought == {"cold"}, \
        f"the single Weatherproof purchase covers Cold, so nothing else supplies fire Resistance: {bought}"
    next_owner_turn(combat, table, mid, tmp_path)
    commit(combat, table, mid, tmp_path, action(combat, mid, "Cloud Shroud", ME), choose=choose_shroud("heat"))
    engine = CombatService(ROOT, tmp_path)._load_session(mid).engine
    packets = [e for e in engine.events if e.event_type == "DAMAGE_COMMITTED" and ME in (e.target_ids or ())
               and int((e.payload or {}).get("rolled_or_pending_damage") or 0) > 0]
    assert packets, "a Heat Shroud's own fire damage is committed against the mantled creature"
    assert all(int(e.payload["reduced_to"]) == int(e.payload["rolled_or_pending_damage"]) // 2 for e in packets), \
        "every fire packet the mantled creature took was halved by the forced Rain Mantle"


def test_dry_weatherproof_resistance_is_not_widened_to_all_necrotic_damage(tmp_path):
    """"necrotic damage from desiccation" cannot be a blanket necrotic Resistance, so the table judges it."""
    # Mortal Realm, so Dry's own Mantle has no printed necrotic Resistance of its own to confuse the reading.
    combat, table, mid = arena(tmp_path, MANTLE_TALENTS, "weatherproof-dry", cl=1, ask_actors=(ALLY,), maximum_rounds=8)
    owner_turn(combat, table, mid, tmp_path, idle=True)
    commit(combat, table, mid, tmp_path, action(combat, mid, "Sky Mantle", ALLY), choose=mantle_chooser("dry"))
    engine = combat._load_session(mid).engine
    assert not (mantle_of(engine, ALLY)[0].data["rule"].get("damage_resistances") or []), \
        "the printed half the engine cannot name is not granted as a whole damage type"
    riders = " ".join(str(e.payload.get("rider") or "") for e in engine.events if e.event_type == "GM_RIDER")
    assert "desiccation" in riders, "and the table is told what it must judge"


def test_thunder_mantle_grants_advantage_on_death_saving_throws(tmp_path):
    """"Advantage on death saving throws" (Thunder Sign's Mantle), read by combat/ext/life_state._modes."""
    from combat.ext import life_state
    from combat.gate5_service import CombatService
    from tests.h1_support import ROOT

    combat, table, mid = arena(tmp_path, MANTLE_TALENTS, "mantle-thunder-death", ask_actors=(ALLY,), maximum_rounds=8)
    owner_turn(combat, table, mid, tmp_path, idle=True)
    commit(combat, table, mid, tmp_path, action(combat, mid, "Sky Mantle", ALLY), choose=mantle_chooser("thunder"))
    # Committed and reloaded, so the printed rule the reader consults is the stored one.
    engine = CombatService(ROOT, tmp_path)._load_session(mid).engine
    ally, mantle = engine.state.actors[ALLY], mantle_of(engine, ALLY)[0]
    assert mantle.data["rule"]["death_save_mode"] == {"mode": "ADVANTAGE"}
    assert "ADVANTAGE" in [mode for mode, _ in life_state._modes(ally, engine)], \
        "the printed Advantage reaches the rules that roll a death saving throw"
    ally.life_state = "DYING"
    life_state.death_save(engine, ally, "test:thunder_mantle")
    saves = [r for r in engine.rolls if "death" in str(getattr(r, "reason", "")).lower()]
    assert saves and str(getattr(saves[-1], "mode", "")) == "ADVANTAGE", \
        f"and the death saving throw itself is made with Advantage: {[r.mode for r in saves]}"


def test_weather_backlash_burns_for_the_mantle_owners_proficiency_bonus(tmp_path):
    """"the attacker takes damage equal to *your* Proficiency Bonus": the Mantle owner's, not the attacker's."""
    combat, table, mid = arena(tmp_path, MANTLE_TALENTS, "backlash-owner-pb", ask_actors=(ALLY, FOE), ally_ac=6,
                               foe_pb=1, maximum_rounds=60)
    owner_turn(combat, table, mid, tmp_path, idle=True)
    commit(combat, table, mid, tmp_path, action(combat, mid, "Sky Mantle", ALLY), choose=mantle_chooser("heat"))
    engine = combat._load_session(mid).engine
    owner_pb = int(engine.state.actors[ME].proficiency_bonus)
    attacker_pb = int(engine.state.actors[FOE].proficiency_bonus)
    assert owner_pb != attacker_pb, "the attacker must not share the Mantle owner's Proficiency Bonus"
    burns = _melee_hits(combat, table, mid, tmp_path, owner_pb)
    assert burns, "a melee hit on the mantled creature burns the attacker"
    assert all(burn == owner_pb for burn in burns), \
        f"every burn is the Mantle owner's Proficiency Bonus ({owner_pb}), not the attacker's ({attacker_pb}): {burns}"


def _melee_hits(combat, table, mid, tmp_path, expected, *, limit=40):
    """Have the east foe strike the mantled ally in melee until it has burned for the expected Proficiency Bonus.

    The attacker is the only creature that loses hit points here, so its own loss is the printed backlash. A miss costs
    nothing, so a strike that lands as 0 is not a trigger.
    """
    burns = []
    for _ in range(limit):
        engine = combat._load_session(mid).engine
        if engine.state.terminal_result is not None or not legal_candidates(engine):
            break
        if engine.state.current_actor_id != FOE:
            commit(combat, table, mid, tmp_path)
            continue
        strikes = [c.candidate_id for c in engine.legal_candidates()
                   if c.display_name == "Unarmed Strike" and ALLY in c.target_ids]
        if not strikes:
            commit(combat, table, mid, tmp_path)
            continue
        before = engine.state.actors[FOE].current_hp
        commit(combat, table, mid, tmp_path, strikes[0])
        lost = before - combat._load_session(mid).engine.state.actors[FOE].current_hp
        if lost:
            burns.append(lost)
        if burns and burns[-1] >= expected:
            break
    return burns


def test_weather_backlash_triggers_once_per_round_and_survives_the_recipients_turn(tmp_path):
    """"This damage can trigger only once per round per mantled creature" -- the round, not the mantled creature's turn."""
    combat, table, mid = arena(tmp_path, MANTLE_TALENTS, "backlash-round", ask_actors=(ALLY, FOE), ally_ac=6,
                               maximum_rounds=60)
    owner_turn(combat, table, mid, tmp_path, idle=True)
    commit(combat, table, mid, tmp_path, action(combat, mid, "Sky Mantle", ALLY), choose=mantle_chooser("heat"))
    engine = combat._load_session(mid).engine
    flag = f"_round_weather_backlash:{ME}:{ALLY}"
    flag_round = None
    retained = False
    for _ in range(80):
        engine = combat._load_session(mid).engine
        if engine.state.terminal_result is not None or not legal_candidates(engine):
            break
        current = engine.state.current_actor_id
        if current == FOE and (flag_round is None or engine.state.round_number == flag_round):
            cid = next((c.candidate_id for c in engine.legal_candidates()
                        if c.display_name == "Unarmed Strike" and ALLY in c.target_ids), None)
            if cid is not None:
                commit(combat, table, mid, tmp_path, cid)
                engine = combat._load_session(mid).engine
                if int(engine.state.actors[ALLY].turn_flags.get(flag) or 0):
                    flag_round = engine.state.round_number
                continue
        if current == ALLY and flag_round is not None and not retained:
            # The mantled creature's own turn has begun: a per-turn flag would already have been cleared here.
            assert engine.state.actors[ALLY].turn_flags.get(flag) == flag_round, \
                "the once-per-round limit survives the mantled creature's own turn start"
            retained = True
            break
        commit(combat, table, mid, tmp_path)
    assert flag_round, "the melee hit triggered the Backlash"
    assert retained, "the mantled creature's own turn began afterwards"
    engine = combat._load_session(mid).engine
    burns = [line for line in logs(engine) if "Weather Backlash" in line]
    assert len(burns) == 1, f"one melee hit in the round burns the attacker exactly once: {burns}"
    assert "once per round per mantled creature" in burns[0]
    assert mantle_of(engine, ALLY)[0].instance_id not in str(engine.state.actors[ALLY].turn_flags.get(flag, "")), \
        "the limit is keyed by owner and mantled creature, not by the Mantle instance"
    # The limit survives a reload (it is a turn flag on the mantled creature, not Mantle-local state).
    engine = combat._load_session(mid).engine
    assert engine.state.actors[ALLY].turn_flags.get(flag) == flag_round, \
        "reloading the saved fight leaves the round's limit alone"
    # Replacing the Mantle inside the same round, between two landed hits, is covered by
    # test_weather_backlash_limit_holds_across_replacing_the_mantle_in_the_same_round below.
    # The next round's melee hit burns the attacker again: the limit is per round, not per fight.
    second = 0
    for _ in range(80):
        engine = combat._load_session(mid).engine
        if engine.state.terminal_result is not None or not legal_candidates(engine):
            break
        if len([line for line in logs(engine) if "Weather Backlash" in line]) > 1:
            second = engine.state.round_number
            break
        if engine.state.current_actor_id == FOE:
            cid = next((c.candidate_id for c in engine.legal_candidates()
                        if c.display_name == "Unarmed Strike" and ALLY in c.target_ids), None)
            if cid is not None:
                commit(combat, table, mid, tmp_path, cid)
                continue
        commit(combat, table, mid, tmp_path)
    assert second and second > flag_round, "a later round's melee hit burns the attacker again"


def _marched(events, after=0):
    """The Weather Backlash moments the fight recorded after event ``after``, in order: a landed hit, the burn, a fresh Mantle."""
    out = []
    for event in events:
        if event.sequence <= after:
            continue
        if event.event_type == "DAMAGE_COMMITTED" and event.actor_id in (FOE, FOE2) and ALLY in (event.target_ids or ()) \
                and int((event.payload or {}).get("hp_damage") or 0) > 0:
            out.append("hit")
        elif event.event_type == "PASSIVE_TRIGGERED" and "Weather Backlash" in str(event.payload.get("log") or ""):
            out.append("burn")
        elif event.event_type == "CONDITION_APPLIED" and (event.payload or {}).get("condition_id") == MANTLE:
            out.append("mantle")
    return out


def test_weather_backlash_limit_holds_across_replacing_the_mantle_in_the_same_round(tmp_path, monkeypatch):
    """"This damage can trigger only once per round per mantled creature" -- proved in the order the exploit needs.

    A limit kept on the Mantle itself is reset by replacing the Mantle, so the round this watches for is the one the
    exploit needs: a landed melee hit burns the attacker, the owner spends its next action re-signing that same creature
    (a fresh Mantle instance), and a second landed melee hit follows before the round ends. Both foes' melee attacks
    are forced to land, so the order is the printed rule's to decide and not the dice's, and the owner is checked to
    stand between the two foes so that one hit, then the recast, then the other hit can all happen in one round.
    """
    from combat import ext
    ext.effects()

    def foe_melee_lands(engine, roll, *rest):
        if str(roll.actor_id) in (FOE, FOE2) and "SAVE" not in str(roll.reason):
            return {"source_id": "test:auto13r3f1.foe_melee_lands", "operation": "replace", "natural_result": 20}
        return None

    monkeypatch.setitem(ext._HOOKS, "d20_result", [*ext._HOOKS.get("d20_result", ()), foe_melee_lands])
    combat, table, mid = arena(tmp_path, MANTLE_TALENTS, "backlash-restring", ask_actors=(ALLY, FOE, FOE2), ally_ac=6,
                               maximum_rounds=6, positions={FOE2: {"x": 4, "y": 7}})
    order = combat._load_session(mid).engine.state.initiative_order
    foes = [order.index(FOE), order.index(FOE2)]
    assert min(foes) < order.index(ME) < max(foes), (
        "this fight must put the owner between the two foes, so one of them lands a hit, the owner re-signs the "
        f"Mantle, and the other lands a second hit in that same round: {order}")
    owner_turn(combat, table, mid, tmp_path, idle=True)
    commit(combat, table, mid, tmp_path, action(combat, mid, "Sky Mantle", ALLY), choose=mantle_chooser("heat"))
    assert mantle_instance(combat, mid, ALLY), "the first Sky Mantle is cast"
    #: (kind, round) for every Weather Backlash moment, in the order the fight recorded them.
    marks: list[tuple[str, int]] = []
    seen = combat._load_session(mid).engine.state.event_sequence
    for _ in range(60):
        engine = combat._load_session(mid).engine
        if engine.state.terminal_result is not None or not legal_candidates(engine):
            break
        current = engine.state.current_actor_id
        cid = None
        if current == ME:
            cid = next((c.candidate_id for c in engine.legal_candidates()
                        if c.display_name == "Sky Mantle" and ALLY in c.target_ids), None)
        elif current in (FOE, FOE2):
            cid = next((c.candidate_id for c in engine.legal_candidates()
                        if c.display_name == "Unarmed Strike" and ALLY in c.target_ids), None)
        commit(combat, table, mid, tmp_path, cid, choose=mantle_chooser("heat") if cid else None)
        engine = combat._load_session(mid).engine
        marks.extend((kind, engine.state.round_number) for kind in _marched(engine.events, seen))
        seen = engine.state.event_sequence
        window = _exploited_round(marks)
        if window:
            break
    window = _exploited_round(marks)
    assert window, (
        "no round recorded a landed hit and its burn, then a replaced Mantle, then a second landed hit, which is the "
        f"only order in which a per-Mantle limit would hand out a second burn: {marks}")
    burns = [line for line in logs(combat._load_session(mid).engine) if "Weather Backlash" in line]
    assert any("once per round per mantled creature" in line for line in burns), burns
    assert sum(1 for kind, at in marks if kind == "burn" and at == window) == 1, \
        f"round {window} burned once: replacing the Mantle mid-round must not hand out a second burn. {marks}"


def _exploited_round(marks):
    """The round in which a burn, then a replaced Mantle, then another landed hit were recorded, or None."""
    for index, (kind, number) in enumerate(marks):
        if kind != "burn":
            continue
        window = [later for later in marks[index + 1:] if later[1] == number]
        kinds = [later[0] for later in window]
        if "mantle" in kinds and "hit" in kinds[kinds.index("mantle") + 1:]:
            return number
    return None


def test_thunder_mantle_burn_prompt_names_the_attacker_not_the_optional_talent(tmp_path):
    """Thunder's own "once during the Mantle" burn, asked on an enemy's turn with three distinct creatures named.

    Three creatures, because the prompt used to confuse two of them: it credited the *Mantle's owner* with making the
    hit, when the creature that struck is the attacker. The owner here does not own Weatherproof Mantle, which is an
    optional talent that has nothing to do with this burn, so the burn must not be asked under it either.
    """
    talents = [talent for talent in MANTLE_TALENTS if talent != "TAL_WEATHER_WEATHERPROOF_MANTLE"]
    combat, table, mid = arena(tmp_path, talents, "backlash-thunder-prompt", ask_actors=(ALLY, FOE), ally_ac=6,
                               maximum_rounds=40)
    owner_turn(combat, table, mid, tmp_path, idle=True)
    commit(combat, table, mid, tmp_path, action(combat, mid, "Sky Mantle", ALLY), choose=mantle_chooser("thunder"))
    engine = combat._load_session(mid).engine
    assert not weather_signs.owns(engine, engine.state.actors[ME], "weatherproof"), \
        "the owner does not own Weatherproof, so that talent cannot be what this burn is asked under"
    prompts: list[dict] = []
    for _ in range(60):
        engine = combat._load_session(mid).engine
        if engine.state.terminal_result is not None or not legal_candidates(engine):
            break
        if engine.state.current_actor_id == FOE:
            cid = next((c.candidate_id for c in engine.legal_candidates()
                        if c.display_name == "Unarmed Strike" and ALLY in c.target_ids), None)
            if cid is not None:
                # An enemy's turn: the owner is still the one asked, which is the off-turn case.
                commit(combat, table, mid, tmp_path, cid, prompts=prompts)
                break
        commit(combat, table, mid, tmp_path)
    burns = [p for p in prompts if "WEATHER_THUNDER_BACKLASH" in str(p["context"].get("checkpoint") or "")]
    assert burns, "Thunder's own once-per-Mantle burn never asked for its damage type"
    shown = str(burns[0]["moment"])
    assert "East foe hit Ally" in shown, \
        f"the prompt must name the creature that actually struck, not the Mantle's owner: {shown}"
    assert "Your hit" not in shown, "the owner did not make the hit, so the prompt must not say that it did"
    assert str(burns[0]["reactor"]) == "You", "the owner is asked, off its own turn"
    assert str(burns[0]["by"]) == "East foe" and str(burns[0]["affected"]) == "East foe", \
        "the creature that struck, and the creature that takes the damage back, is the attacker"
    assert str(burns[0]["title"]) == "Thunder Sign Mantle", \
        f"the burn is named for the Mantle benefit that grants it: {burns[0]['title']}"
    rules = str(burns[0]["rules"])
    assert "Sky Mantle" in rules, "asked under the Sky Mantle that granted the burn"
    assert "also grants Resistance to one damage type" not in rules, \
        "Weatherproof Mantle is a separate optional talent and must not be credited with this burn"


def mantle_instance(combat, mid, who):
    """The Mantle instance id on ``who``, or "" when it wears none."""
    mantles = mantle_of(combat._load_session(mid).engine, who)
    return mantles[0].instance_id if mantles else ""


def test_rain_shroud_speed_penalty_ends_at_the_start_of_the_owners_next_turn(tmp_path):
    """"its Speed is reduced by 10 feet until the start of your next turn": the Shroud owner's turn, not the victim's."""
    combat, table, mid = arena(tmp_path, SPHERE, "shroud-rain-speed", dc=40, maximum_rounds=60)
    owner_turn(combat, table, mid, tmp_path, idle=True)
    commit(combat, table, mid, tmp_path, action(combat, mid, "Cloud Shroud (any creature)", FOE),
           choose=choose_shroud("rain"))
    engine = combat._load_session(mid).engine
    cuts = [m for m in engine.state.actors[FOE].modifiers.values() if m.target_field == "speed_ft"]
    assert cuts, "a failed Rain Shroud save reduces the target's Speed by 10 feet"
    for modifier in cuts:
        assert str(modifier.expires_on).startswith(f"START_OF_TURN_AT:{ME}:"), \
            f"the printed duration is the Shroud owner's own next turn, not the victim's: {modifier.expires_on}"
    for _ in range(60):
        engine = combat._load_session(mid).engine
        # Wait for the owner's own next turn to have begun: the Shroud's throw only repeats at the end of the victim's.
        if not legal_candidates(engine) or (engine.state.actors[ME].turns_started >= 2
                                            and engine.state.current_actor_id == ME):
            break
        commit(combat, table, mid, tmp_path)
    engine = combat._load_session(mid).engine
    assert engine.state.current_actor_id == ME and engine.state.actors[ME].turns_started >= 2, \
        "the owner's next turn has begun"
    assert not [m for m in engine.state.actors[FOE].modifiers.values() if m.target_field == "speed_ft"], \
        "the penalty is gone once the owner's next turn has started, not the victim's"


def test_shroud_minute_releases_only_the_concentration_it_took(tmp_path):
    """The Shroud's own minute ends the Concentration it took, and leaves another one the owner holds alone."""
    from combat import concentration

    combat, table, mid = arena(tmp_path, SPHERE, "shroud-concentration", dc=40, maximum_rounds=60)
    owner_turn(combat, table, mid, tmp_path, idle=True)
    commit(combat, table, mid, tmp_path, action(combat, mid, "Cloud Shroud (any creature)", FOE),
           choose=choose_shroud("thunder"))
    engine = combat._load_session(mid).engine
    first = shroud_of(engine)[0]
    started = engine.state.actors[ME].concentration
    assert started is not None and first.data["concentration_started_sequence"] == started.started_sequence, \
        "the Shroud records which Concentration it is holding"
    next_owner_turn(combat, table, mid, tmp_path)
    commit(combat, table, mid, tmp_path, action(combat, mid, "Cloud Shroud (any creature)", FOE2),
           choose=choose_shroud("thunder"))
    engine = combat._load_session(mid).engine
    second = shroud_of(engine, FOE2)[0]
    held = [one for _, one in concentration.held(engine.state.actors[ME])]
    assert any(one.started_sequence == started.started_sequence for one in held), \
        "the first Shroud's Concentration is now an earlier one the owner still holds"
    assert second.data["concentration_started_sequence"] != started.started_sequence
    for _ in range(260):
        engine = combat._load_session(mid).engine
        if not legal_candidates(engine) or not shroud_of(engine, FOE):
            break
        commit(combat, table, mid, tmp_path)
    engine = combat._load_session(mid).engine
    assert not shroud_of(engine, FOE), "the first Shroud's own minute is up"
    assert shroud_of(engine, FOE2), "the later Shroud is still inside its own minute"
    assert engine.state.actors[ME].concentration is not None, \
        "the Concentration the second Shroud is holding is untouched"
    assert engine.state.actors[ME].concentration.started_sequence == second.data["concentration_started_sequence"]
    assert not any(one.started_sequence == started.started_sequence
                   for _, one in concentration.held(engine.state.actors[ME])), \
        "and only the Concentration the ended Shroud took was released"
def test_wind_shroud_marker_spoils_the_shrouded_creatures_own_ranged_attack(tmp_path):
    """"Disadvantage on ranged weapon attacks until the start of its next turn": its own attack, not its target's."""
    from combat import typed_executor as te
    from combat.ext import weather_shroud

    combat, table, mid = arena(tmp_path, SPHERE, "shroud-wind-ranged", dc=40, maximum_rounds=10)
    owner_turn(combat, table, mid, tmp_path, idle=True)
    commit(combat, table, mid, tmp_path, action(combat, mid, "Cloud Shroud", ALLY), choose=choose_shroud("wind"))
    engine = combat._load_session(mid).engine
    ally = engine.state.actors[ALLY]
    assert weather_shroud.markers(ally, "weather_ranged"), "a failed Wind Shroud save spoils the target's ranged attacks"
    ranged, melee = _weapon_actions(engine)
    shot_action = next(a for a in engine.action_catalog.values()
                       if ((a.parameters or {}).get("typed") or {}) is ranged)
    ally_shooting = te.Context(engine, ally, shot_action, None, ranged, [], engine.state.actors[FOE])
    foe_shooting = te.Context(engine, engine.state.actors[FOE], shot_action, None, ranged, [], ally)
    assert weather_shroud.shrouded_ranged(foe_shooting, ally) is None, \
        "a healthy creature shooting a Wind-shrouded enemy is not the one whose attacks are spoiled"
    assert weather_shroud.markers(ally, "weather_ranged"), "and its marker is not spent by that attack"
    assert weather_shroud.shrouded_ranged(ally_shooting, engine.state.actors[FOE]) == "DISADVANTAGE", \
        "the shrouded creature's own ranged weapon attack has Disadvantage"
    melee_action = next(a for a in engine.action_catalog.values()
                        if ((a.parameters or {}).get("typed") or {}) is melee)
    ally_striking = te.Context(engine, ally, melee_action, None, melee, [], engine.state.actors[FOE])
    assert weather_shroud.shrouded_ranged(ally_striking, engine.state.actors[FOE]) is None, \
        "and a melee blow is not a ranged weapon attack"
