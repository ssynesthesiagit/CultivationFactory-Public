"""RESIST (owner: "there should be a resistances section and vulnerabilities").

The character sheet's Defences & Conditions card lists Resistances,
Vulnerabilities and Immunities.  It reads the same defence rows the fight's
damage resolution weighs (combat/typed_reactions.py ``defense_display``),
projected through the table's state endpoint, so the sheet cannot disagree
with the fight: a Resistance or Vulnerability an active effect puts on shows
up with its source and when it ends, next to the permanent compiled ones.
"""

from pathlib import Path

from combat import typed_reactions
from combat.factory_compiler import compile_character

from tests.test_shield_possession_and_armor import (
    ME, AN, _bundle, _sheet, _kit, _fight, _table_match, AXE, UNARMORED, STONE_SKIN,
)

ROOT = Path(__file__).resolve().parents[1]


def _actor_row(table, match):
    return next(row for row in table.state(match)["presentation"]["actors"] if row["entity_id"] == ME)


def test_the_card_lists_an_active_effect_resistance_and_a_vulnerability():
    """Stone Skin compiles as a standing Resistance to Cold while unarmored.

    The Fire Resistance and the Lightning Vulnerability are what a printed
    "Resistance to Fire damage until the end of your next turn" and
    "Vulnerability to Lightning damage" put on the fighter: the engine's own
    modifier write, the one combat/typed_executor.py block_resistance and
    block_vulnerability make when such an ability runs."""
    engine = _fight(_sheet(_kit(AXE), mids=[UNARMORED, STONE_SKIN]))
    me = engine.state.actors[ME]
    engine._add_modifier(me, "test:fire_ward", "damage_resistance", "ADD", "FIRE", "ALWAYS",
                         expires_on="END_OF_HOLDER_NEXT_TURN")
    engine._add_modifier(me, "test:shock_weakness", "damage_vulnerability", "ADD", "LIGHTNING", "ALWAYS",
                         expires_on="UNTIL_REMOVED")

    card = typed_reactions.defense_display(engine, me)

    assert {"damage_type": "Cold", "source": "Stone Skin", "until": None, "note": None} in card["resistances"]
    [fire] = [row for row in card["resistances"] if row["damage_type"] == "Fire"]
    assert fire["source"] == "Fire Ward" and "turn" in (fire["until"] or "")
    assert card["vulnerabilities"] == [
        {"damage_type": "Lightning", "source": "Shock Weakness", "until": None, "note": None}]
    assert card["immunities"] == []
    # the card cannot disagree with the fight: the same answers damage resolution gives
    assert typed_reactions.damage_factor(engine, me, "FIRE", None, None) == 0.5
    assert typed_reactions.damage_factor(engine, me, "COLD", None, None) == 0.5
    assert typed_reactions.damage_factor(engine, me, "LIGHTNING", None, None) == 2.0


def test_the_table_projects_the_resistance_a_committed_action_granted(tmp_path):
    """Diamond Rime Body is a printed bonus action: "you gain Resistance to
    Cold damage" for one minute.  Driving it through the table commits it,
    and the state the sheet reads lists it with its source and when it
    ends -- next to the standing Stone Skin Resistance."""
    sheet = _sheet(_kit(AXE), mids=[UNARMORED, STONE_SKIN])
    sheet["spheres_and_talents"]["learned_talent_record_ids"] = ["TAL_ICE_DIAMOND_RIME_BODY"]
    combat, table, mid = _table_match(tmp_path, _bundle(sheet))

    before = _actor_row(table, mid)["damage_defenses"]["resistances"]
    assert before == [{"damage_type": "Cold", "source": "Stone Skin", "until": None, "note": None}]

    state = table.state(mid)
    option = next(o for g in state["menu"]["actions"] for o in g["options"]
                  if o["label"] == "Diamond Rime Body")
    committed = table.act(mid, option["candidate_id"], state["menu"]["decision_id"],
                          state["menu"]["state_version"], state["last_sequence"])
    assert committed["status"] == "COMMITTED"

    defenses = _actor_row(table, mid)["damage_defenses"]["resistances"]
    [rimed] = [row for row in defenses if row["source"] == "Diamond Rime Body"]
    assert rimed["damage_type"] == "Cold" and "round" in (rimed["until"] or "")
    assert {"damage_type": "Cold", "source": "Stone Skin", "until": None, "note": None} in defenses


