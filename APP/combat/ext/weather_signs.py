"""The printed Weather Sign talents' Mantle, Shroud and Gather rows (Sphere of Weather).

Why this module exists: the six Weather Sign talents (Wind, Rain, Cold, Heat, Dry, Thunder) are printed in the
owner's Sphere Compendium ("### WEATHER SIGN TALENTS") and every Weather base ability points at them -- Sky Mantle
"the target gains that sign's Mantle effect", Cloud Shroud "apply its Shroud effect", Gather Weather "the area becomes
severity 1 of that sign's weather category" -- but the canonical catalog carries no record for them (see the report's
catalog-gap item), so nothing else in this repository knows what a Wind Shroud does. This module is that missing
printed table, in one place, and it is read by:

* ``weather_mantle.py`` -- a placed Sky Mantle's sign benefits, Defensive Weather, Weatherproof Mantle and
  Weather Backlash.
* ``weather_shroud.py`` -- a placed Cloud Shroud's saving throw and what a failure does, and Pressure-Cracking
  Shroud.

Gather Weather now records fields in weather_fields.py. Its public severity
query resolves compatible signs, cell-local opposition and Storm support for
Severe Shroud, Pressure-Cracking Shroud, Weather Cut and Stormlord's Finger.

Every row below is transcribed from the printed text (compendium lines 100169-100355, also
``APP/authority/typed_mechanics/rules_text.json`` for the abilities that quote them). Nothing here invents a number.

Sign ids are the lower-case printed names and are what a mantle or shroud condition stores in ``data["sign"]``, so a
saved fight keeps its sign across a reload. ``OTHER`` is the printed escape used when a table runs a Weather Sign the
six rows do not cover: nothing automated fires and the GM resolves it, exactly as before this table existed.

Realm steps are printed per sign ("At Foundation Realm ... At Core Formation ..."); ``by_realm`` maps the realm name to
the printed value and ``realm_at`` picks the highest band the character's Cultivation Level has reached
(``combat/table_advance.realm_of``).
"""

from __future__ import annotations

from typing import Any

SPHERE = "tianxia.sphere.weather"

#: The sign of a mantle or shroud the owner chose while the GM keeps it ("another sign").
OTHER = "other"

#: Each sign's printed weather category (the Gather expression's "severity 1 of that sign's weather category").
CATEGORIES = {
    "wind": "wind",
    "rain": "precipitation",
    "cold": "cold",
    "heat": "heat",
    "dry": "aridity",
    "thunder": "storm",
}

#: The printed opposing pairs of Four-Season Reversal, "Choose one opposing pair".
OPPOSING = {
    "cold": "heat",
    "heat": "cold",
    "rain": "dry",
    "dry": "rain",
    "wind": "stillness",
    "stillness": "wind",
    "thunder": "silence",
    "silence": "thunder",
}

#: Which sign a save or a damage packet is "about", read from the conditions and damage types the engine already
#: named for the save (``typed_save_modifiers``: "damage:fire", "deafened", ...). Used by Defensive Weather
#: ("Advantage ... if the Mantle's sign matches or opposes the effect's sign"). A sign the table cannot read is None,
#: and Defensive Weather leaves that save alone. Only names one of the printed signs actually produces are listed: an
#: effect that merely *could* be a sign's work is not read as one.
SIGNS_OF = {
    "damage:cold": "cold", "damage:fire": "heat", "damage:lightning": "thunder", "damage:thunder": "thunder",
    "chilled": "cold", "frozen": "cold", "restrained": "cold", "prone_by_storm": "thunder",
    "deafened": "thunder", "stunned": "thunder", "doused": "rain", "weather_doused": "rain", "poisoned": "dry",
}

#: The words that place the source of a pending save in Thunder's printed family: "saves against being Deafened, Stunned
#: or knocked Prone **by thunder, lightning or storm effects**". A save whose source says none of these is not one of
#: them, however the effect would end the creature, so an unrelated Deafening or Stunning effect is left alone. A save
#: that names its own Thunder Sign belongs here too: it *is* a thunder, lightning or storm effect.
THUNDER_SOURCE_WORDS = ("thunder", "lightning", "storm", "tempest")

#: The words that place the source of a pending save in the cold-weather family Heat's Weatherproof benefit names
#: ("Advantage on saves against **cold weather hazards**"). Every entry is a whole phrase that *names the weather* -- a
#: blizzard, an ice storm, a cold front, freezing wind -- and never a bare word an ordinary cold-damage technique may
#: carry in its own name: "Frost Bolt", "Freezing Touch" and "Glacial Edge" deal cold damage without being weather, so
#: those saving throws are not covered here and the printed manual instruction on the Heat row is what the table uses.
COLD_WEATHER_SOURCE_WORDS = ("cold weather", "blizzard", "ice storm", "cold front", "freezing wind")