def test_a_conditional_resistance_shows_with_its_condition():
    """F1: a Resistance that only applies to some attacks is listed with the condition, not hidden.

    A compiled "defense" row marked mundane_only (e.g. "Fire Resistance against nonmagical attacks") needs
    a real attack to pass its gate, so the card must still list it and say what it is conditional on."""
    engine = _fight(_sheet(_kit(AXE), mids=[UNARMORED, STONE_SKIN]))
    me = engine.state.actors[ME]
    engine.typed_passive_rows = {**getattr(engine, "typed_passive_rows", {}),
                                 ME: [{"block": "defense", "feature_id": "test:mundane_fire", "source": "Mundane Ward",
                                       "damage_types": ["FIRE"], "kind": "resistance", "amount": 0,
                                       "mundane_only": True, "attacks_only": False, "attack_kinds": [],
                                       "martial_focus": False, "requires_condition": None, "immune_below_cl": 0,
                                       "melee_only": False, "once_per_round": False}]}

    card = typed_reactions.defense_display(engine, me)
    [fire] = [row for row in card["resistances"] if row["damage_type"] == "Fire"]
    assert fire["source"] == "Mundane Ward" and "nonmagical" in (fire["note"] or "")


def test_a_timed_condition_grant_shows_its_expiry_and_a_permanent_one_shows_none():
    """A condition that grants a defence (Petrified: Resistance to every damage type and immunity to Poisoned)
    lists its end time on the card while the condition lasts; a permanent one lists none."""
    from combat.typed_executor import CONDITION_PREFIX

    engine = _fight(_sheet(_kit(AXE), mids=[UNARMORED, STONE_SKIN]))
    me = engine.state.actors[ME]
    petrified = CONDITION_PREFIX + "petrified"

    engine._apply_condition(me, petrified, "test:gaze", AN, expires_on="END_OF_HOLDER_NEXT_TURN")
    timed = typed_reactions.defense_display(engine, me)
    [all_kinds] = [row for row in timed["resistances"] if row["damage_type"] == "All damage types"]
    [poison] = [row for row in timed["immunities"] if row["condition"] == "Poisoned"]
    assert all_kinds["source"] == poison["source"] == "Petrified"
    assert all_kinds["until"] and "end of" in all_kinds["until"] and "turn" in all_kinds["until"]
    assert poison["until"] == all_kinds["until"]

    me.conditions.clear()
    engine._apply_condition(me, petrified, "test:gaze", AN, expires_on="UNTIL_REMOVED")
    permanent = typed_reactions.defense_display(engine, me)
    assert all(row["until"] is None for row in permanent["resistances"] if row["source"] == "Petrified")
    assert all(row["until"] is None for row in permanent["immunities"] if row["source"] == "Petrified")


def test_a_plugin_condition_immunity_appears_on_the_card():
    """F2: a condition immunity granted by a plug-in is listed on the card, and the card never calls the
    operational condition_immune hook (which can spend a Reaction).  The plug-in declares it through the
    defense_description hook's "conditions" row (the Imperial Mandate-style immunity)."""
    from combat import ext
    engine = _fight(_sheet(_kit(AXE), mids=[UNARMORED, STONE_SKIN]))
    me = engine.state.actors[ME]

    @ext.hook("defense_description")
    def imperial_mandate_description(engine_, target_):
        return [{"conditions": ["frightened"], "source": "Imperial Mandate", "expires_on": "UNTIL_REMOVED",
                 "note": "while they can see the source"}]

    try:
        card = typed_reactions.defense_display(engine, me)
    finally:
        ext._HOOKS["defense_description"].remove(imperial_mandate_description)
        ext._HOOK_PRIORITIES.pop(("defense_description", imperial_mandate_description), None)

    assert any(row["condition"] == "Frightened" and row["source"] == "Imperial Mandate"
               for row in card["immunities"])


def test_a_suppressed_resistance_shows_as_suppressed():
    """F3: a Resistance a suppression effect has turned off is listed as suppressed, not as active."""
    engine = _fight(_sheet(_kit(AXE), mids=[UNARMORED, STONE_SKIN]))
    me = engine.state.actors[ME]
    engine._add_modifier(me, "test:fire_ward", "damage_resistance", "ADD", "FIRE", "ALWAYS",
                         expires_on="UNTIL_REMOVED")
    engine._add_modifier(me, "test:suppressor", "resistance_suppressed", "SET", "FIRE", "ALWAYS",
                         expires_on="UNTIL_REMOVED")

    card = typed_reactions.defense_display(engine, me)
    [fire] = [row for row in card["resistances"] if row["damage_type"] == "Fire"]
    assert fire["note"] and "suppressed" in fire["note"]
    assert typed_reactions.damage_factor(engine, me, "FIRE", None, None) == 1.0


def test_a_one_use_benefit_shows_it_lasts_until_used():
    """F4: a one-use Resistance says it lasts until used (not until the end of a turn), and names its source."""
    engine = _fight(_sheet(_kit(AXE), mids=[UNARMORED, STONE_SKIN]))
    me = engine.state.actors[ME]
    engine._add_modifier(me, "test:next_hit_ward", "damage_resistance_next", "ADD", "COLD", "ALWAYS",
                         expires_on="CONSUMED")

    card = typed_reactions.defense_display(engine, me)
    [cold] = [row for row in card["resistances"] if row["damage_type"] == "Cold" and row["source"] != "Stone Skin"]
    assert "until used" in (cold["until"] or "")
    assert "test:" not in (cold["source"] or "")


def test_a_fighter_with_no_defences_projects_empty_sections(tmp_path):
    """No defences at all: every section is empty, so the card hides them."""
    combat, table, mid = _table_match(tmp_path, _bundle(_sheet(_kit(AXE))))
    assert _actor_row(table, mid)["damage_defenses"] == {
        "resistances": [], "vulnerabilities": [], "immunities": [], "reductions": []}


def test_a_timed_condition_immunity_from_an_effect_shows_its_expiry():
    """RESISTR3 F1: an effect that grants immunity to a condition until a turn boundary (the modifier
    combat/typed_executor.py block_resistance writes) lists its end time; an UNTIL_REMOVED one lists none."""
    engine = _fight(_sheet(_kit(AXE), mids=[UNARMORED, STONE_SKIN]))
    me = engine.state.actors[ME]
    engine._add_modifier(me, "test:calm_mind", "condition_immunity", "ADD", "frightened", "ALWAYS",
                         expires_on="END_OF_HOLDER_NEXT_TURN")
    engine._add_modifier(me, "test:iron_will", "condition_immunity", "ADD", "charmed", "ALWAYS",
                         expires_on="UNTIL_REMOVED")

    card = typed_reactions.defense_display(engine, me)

    [frightened] = [row for row in card["immunities"] if row.get("condition") == "Frightened"]
    assert frightened["source"] == "Calm Mind" and "turn" in (frightened["until"] or "")
    [charmed] = [row for row in card["immunities"] if row.get("condition") == "Charmed"]
    assert charmed["source"] == "Iron Will" and charmed["until"] is None