#: The printed hazards a sign's own Mantle benefit (or Weatherproof Mantle) makes harder, each with the names
#: ``typed_save_modifiers`` gives a pending save, the sign the hazard is "about", and the source families the printed
#: line requires. A sign's printed advantage applies only to the hazard it names:
#:
#: ``names``    exact matches the engine named for the save (the condition or damage type the effect would inflict).
#: ``sources``  source families the printed line requires *as well as* the name, read by :func:`source_kinds`. Thunder's
#:              deafened/stunned rows require a thunder, lightning or storm source, so an unrelated effect that would
#:              Deafen or Stun gets no benefit. Cold ``cold_weather`` requires a cold-weather source, so an ordinary
#:              cold-damage spell gets none either. A row with no ``sources`` is answered by its name alone.
#: ``by_sign``  True only where the printed line names a *Sign* rather than a hazard ("against Cold Sign effects",
#:              "against Rain Sign Shrouds"), so a save that names that sign in ``typed["weather_sign"]`` is matched.
#:              It is False for hazard-named rows: naming a Sign is not by itself naming its weather, so a save that
#:              names the Cold Sign is not a cold-weather hazard unless ``sources`` confirms the source is one.
#: ``category`` True where the printed hazard *is* a whole weather category ("cold weather hazards"), so the printed
#:              Sign's own effect of that category is one of them: a Cold Sign Shroud's throw is cold weather, and it is
#:              matched only when :func:`source_kinds` confirms the source really is that category's weather.
HAZARDS = {
    "deafened": {"names": ("deafened",), "sign": "thunder", "sources": ("thunder",)},
    "stunned": {"names": ("stunned",), "sign": "thunder", "sources": ("thunder",)},
    "prone_by_storm": {"names": ("prone_by_storm",), "sign": "thunder"},
    "cold_sign": {"names": ("cold_sign",), "sign": "cold", "by_sign": True},
    "cold_weather": {"names": ("cold_weather", "damage:cold"), "sign": "cold", "sources": ("cold_weather",),
                     "category": True},
    "poison": {"names": ("poison", "poisoned", "damage:poison"), "sign": "dry"},
    "disease": {"names": ("disease",), "sign": "dry"},
    "dehydration": {"names": ("dehydration",), "sign": "dry"},
    "rain_shroud": {"names": ("rain_shroud", "weather_doused", "doused"), "sign": "rain", "by_sign": True},
}


def source_kinds(source: Any = "", ability: Any = "", save_sign: Any = "", named: Any = (),
                 *, weather_source: Any = False) -> set[str]:
    """Which printed hazard family the *source* of the pending save belongs to, from what the engine already knows.

    A family is only ever claimed from what the effect says about itself, never guessed from the subject it happens to
    hit:

    * **thunder** -- the save's source names thunder, lightning, storm or tempest; or the save names its own Thunder
      Sign, which *is* a thunder effect; or the engine named a single lightning or thunder damage type for it, so the
      save is against being Deafened or Stunned *by lightning*.
    * **cold_weather** -- the engine named the save ``cold_weather`` outright; or the save's source names an
      unambiguous cold-weather hazard (a phrase from :data:`COLD_WEATHER_SOURCE_WORDS`); or the save is a printed
      Weather Sign effect of the cold category, which ``weather_shroud`` identifies by putting the sign on the context.

    Anything else -- an ordinary cold-damage technique whose name merely contains "frost", an unrelated effect that
    would Deafen -- is in neither family, and returns an empty set. That is what leaves such a save without a printed
    advantage and hands it to the table's manual instruction instead.
    """
    text = f"{source} {ability}".lower()
    names = {str(name).lower() for name in (named or ())}
    kinds: set[str] = set()
    if (any(word in text for word in THUNDER_SOURCE_WORDS) or str(save_sign or "") == "thunder"
            or names & {"damage:lightning", "damage:thunder"}):
        kinds.add("thunder")
    if "cold_weather" in names or any(word in text for word in COLD_WEATHER_SOURCE_WORDS) or (
            str(save_sign or "") in cold_category() and bool(weather_source)):
        kinds.add("cold_weather")
    return kinds


def cold_category() -> frozenset[str]:
    """The printed sign ids whose own weather category is cold, so a Cold Sign effect can be recognised as cold weather."""
    return frozenset(sign_id for sign_id, row in SIGNS.items() if str((row.get("category") or "")) == "cold")