def test_imperial_mandate_lists_frightened_immunity_only_for_a_commanded_ally_who_can_see_the_leader():
    """The Mandate's Frightened immunity (in the Court, while Commanded and able to see or hear the leader) is listed
    on the Defences card for the qualifying ally, and absent for an ally outside its gate."""
    from tests.test_sys_resources_states import ALLY, ME as LEADER, _command, _act, COURT_ACTION
    from combat.gate2_runtime_models import Position

    engine = _command("warleader_domain_court_of_moving_banners", "imperial_mandate_of_the_living_line", marks=0)
    _act(engine, LEADER, COURT_ACTION)
    ally = engine.state.actors[ALLY]

    shown = typed_reactions.defense_display(engine, ally)
    [frightened] = [row for row in shown["immunities"] if row.get("condition") == "Frightened"]
    assert frightened["source"] == "Imperial Mandate Of The Living Line" and "see or hear" in (frightened["note"] or "")

    ally.position = Position(x=60, y=60)
    hidden = typed_reactions.defense_display(engine, ally)
    assert not [row for row in hidden["immunities"] if row.get("condition") == "Frightened"]


def test_a_condition_a_plugin_retired_lists_no_defences():
    """RESISTR6: a condition that a condition_excluded plug-in has retired grants nothing in combat
    (condition_rules with the engine), so the Defences card lists nothing from it either."""
    from combat import ext
    from combat.typed_executor import CONDITION_PREFIX

    engine = _fight(_sheet(_kit(AXE), mids=[UNARMORED, STONE_SKIN]))
    me = engine.state.actors[ME]
    engine._apply_condition(me, CONDITION_PREFIX + "petrified", "test:gaze", AN, expires_on="UNTIL_REMOVED")
    assert any(row["source"] == "Petrified" for row in typed_reactions.defense_display(engine, me)["resistances"])

    @ext.hook("condition_excluded")
    def retire_petrified(engine_, actor_, condition_):
        return condition_.condition_id == CONDITION_PREFIX + "petrified"

    try:
        card = typed_reactions.defense_display(engine, me)
    finally:
        ext._HOOKS["condition_excluded"].remove(retire_petrified)
        ext._HOOK_PRIORITIES.pop(("condition_excluded", retire_petrified), None)

    assert not any(row["source"] == "Petrified" for row in card["resistances"] + card["immunities"])


def test_the_card_lists_an_attack_only_plugin_resistance_with_its_qualifier():
    """RESISTf4: a Resistance a plug-in answers only for a kind of attack is still listed, and names that attack.

    Weatherproof Mantle's Wind Sign is "Resistance to nonmagical ranged weapon damage" (combat/ext/weather_mantle.py,
    the ``damage_defenses`` hook): it names the attack, not the damage type, so it cannot live in the Mantle's
    condition rule data.  The card has no attack to weigh -- it asks each hook with an empty attack profile -- so the
    row used to be filtered away by the very gates damage resolution applies, and a creature could be hit by a
    qualifying attack while its sheet listed no Resistance at all.  The card now keeps the row and shows the gate as a
    plain qualifier; combat's own filtering is unchanged, which the same test pins down.
    """
    from combat import ext

    engine = _fight(_sheet(_kit(AXE), mids=[UNARMORED, STONE_SKIN]))
    me = engine.state.actors[ME]

    @ext.hook("damage_defenses")
    def wind_sign_resistance(engine_, target_, damage_type, typed, source_actor_id):
        """The Mantle-shaped row: a weapon attack's damage, gated on attack_kinds and nonmagical."""
        if target_.entity_id != ME:  # the Mantle is on one creature and grants nothing to anyone else
            return None
        return [{"kind": "resistance", "damage_types": [str(damage_type).upper()],
                 "feature_id": "test:sky_mantle", "attack_kinds": ["weapon"], "mundane_only": True}]

    try:
        card = typed_reactions.defense_display(engine, me)
        # combat still filters the row out for an attack that is not a weapon attack: the card does not decide
        assert typed_reactions.additional_defenses(engine, me, "PIERCING", None, None) == []
    finally:
        ext._HOOKS["damage_defenses"].remove(wind_sign_resistance)
        ext._HOOK_PRIORITIES.pop(("damage_defenses", wind_sign_resistance), None)

    [piercing] = [row for row in card["resistances"] if row["damage_type"] == "Piercing"]
    assert piercing["source"] == "Sky Mantle"
    assert piercing["note"] == "only against nonmagical attacks, only against weapon attacks"

    # a creature the plug-in does not answer for lists nothing from it
    assert not any(row["source"] == "Sky Mantle"
                   for row in typed_reactions.defense_display(engine, engine.state.actors[AN])["resistances"])


def test_a_compiled_all_damage_resistance_is_listed_once():
    """RESISTR10: a compiled passive Resistance written as damage_types ["ALL"] is listed as "All damage types"
    (it used to be dropped, so the card showed nothing although damage resolution halves every type)."""
    engine = _fight(_sheet(_kit(AXE), mids=[UNARMORED, STONE_SKIN]))
    me = engine.state.actors[ME]
    passive = getattr(engine, "typed_passive_rows", None)
    if passive is None:
        engine.typed_passive_rows = passive = {}
    passive.setdefault(ME, []).append({"block": "resistance", "kind": "resistance", "damage_types": ["ALL"],
                                       "feature_id": "test:diamond_body"})

    card = typed_reactions.defense_display(engine, me)

    assert {"damage_type": "All damage types", "source": "Diamond Body", "until": None, "note": None} \
        in card["resistances"]


def test_a_next_damage_defence_says_it_is_spent_on_the_next_hit():
    """RESISTR11: a damage_resistance_next / damage_vulnerability_next modifier is spent by the next damage of its
    type (typed_reactions.defend), so the card says so even when its expiry is a turn boundary."""
    engine = _fight(_sheet(_kit(AXE), mids=[UNARMORED, STONE_SKIN]))
    me = engine.state.actors[ME]
    engine._add_modifier(me, "test:glass_skin", "damage_resistance_next", "ADD", "FIRE", "ALWAYS",
                         expires_on="END_OF_HOLDER_NEXT_TURN")
    engine._add_modifier(me, "test:cracked_shell", "damage_vulnerability_next", "ADD", "THUNDER", "ALWAYS",
                         expires_on="END_OF_HOLDER_NEXT_TURN")

    card = typed_reactions.defense_display(engine, me)

    [fire] = [row for row in card["resistances"] if row["damage_type"] == "Fire"]
    [thunder] = [row for row in card["vulnerabilities"] if row["damage_type"] == "Thunder"]
    assert fire["note"] == thunder["note"] == "next damage of that type only"


# --------------------------------------------------------------------------- RESISTf5: every standing plug-in defence the card could not name
# The Defences card asks each damage_defenses hook with an empty attack profile, so a plug-in that only
# answers for a particular attack (or that answers through condition_immune, which the card must never call
# because it can spend a Reaction) had no row to show.  Each plug-in below now names the half of its printed
# benefit that exists between hits, through the defense_description hook, reusing the very predicate its combat
# hook reads.  The tests pin both halves: the card lists it for a creature that has it, lists nothing for a
# creature that has not, and the combat hook still answers exactly as before.


def _rage(engine, me, *, raging=True):
    """Asura's Rage held, as the state hook leaves it."""
    if raging:
        engine._apply_condition(me, "condition:typed.state.asura_s_rage", "test:asura_rage", ME,
                                expires_on="END_OF_HOLDER_NEXT_TURN")