def hazard_matches(own: Any, named: Any, *, save_sign: str = "", kinds: Any = frozenset()) -> bool:
    """Whether a sign's own printed save advantages apply to the save now pending.

    ``own`` is the Mantle's stored ``save_advantage`` list (the printed hazards it helps with), ``named`` the names
    ``typed_executor.typed_save_modifiers`` gave the save, ``save_sign`` the sign the save itself names (a Weather
    Shroud throw) and ``kinds`` what :func:`source_kinds` read from that save's source. A printed advantage applies when
    the engine named one of its hazards *and* the source is the family the printed line requires; for a hazard that is a
    whole weather category it also applies to that Sign's own effect of that category, but only once the source is
    confirmed to be that category's weather; and -- only for the rows whose printed line names a Sign -- when the save
    says which Weather sign it belongs to. Nothing else does.
    """
    names = {str(name).lower() for name in (named or ())}
    families = {str(value) for value in (kinds or ())}
    for name in {str(value).lower() for value in (own or ())}:
        row = HAZARDS.get(name)
        if not row:
            continue
        needed = {str(value) for value in row.get("sources") or ()}
        if names & {str(value) for value in row["names"]} and (not needed or families & needed):
            return True
        if row.get("category") and needed and families & needed and str(row.get("sign") or "") == str(save_sign or ""):
            return True
        if row.get("by_sign") and str(row.get("sign") or "") == str(save_sign or ""):
            return True
    return False


def pending_sign(typed: Any) -> str:
    """The Weather Sign a pending save belongs to, when the ability that asked for it named one.

    ``combat/ext/weather_shroud.py`` writes ``typed["weather_sign"]`` on the context it builds for a Shroud's throw, so
    "a saving throw against a Cold Sign effect" can be answered even when the Shroud's printed rows are only a Speed
    change and name no condition at all. Anything else is "" and every reader leaves the save alone.
    """
    value = str((typed or {}).get("weather_sign") or "")
    return value if value in SIGNS else ""

#: The printed Shroud markers with no plain typed rule, and what each one means for a player, in their own words.
#: Shared by ``weather_shroud.py`` (which applies them) and ``weather_mantle.py`` (Weather Backlash's Rain rider
#: douses the attacker with the same one), and put on the applied condition as its plain chip text.
MARKERS = {
    "weather_doused": "it is doused (soaked through): a doused creature can spend its Bonus Action to shake, scrape, "
                      "heat or wipe off the water, which ends the dousing early",
    "weather_ranged": "its ranged weapon attacks have Disadvantage",
    "weather_cold_save": "the next saving throw it makes against a Cold Sign effect has Disadvantage",
    "weather_con_save": "its next Constitution saving throw has Disadvantage",
    "no_cold_gear": "it cannot benefit from nonmagical cold-weather gear",
}

#: The printed durations, each as the expiry name the engine removes (tests/test_expiry_names.py KNOWN). The
#: printed Shroud rows say "until the start of **its** next turn" (the shrouded creature), "until the start of
#: **your** next turn" (the one who placed the Shroud) and "before the end of **its** next turn".
TARGET_NEXT_START = "START_OF_TARGET_NEXT_TURN"  # until the start of its next turn
SOURCE_NEXT_START = "START_OF_SOURCE_NEXT_TURN"  # until the start of your next turn (the Shroud's owner)
HOLDER_NEXT_END = "END_OF_HOLDER_NEXT_TURN"      # before the end of its next turn

#: The printed "up to 1 minute" a Cloud Shroud lasts, and a Persistent Shroud's "remaining duration" (it only stops
#: asking for Concentration; the minute is unchanged). Ten rounds, as combat/ext/effect_durations.py counts them.
MINUTE_ROUNDS = 10


def owner_start(engine: Any, owner: Any) -> str:
    """The expiry name for "until the start of **your** next turn" when **you** placed the Shroud.

    The engine's ``START_OF_SOURCE_NEXT_TURN`` is the *applier's* turns, and a modifier records whoever is acting when it
    is applied -- so a Shroud's repeated throw at the end of the *victim's* turn would expire at the start of the victim's
    next turn. This names the owner's own turn explicitly (``combat/ext/effect_durations.token``), which is the clock the
    printed words use, and it is worked out again at every throw so a later round's penalty is not already expired.
    """
    from . import effect_durations

    return effect_durations.token("start", owner.entity_id, int(owner.turns_started) + 1)


def anchored(rows: list[dict[str, Any]], token: str) -> list[dict[str, Any]]:
    """The Shroud's rows with every printed "until the start of your next turn" pointed at the owner's own turn clock."""
    return [{**row, "expires_on": token} if row.get("expires_on") == SOURCE_NEXT_START else row for row in rows]

#: Short, plain descriptions of what each sign does with a Mantle (a Shroud) and with a gathered field. Shown to the
#: player when they pick the sign, because "choose one Weather Sign talent you know" means nothing without them.
PLAIN = {
    "wind": "Wind speeds a creature up (+10 feet, more at higher realms) and makes melee hits against it harder; "
            "its Shroud pushes a creature away and spoils its next ranged attack.",
    "rain": "Rain helps a creature escape grapples and shrug off fire; its Shroud soaks a creature, slows it and "
            "spoils its next saving throw against cold weather.",
    "cold": "Cold lets a creature stride over ice and mud and, at Foundation Realm, shrug off cold damage; its Shroud "
            "halves a creature's Speed, and stops it dead if that is too little.",
    "heat": "Heat gives a creature your Proficiency Bonus in Temporary Hit Points at the start of each of its turns; "
            "its Shroud scalds it for 1d6 plus your Weather ability modifier and stops it benefiting from cold gear.",
    "dry": "Dry helps a creature shrug off poison, disease and thirst and carry heavy loads; its Shroud poisons a "
            "creature with dust, or leaves it worse at its next Constitution saving throw.",
    "thunder": "Thunder makes a creature harder to deafen, stun or knock down with storm effects, and its Shroud "
               "deafens a creature and hurts it for 1d6 plus your Weather ability modifier thunder damage.",
}


#: The printed band names of a sign row's realm steps, in order, keyed the way combat/table_advance.realm_of names them.
BANDS = ("Mortal", "Foundation", "Core Formation", "Nascent Soul", "Immortal")

#: How the printed text writes each band ("At Foundation Realm ...", "at Mortal Realm").
PRINTED_BAND = {"Mortal": "Mortal Realm", "Foundation": "Foundation Realm", "Core Formation": "Core Formation",
                "Nascent Soul": "Nascent Soul", "Immortal": "Immortal"}


def realm_at(cl: int) -> str:
    """The realm band a Cultivation Level has reached, in combat/table_advance.realm_of's names."""
    from ..table_advance import realm_of

    return realm_of(int(cl or 1))


def by_realm(table: dict[str, Any], cl: int) -> Any:
    """The printed value for this character's realm.

    A sign row keys its steps by the printed band name ("Foundation Realm", "Core Formation", "Nascent Soul") and its
    starting value under "base"; the last step at or below the creature's band wins, as the printed "The damage
    becomes 2d6 at Foundation Realm" reads.
    """
    if not table:
        return None
    reached = BANDS.index(realm_at(cl))
    for index in range(reached, -1, -1):
        key = PRINTED_BAND[BANDS[index]]
        if key in table:
            return table[key]
    return table.get("base")


def opposes(one: str | None, other: str | None) -> bool:
    """Whether two signs are the printed opposing pair of Four-Season Reversal."""
    if not one or not other:
        return False
    if one == other:
        return False
    return OPPOSING.get(one) == other


def matches_or_opposes(mantle_sign: str | None, effect_signs: set[str]) -> bool:
    """Sky Mantle's Defensive Weather: the Mantle's sign "matches or opposes the effect's sign"."""
    if not mantle_sign or not effect_signs:
        return False
    return mantle_sign in effect_signs or any(opposes(mantle_sign, sign) for sign in effect_signs)


def signs_of_save(named: set[str]) -> set[str]:
    """The signs a pending save can be read as, from the conditions and damage types typed_executor named for it."""
    out = {SIGNS_OF[name] for name in (named or set()) if name in SIGNS_OF}
    if "damage:cold" in named:
        out.add("cold")
    return out


BLOCK = "weather"


def rows_of(engine: Any, actor: Any, kind: str) -> list[dict[str, Any]]:
    """The owned feature-block rows of one Weather kind.

    The marker rows live in ``combat/rules/feature_blocks.d/auto13_weather.json`` (block "weather", one row per
    printed talent, each with the "why" of what this package does for it) and are compiled once, by
    :func:`block`. Shared by ``weather_mantle.py`` and ``weather_shroud.py``, which read them to decide whether a
    printed talent is in force.
    """
    return [row for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, [])
            if row.get("block") == BLOCK and row.get("kind") == kind]


def owns(engine: Any, actor: Any, kind: str) -> bool:
    """Whether the creature owns the printed talent of that kind."""
    return bool(rows_of(engine, actor, kind))