def test_jigoku_rage_lists_the_frightened_immunity_a_raging_hellwalker_has():
    """RESISTf5 (the RESISTR12 finding): a raging Hellwalker is immune to Frightened in combat
    (combat/ext/jigoku.py condition_immune), and the Defences card now lists that immunity instead of a
    creature that cannot be frightened showing no defence at all.  A creature that is not raging is neither
    immune nor listed."""
    from combat.ext import jigoku
    from combat.typed_executor import condition_immune

    engine = _fight(_sheet(_kit(AXE), mids=[UNARMORED, STONE_SKIN]))
    me = engine.state.actors[ME]

    assert not [row for row in typed_reactions.defense_display(engine, me)["immunities"]
                if row.get("condition") == "Frightened"]
    assert condition_immune(engine, me, "frightened") is not True

    _rage(engine, me)
    assert condition_immune(engine, me, "frightened") is True  # the fight's own answer
    [frightened] = [row for row in typed_reactions.defense_display(engine, me)["immunities"]
                    if row.get("condition") == "Frightened"]
    assert "rag" in (frightened["note"] or "").lower()
    assert frightened["until"] and "turn" in frightened["until"]  # the Rage's own end time
    assert " 's " not in frightened["until"] and not frightened["until"].startswith("'s")  # RESISTR13: holder named

    # a creature that never rages is not immune and lists nothing
    assert condition_immune(engine, engine.state.actors[AN], "frightened") is not True
    assert not [row for row in typed_reactions.defense_display(engine, engine.state.actors[AN])["immunities"]
                if row.get("condition") == "Frightened"]
    assert jigoku._raging(engine, me) and not jigoku._raging(engine, engine.state.actors[AN])


def test_a_compiled_path_rider_condition_immunity_lists_on_the_card():
    """RESISTf5: a Path/Subpath rider's printed condition immunity is applied by condition_immune, which the
    card must never call.  The rider's rows live under combat/ext/path_riders.py's own "path_rider" block, so
    the card's condition-rule projection never saw them either; the plug-in now names the same rows."""
    engine = _fight(_sheet(_kit(AXE), mids=[UNARMORED, STONE_SKIN]))
    me = engine.state.actors[ME]
    engine.typed_passive_rows = {**getattr(engine, "typed_passive_rows", {}), ME: [
        {"block": "path_rider", "kind": "condition_immunity", "feature_id": "test:unshakable",
         "conditions": ["frightened"]}]}

    from combat.typed_executor import condition_immune
    assert condition_immune(engine, me, "frightened") is True
    [frightened] = [row for row in typed_reactions.defense_display(engine, me)["immunities"]
                    if row.get("condition") == "Frightened"]
    assert frightened["source"] == "Unshakable"

    # a creature that compiled no such rider is neither immune nor listed
    assert condition_immune(engine, engine.state.actors[AN], "frightened") is not True
    assert not [row for row in typed_reactions.defense_display(engine, engine.state.actors[AN])["immunities"]
                if row.get("condition") == "Frightened"]


def test_the_court_of_the_crawling_fever_lists_its_poison_and_necrotic_resistance():
    """RESISTf5: the Court's Resistance applies only to damage that comes from a Disease ability, which is
    read off the packet combat carries -- so the card, which has no attack in hand, could not see it.  The
    Court's own membership gate (court_covers) is what the card now shows, and only for the maker."""
    from combat.ext import disease
    from combat.gate2_runtime_models import ZoneState

    engine = _fight(_sheet(_kit(AXE), mids=[UNARMORED, STONE_SKIN]))
    me = engine.state.actors[ME]

    def covered():
        return any(row["damage_type"] in ("Poison", "Necrotic")
                   for row in typed_reactions.defense_display(engine, me)["resistances"])

    assert not covered()
    engine.state.zones["zone:court"] = ZoneState(
        zone_id="zone:court", source_definition_id=f"action:typed.x.{disease.CRAWLING}", owner_id=ME,
        center=me.position, radius_cells=6, affected_cells=(me.position,), concentration_link=False,
        duration_rounds=10, created_round=1, trigger_profile={"kind": "TYPED"})

    assert disease.court_covers(engine, me)
    card = typed_reactions.defense_display(engine, me)
    kinds = {row["damage_type"] for row in card["resistances"] if "crawling fever" in (row["source"] or "").lower()}
    assert kinds == {"Poison", "Necrotic"}
    assert all("Disease" in (row["note"] or "") for row in card["resistances"]
               if "crawling fever" in (row["source"] or "").lower())

    # an ally nobody chose is outside the printed benefit and lists nothing
    ally = engine.state.actors[AN]
    ally.position = type(ally.position)(x=60, y=60)
    assert not disease.court_covers(engine, ally)
    assert not [row for row in typed_reactions.defense_display(engine, ally)["resistances"]
                if "crawling fever" in (row["source"] or "").lower()]