def names() -> list[str]:
    """The six printed sign ids, in printed order."""
    return ["wind", "rain", "cold", "heat", "dry", "thunder"]


# ----------------------------------------------------------------------------------------------- the printed rows
#
# mantle:   what a creature with the Sky Mantle of this sign gains while the sign is active.
# shroud:   the printed saving throw of this sign's Shroud and what a failure or a success does, written as
#           ordinary typed effect rows (the engine's own vocabulary, combat/typed_executor.py: "damage", "speed",
#           "condition", "forced_movement"), so a Shroud's outcome runs through the same save, Resistance,
#           condition-reaction and damage paths as every other typed ability. Each row's "expires_on" is one of
#           the three printed durations named above, so nothing lasts past the turn the text names.
# severe:   Severe Shroud's "apply one of the following" rider for this sign.
# backlash: Weather Backlash's damage type and rider for this sign.
# weatherproof: Weatherproof Mantle's printed Resistance (and saves) for this sign.
# gather:   the printed Gather expression, quoted for the field's own description.
#
# The printed outcomes with no plain typed rule are the markers in ``MARKERS``; each one is applied as a real
# condition whose chip says what it means in the player's own words, and read back from the live creature.

SIGNS: dict[str, dict[str, Any]] = {
    "wind": {
        "name": "Wind Sign",
        "category": "wind",
        "mantle": {
            "speed_ft": {"base": 10, "Foundation Realm": 15, "Core Formation": 20, "Nascent Soul": 30},
            "opportunity_disadvantage_ft": 10,
            "plain": "+10 feet Speed (more at higher realms); attacks against it that provoke an Opportunity Attack "
                      "have Disadvantage once it has moved 10 feet or more this turn",
        },
        "shroud": {
            "ability": "STR",
            "evidence": "The shrouded creature makes a Strength saving throw.",
            "fail": [{"type": "forced_movement", "applies_to": "target", "flat": 10, "direction": "away",
                      "evidence": "it is pushed 10 feet in a direction you choose"},
                     {"type": "condition", "condition": "weather_ranged", "applies_to": "target",
                      "expires_on": TARGET_NEXT_START,
                      "evidence": "Disadvantage on ranged weapon attacks until the start of its next turn"}],
            "success": [{"type": "condition", "condition": "weather_ranged", "applies_to": "target", "next": 1,
                         "expires_on": TARGET_NEXT_START,
                         "evidence": "still has Disadvantage on its next ranged weapon attack before the start of its next turn"}],
            "push_ft": {"base": 10, "Core Formation": 15, "Nascent Soul": 20},
        },
        "severe": "Wind: the target is pushed 10 feet.",
        "backlash": {"damage_types": ["slashing", "piercing"], "choose": True,
                     "plain": "the attacker takes slashing or piercing damage equal to your Proficiency Bonus"},
        "weatherproof": {"damage_resistances": [], "save_advantage": [],
                         # "Resistance to nonmagical ranged weapon damage" names the attack, not the damage type, so the
                         # engine's damage-type Resistance cannot hold it: weather_mantle.weatherproof_defense answers it
                         # through the shared damage_defenses seam instead (a ranged weapon attack that is not magical).
                         "restricted_defense": "ranged_nonmagical_weapon",
                         "plain": "Wind grants Resistance to nonmagical ranged weapon damage"},
        "gather": "Your Gather Weather creates whipping wind. The area lightly scatters mist, smoke, loose paper, "
                  "dust, and Tiny unattended flames.",
    },
    "rain": {
        "name": "Rain Sign",
        "category": "precipitation",
        "mantle": {
            "escape_advantage": True,
            "damage_resistances": [],
            "forced_damage_resistances": ["FIRE"],
            "plain": "Advantage on ability checks to escape a Grapple or move through a hostile creature's space, "
                     "and Resistance to fire damage while the weather around it is Precipitation severity 1 or "
                     "higher, or while you force the sign with Cultivation Points",
            # The forced half of that Resistance is automated; the gathered-weather half is not, because this repository
            # has no gathered-weather state to read (there is no weather field), so the table judges it.
            "manual": ["Resistance to fire damage while Precipitation severity 1 or higher is gathered around it (there "
                       "is no gathered-weather state here, so that half is the table's to judge; forcing the sign covers "
                       "the same Resistance either way)"],
        },
        "shroud": {
            "ability": "CON",
            "evidence": "The shrouded creature makes a Constitution saving throw.",
            "fail": [{"type": "condition", "condition": "weather_doused", "applies_to": "target",
                      "expires_on": TARGET_NEXT_START, "evidence": "it is doused"},
                     {"type": "speed", "applies_to": "target", "flat": -10, "expires_on": SOURCE_NEXT_START,
                      "evidence": "its Speed is reduced by 10 feet until the start of your next turn"},
                     {"type": "condition", "condition": "weather_cold_save", "applies_to": "target", "next": 1,
                      "expires_on": HOLDER_NEXT_END,
                      "evidence": "Disadvantage on the next saving throw it makes against a Cold Sign effect before the end of its next turn"}],
            "success": [{"type": "condition", "condition": "weather_doused", "applies_to": "target",
                         "expires_on": TARGET_NEXT_START,
                         "evidence": "it is doused until the start of its next turn but suffers no Speed penalty"}],
        },
        "severe": "Rain: the target is doused and cannot take Reactions.",
        "backlash": {"damage_types": ["bludgeoning"],
                     "condition": {"condition": "weather_doused", "duration": TARGET_NEXT_START},
                     "plain": "the attacker takes bludgeoning damage equal to your Proficiency Bonus and is doused"},
        "weatherproof": {"damage_resistances": ["FIRE"], "save_advantage": [],
                         "plain": "Rain grants Resistance to fire damage"},
        "gather": "Your Gather Weather creates mist, fog, drizzle, rain, or cloud cover appropriate to the temperature.",
    },
    "cold": {
        "name": "Cold Sign",
        "category": "cold",
        "mantle": {
            "damage_resistances_by_realm": {"Foundation Realm": ["COLD"]},
            "plain": "It ignores difficult terrain caused by ice, snow, mud, shallow water, frost or slick ground, and "
                     "moves 10 feet faster across it; at Foundation Realm it also has Resistance to cold damage",
            # The engine's difficult-terrain reader (combat/motion.py ignores_difficult) answers yes or no for a creature,
            # with no way to restrict it to ground of these kinds, so the printed terrain benefit is put to the table
            # rather than quietly widened to every difficult surface in the fight.
            "manual": ["ignoring difficult terrain caused by ice, snow, mud, shallow water, frost or slick ground (the "
                       "table's difficult ground has no kind to check, so this is settled at the table)",
                       "moving 10 feet faster across that ground (there is no terrain-conditional Speed bonus)"],
        },
        "shroud": {
            "ability": "CON",
            "evidence": "The shrouded creature makes a Constitution saving throw.",
            "fail": [{"type": "speed", "applies_to": "target", "halved": True, "expires_on": TARGET_NEXT_START,
                      "evidence": "its Speed is reduced by half until the start of its next turn",
                      "restrained_below_ft": 5}],
            "success": [{"type": "speed", "applies_to": "target", "flat": -10, "expires_on": TARGET_NEXT_START,
                         "evidence": "its Speed is reduced by 10 feet until the start of its next turn"}],
        },
        "severe": "Cold: the target's Speed becomes 0.",
        "backlash": {"damage_types": ["cold"], "plain": "the attacker takes cold damage equal to your Proficiency Bonus"},
        "weatherproof": {"damage_resistances": ["COLD"], "save_advantage": [],
                         "plain": "Cold grants Resistance to cold damage"},
        "gather": "Your Gather Weather creates frost, rimed surfaces, chilled breath, and slick ground.",
    },
    "heat": {
        "name": "Heat Sign",
        "category": "heat",
        "mantle": {
            "temp_hp": {"formula": "pb"},
            "save_advantage_by_realm": {"Core Formation": ["cold_sign"]},
            "plain": "It gains Temporary Hit Points equal to your Proficiency Bonus at the start of each of its turns "
                     "while the Mantle lasts; at Core Formation it also has Advantage on saves against Cold Sign effects",
        },
        "shroud": {
            "ability": "CON",
            "evidence": "The shrouded creature makes a Constitution saving throw.",
            "damage": {"damage_types": ["fire"], "formula": "key_ability_modifier",
                       "dice_by_cl": [[1, 4, 1, 6], [5, 9, 2, 6], [10, 14, 3, 6], [15, 20, 4, 6]],
                       "evidence": "it takes fire damage equal to 1d6 + your Weather key ability modifier (2d6 at Foundation Realm, 3d6 at Core Formation, 4d6 at Nascent Soul)"},
            "fail": [{"type": "condition", "condition": "no_cold_gear", "applies_to": "target",
                      "expires_on": TARGET_NEXT_START,
                      "evidence": "it cannot benefit from nonmagical cold-weather gear until the start of its next turn"}],
            "success": [],
        },
        "severe": "Heat: the target cannot regain hit points.",
        "backlash": {"damage_types": ["fire"], "plain": "the attacker takes fire damage equal to your Proficiency Bonus"},
        "weatherproof": {"damage_resistances": ["FIRE"], "save_advantage": ["cold_weather"],
                         # The printed line is "cold weather hazards", not every source of cold damage, so an ordinary
                         # cold-damage spell is not covered. Where the engine cannot tell that a save really is against
                         # cold weather, the table decides -- but only after establishing that the cause *was* cold
                         # weather, which is what the printed restriction asks for.
                         "manual": ["if the table establishes that a saving throw is against cold weather -- a blizzard, "
                                    "freezing wind, an ice storm or a cold front -- and the game could not tell that "
                                    "from the ability causing it, grant that saving throw Advantage yourself; an "
                                    "ordinary technique that merely deals cold damage is not a cold-weather hazard"],
                         "plain": "Heat grants Resistance to fire damage and Advantage on saves against cold weather hazards"},
        "gather": "Your Gather Weather creates oppressive heat, heat shimmer, and mirage distortion.",
    },
    "dry": {
        "name": "Dry Sign",
        "category": "aridity",
        "mantle": {
            "save_advantage": ["poison", "disease", "dehydration", "rain_shroud"],
            "carry_bonus": "pb",
            "damage_resistances_by_realm": {"Core Formation": ["NECROTIC"]},
            "plain": "Advantage on saving throws against poison, disease, dehydration and Rain Sign Shrouds, and your "
                     "Proficiency Bonus added to its Strength checks to carry, drag, lift or hold supplies",
            # The engine weighs a load against a carrying capacity (combat/carry.py) and makes no Strength check to
            # carry, drag, lift or hold, so this printed bonus has nothing to add to and is the table's to apply.
            "manual": ["your Proficiency Bonus added to its Strength checks to carry, drag, lift or hold supplies "
                       "(the table weighs a load against a carrying capacity rather than making a Strength check)"],
        },
        "shroud": {
            "ability": "CON",
            "evidence": "The shrouded creature makes a Constitution saving throw.",
            "fail": [{"type": "condition", "condition": "poisoned", "applies_to": "target",
                      "expires_on": TARGET_NEXT_START,
                      "evidence": "it is Poisoned until the start of its next turn as dust and dryness disrupt it"}],
            "success": [{"type": "condition", "condition": "weather_con_save", "applies_to": "target", "next": 1,
                         "expires_on": HOLDER_NEXT_END,
                         "evidence": "Disadvantage on the next Constitution saving throw it makes before the end of its next turn"}],
        },
        "severe": "Dry: the target cannot benefit from temporary hit points.",
        "backlash": {"damage_types": ["necrotic"],
                     "plain": "the attacker takes necrotic damage equal to your Proficiency Bonus"},
        "weatherproof": {"damage_resistances": [], "save_advantage": ["dehydration"],
                         # "Resistance to necrotic damage from desiccation": the engine's Resistances name a whole damage
                         # type, and nothing in the damage packet says whether it came from drying a creature out. Granting
                         # plain necrotic Resistance would be broader than the printed words, so this half is stated for the
                         # table instead (the Advantage on dehydration saves is automated).
                         "manual": ["Resistance to necrotic damage from desiccation (which necrotic damage counts as "
                                    "desiccation is yours to decide; no blanket Resistance to necrotic damage is "
                                    "granted here)"],
                         "plain": "Dry grants Resistance to necrotic damage from desiccation and Advantage on saves against dehydration"},
        "gather": "Your Gather Weather creates dry air, dust, cracked lips, thirsty breath, and thirsty earth.",
    },
    "thunder": {
        "name": "Thunder Sign",
        "category": "storm",
        "mantle": {
            "death_save_advantage": True,
            "save_advantage": ["deafened", "stunned", "prone_by_storm"],
            # "Once during the Mantle, when the mantled creature is hit by a melee attack, the attacker takes lightning or
            # thunder damage equal to your Proficiency Bonus": the Thunder Mantle's own printed benefit, once per Mantle.
            "melee_backlash": {"damage_types": ["lightning", "thunder"], "choose": True},
            "plain": "Advantage on death saving throws and on saves against being Deafened, Stunned or knocked Prone by "
                     "thunder, lightning or storm effects; once during the Mantle, a melee hit on the mantled creature "
                     "burns the attacker for your Proficiency Bonus lightning or thunder damage",
            # The printed line is limited to a thunder, lightning or storm source, and an effect from elsewhere that
            # would Deafen or Stun is not one of them. So the table's half is never "grant it when in doubt": it is
            # "grant it once you have established that the cause really was thunder, lightning or storm and the game
            # could not tell that by itself".
            "manual": ["if an effect would Deafen or Stun it, decide first what caused it: this printed benefit "
                       "covers only an effect that came from thunder, lightning or a storm. When the table has "
                       "established that cause and the game could not recognise it on its own, grant that saving "
                       "throw Advantage yourself. An effect from anywhere else, or one whose cause the table cannot "
                       "settle, gets nothing here."],
        },
        "shroud": {
            "ability": "CON",
            "evidence": "The shrouded creature makes a Constitution saving throw.",
            "damage": {"damage_types": ["thunder"], "formula": "key_ability_modifier",
                       "dice_by_cl": [[1, 4, 1, 6], [5, 9, 2, 6], [10, 14, 3, 6], [15, 20, 4, 6]],
                       "evidence": "it takes thunder damage equal to 1d6 + your Weather key ability modifier (2d6 at Foundation Realm, 3d6 at Core Formation, 4d6 at Nascent Soul)"},
            "fail": [{"type": "condition", "condition": "deafened", "applies_to": "target",
                      "expires_on": TARGET_NEXT_START, "evidence": "it is Deafened until the start of its next turn"}],
            "success": [],
        },
        "severe": "Thunder: the target is Deafened and cannot take Reactions.",
        "backlash": {"damage_types": ["lightning", "thunder"], "choose": True,
                     "plain": "the attacker takes lightning or thunder damage equal to your Proficiency Bonus"},
        # "Thunder grants Resistance to lightning or thunder damage, chosen when the Mantle is placed": one of the two.
        "weatherproof": {"choose_damage_types": ["LIGHTNING", "THUNDER"], "damage_resistances": [], "save_advantage": [],
                         "plain": "Thunder grants Resistance to lightning or thunder damage, chosen when the Mantle is placed"},
        "gather": "If the gathered area already contains Wind severity 1 or higher and Rain or Dry severity 1 or "
                  "higher, it becomes Storm severity 1.",
    },
}