def test_an_allied_dreamscape_shelter_lists_its_nightmare_resistance():
    """RESISTf5: standing inside a Lucid Veil or Symbolic Shelter resists Psychic damage from the two printed
    Nightmare Dream talents, which combat reads off the packet's sealed source.  The card names the shelter's
    half, for an ally standing in it and for no one else."""
    from combat.ext import dreams_core
    from combat.gate2_runtime_models import ZoneState

    engine = _fight(_sheet(_kit(AXE), mids=[UNARMORED, STONE_SKIN]))
    me = engine.state.actors[ME]
    nightmare = {"source": "TAL_DREAM_NIGHTMARE_GLIMPSE"}
    other = {"source": "TAL_ICE_RIME_BLAST"}

    assert dreams_core.nightmare_shelter(engine, me, "PSYCHIC", nightmare, None) is None
    assert not [row for row in typed_reactions.defense_display(engine, me)["resistances"]
                if row["damage_type"] == "Psychic"]

    engine.state.zones["zone:shelter"] = ZoneState(
        zone_id="zone:shelter", source_definition_id="action:typed.x.symbolic_shelter", owner_id=AN,
        center=me.position, radius_cells=2, affected_cells=(me.position,), concentration_link=False,
        created_round=1,
        trigger_profile={"kind": "TYPED", "inside": [{"rule": {"dream_nightmare_resistance": 1}, "who": "any"}]})

    assert dreams_core.nightmare_shelter(engine, me, "PSYCHIC", nightmare, None)  # the fight's own answer
    assert dreams_core.nightmare_shelter(engine, me, "PSYCHIC", other, None) is None  # not a Nightmare talent
    [psychic] = [row for row in typed_reactions.defense_display(engine, me)["resistances"]
                 if row["damage_type"] == "Psychic"]
    assert "Nightmare" in (psychic["note"] or "")

    # the shelter's own maker is not one of the "allies inside" it protects
    assert not [row for row in typed_reactions.defense_display(engine, engine.state.actors[AN])["resistances"]
                if row["damage_type"] == "Psychic"]


def test_miasma_form_lists_its_resistance_to_weapon_damage():
    """RESISTf5: Miasma Form resists weapon damage that is nonmagical, which combat reads off the packet, so
    the card could not show a benefit the poisoner really has.  The card lists it while the Miasma is held and
    says what it is conditional on; a creature not in its Miasma lists nothing."""
    from combat.ext import poison
    from combat.gate2_runtime_models import ConcentrationState

    engine = _fight(_sheet(_kit(AXE), mids=[UNARMORED, STONE_SKIN]))
    me = engine.state.actors[ME]
    mundane_blow = {"effects": [{"type": "damage", "damage_type": "bludgeoning"}], "mundane": True}
    magical_blow = {"effects": [{"type": "damage", "damage_type": "bludgeoning"}], "mundane": False}

    def listed(actor):
        return {row["damage_type"] for row in typed_reactions.defense_display(engine, actor)["resistances"]
                if "miasma" in (row["source"] or "").lower()}

    assert not listed(me)
    me.concentration = ConcentrationState(source_definition_id=poison.MIASMA, started_sequence=1)
    engine._add_modifier(me, poison.MIASMA, "test:miasma_hold", "SET", "1", "ALWAYS", expires_on="UNTIL_REMOVED")

    assert poison.miasma_physical_resistance(engine, me, "BLUDGEONING", mundane_blow, None)  # the fight's answer
    assert poison.miasma_physical_resistance(engine, me, "BLUDGEONING", magical_blow, None) is None
    assert listed(me) == {"Bludgeoning", "Piercing", "Slashing"}
    assert all("nonmagical" in (row["note"] or "") for row in typed_reactions.defense_display(engine, me)["resistances"]
               if "miasma" in (row["source"] or "").lower())

    # a creature not concentrating on the Miasma has none of it
    assert not poison.miasma_active(engine.state.actors[AN])
    assert not listed(engine.state.actors[AN])


def test_shugenjas_elemental_patron_resistance_lists_for_a_patron_that_declares_an_element():
    """RESISTf5: the Shugenja's patron Resistance answers only for damage from abilities declaring that
    element, which combat reads off the packet.  The card names the patron's damage type with that printed
    condition, and a creature without a recorded patron lists nothing."""
    from combat.ext import shugenja_prayer as prayer

    engine = _fight(_sheet(_kit(AXE), mids=[UNARMORED, STONE_SKIN]))
    me = engine.state.actors[ME]
    tagged = {"source_tags": ["earth"]}
    untagged = {"source_tags": []}

    def listed(actor):
        return {row["damage_type"] for row in typed_reactions.defense_display(engine, actor)["resistances"]
                if "prayer" in (row["source"] or "").lower()}

    assert not listed(me)
    engine.typed_passive_rows = {**getattr(engine, "typed_passive_rows", {}), ME: [
        {"block": "path_passive", "feature_id": prayer.PRAYER, "kind": "shugenja"}]}
    engine._apply_condition(me, prayer.PATRON, prayer.PRAYER, ME, expires_on="UNTIL_REMOVED",
                            data={"patron": "earth", "label": "Elemental Patron: Earth"})

    assert prayer.narrow_resistance(engine, me, "BLUDGEONING", tagged, None)  # the fight's own answer
    assert prayer.narrow_resistance(engine, me, "BLUDGEONING", untagged, None) is None  # another element's blow
    assert listed(me) == {"Bludgeoning"}
    [bludgeoning] = [row for row in typed_reactions.defense_display(engine, me)["resistances"]
                     if row["damage_type"] == "Bludgeoning"]
    assert "Earth" in (bludgeoning["note"] or "")

    # a creature that recorded no patron has no such Resistance
    assert not listed(engine.state.actors[AN])



def test_a_patron_without_a_declared_element_names_elemental_prayer_as_its_source():
    """RESISTR13: the four patrons whose Resistance needs no packet are listed through the standing hook rows,
    and they name Elemental Prayer (not "Active effect") as what grants them."""
    from combat.ext import shugenja_prayer as prayer

    patron = next(name for name in prayer.PATRONS if name not in prayer.CHOICES)
    engine = _fight(_sheet(_kit(AXE), mids=[UNARMORED, STONE_SKIN]))
    me = engine.state.actors[ME]
    engine.typed_passive_rows = {**getattr(engine, "typed_passive_rows", {}), ME: [
        {"block": "path_passive", "feature_id": prayer.PRAYER, "kind": "shugenja"}]}
    engine._apply_condition(me, prayer.PATRON, prayer.PRAYER, ME, expires_on="UNTIL_REMOVED",
                            data={"patron": patron, "label": f"Elemental Patron: {patron.title()}"})

    kind = prayer.TYPES[patron].title()
    [row] = [r for r in typed_reactions.defense_display(engine, me)["resistances"]
             if r["damage_type"] == kind and r["source"] != "Stone Skin"]
    assert row["source"] != "Active effect" and "prayer" in row["source"].lower()