def sign(sign_id: Any) -> dict[str, Any] | None:
    """The printed row for one sign id, or None for an unknown or GM-run sign."""
    return SIGNS.get(str(sign_id or ""))


def plain(sign_id: Any) -> str:
    """A one-line plain description of what the sign does with a Mantle and a Shroud."""
    row = sign(sign_id)
    if row is None:
        return ""
    return f"{row['name']}: a Mantle {row['mantle']['plain']}; a Shroud makes a {row['shroud']['ability']} saving throw."


def marker_label(name: Any) -> str:
    """The plain chip text for one of the printed Shroud markers (``MARKERS``)."""
    return MARKERS.get(str(name or ""), "")


def shroud_rows(sign_id: Any, cl: int) -> dict[str, Any]:
    """The printed Shroud's typed effect rows for this character's realm.

    Returns ``{"save": <ability>, "fail": [...], "success": [...]}``. The realm scaling of the Heat and Thunder
    Shroud dice is folded in (``dice_by_cl`` rows are the engine's own Cultivation-Level table) and the Wind
    Shroud's printed push distance is filled in. Each marker row carries its plain text, so the condition chip a
    player sees says what the printed Shroud does. Nothing else is decided here.
    """
    row = sign(sign_id)
    if row is None:
        return {}
    shroud = row["shroud"]
    push = by_realm(shroud.get("push_ft"), cl)
    out: dict[str, Any] = {"save": str(shroud.get("ability") or "CON").upper(), "ability": str(shroud.get("ability") or "CON").lower(),
                           "fail": [], "success": [], "evidence": shroud.get("evidence") or ""}
    damage = shroud.get("damage")
    for branch in ("fail", "success"):
        for effect in shroud.get(branch) or []:
            effect = dict(effect)
            if effect.get("type") == "forced_movement" and push is not None:
                effect["flat"] = effect["distance_ft"] = int(push)
            if effect.get("type") == "speed" and effect.get("halved"):
                out["speed_halved_below_ft"] = int(effect.get("restrained_below_ft") or 0)
            if effect.get("type") == "condition" and effect.get("condition") in MARKERS:
                effect["condition_label"] = marker_label(effect["condition"])
                # "the next ..." is a one-shot: the applied condition remembers it, so the marker is used up by the
                # save or attack it spoiled and cannot spoil a second one.
                if effect.get("next"):
                    effect["condition_data"] = {"next": 1}
            out[branch].append(effect)
        if damage and branch == "fail":
            row_damage = {"type": "damage", "applies_to": "target", **damage}
            out["fail"].insert(0, row_damage)
    return out
