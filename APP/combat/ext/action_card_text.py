"""Card text for plug-in and system-built actions (FD-16: no battle button may render with an empty body).

A compiled ActionDefinition draws its card body from combat/action_text.py's one resolution order:
its own parameters["description"], then every plug-in's button_description hook, then the printed
record its typed.source/source_definition_id names, then the table's compiled evidence. A plug-in
that builds a button without any of those (a sub-choice of a talent, a mode toggle, a mount action, a
system-generated escape) renders a card with a title and no words -- the reported "Break Chains of Qi"
card ("Action / Range Self / Words used: Qi") is one of them.

This module is the data table those buttons read. It is a plug-in, like every other file in
combat/ext: the core card builder stays generic, and each entry owns its own button's words. An
entry is (a) one lead sentence stating the facts a player needs before pressing the button -- the
action slot, the cost, the range, the check or save, the target, the duration -- read from the code
that builds that button, and (b) the printed record id whose rulebook text the button applies,
rendered through combat/rule_help.printed_rule_text so the body is the book's own words rather than a
paraphrase. A button with no printed record of its own carries the lead sentence alone.

Keys are the button's compiled name -- the part of source_definition_id after
"action:typed.<character-id>." -- so one entry serves every character that owns the talent, and a save
file's own compiled button keeps its text across compiles. A new plug-in button should add its entry
here (or supply its own description/button_description); tests/test_fd16_empty_cards.py fails on any
player-visible card that would still render empty.

This module must never take words away from a plug-in that already describes its own button. The card
body is resolved first-non-empty over the button_description hooks (combat/action_text.py), in module
name order, and this module sorts first -- so every entry yields to any other hook that already answers
for the same row. Only a key named in SUPERSEDES may speak for a button another hook also answers.
"""

from __future__ import annotations

from typing import Any

from . import hook, invoke, subscribers

# key -> (lead sentence, printed record id or "" when the button has no record of its own)
CARDS: dict[str, tuple[str, str]] = {
    # --- Qi Seals: the escape from Chains of Qi ------------------------------------------------------
    "qi5_break_chains": (
        "Action: choose one set of Chains of Qi holding you, then make a Strength check or a Cultivation "
        "Check against the chains' save DC (a flat DC, not a contest, and no cultivation points). Success "
        "ends that set of chains; the chains were placed with the rules below.",
        "tianxia.subpath.qi.cultivator_of_seals.feature.chains_of_qi"),
    # --- Illusion: figments -------------------------------------------------------------------------
    "figment.control": (
        "Action, 60 feet, 1 Cultivation Point: make a Cultivation Check against the creator's Cultivation "
        "Save DC to take control of one figment you can perceive, while you hold Concentration on it.",
        "TAL_ILLUSION_CONTROL_FIGMENT"),
    "figment.create.bonus": (
        "Bonus Action instead of an Action: create one figment. The cultivation point cost, size and every "
        "rule below are unchanged.",
        "TAL_ILLUSION_CREATE_FIGMENT"),
    "figment.minor.create.bonus": (
        "Bonus Action instead of an Action, and no cost: create your Minor Illusion, following every rule "
        "below.",
        "TAL_ILLUSION_MINOR_ILLUSION"),
    # --- Shield faces -------------------------------------------------------------------------------
    "flexible_cover.bonus": (
        "Bonus Action and 1 Martial Focus (free of the Focus with Moving Rampart): stand a Shield Face on "
        "one edge of your space until the start of your next turn.",
        "TAL_SHIELD_FLEXIBLE_COVER"),
    "flexible_cover.turn": (
        "Free, once per turn, while Moving Rampart is active: turn your Shield Face to another edge of your "
        "space. Without Moving Rampart the same turn costs your Reaction.",
        "TAL_SHIELD_FLEXIBLE_COVER"),
    "seal_the_breach.turn": (
        "Free, once per turn: turn your Seal the Breach Barrier to another edge of your space.",
        "TAL_SHIELD_SEAL_THE_BREACH"),
    # --- The Hidden Eye -----------------------------------------------------------------------------
    "hidden_focus": (
        "Bonus Action, 120 feet: regain 1 Martial Focus. Offered only while you are hidden from every enemy "
        "within range, and only while you hold no Martial Focus.",
        "TAL_THE_HIDDEN_EYE_HIDDEN_FOCUS"),
    "adroit_focus": (
        "Bonus Action: regain 1 Martial Focus. Offered only when a creature you Analyzed was reduced to 0 "
        "Hit Points this round, and only while you hold no Martial Focus.",
        "TAL_THE_HIDDEN_EYE_ADROIT_FOCUS"),
    "riders14.court_analyze": (
        "Bonus Action while your Court of the Hidden Eye Domain is up, and no Martial Focus: take the "
        "Analyze action against a creature you can perceive. The Domain's own benefits are below.",
        "TAL_THE_HIDDEN_EYE_COURT_OF_THE_HIDDEN_EYE"),
    "riders14.court_search": (
        "Bonus Action while your Court of the Hidden Eye Domain is up: take the Search action with your own "
        "Perception bonus.",
        "TAL_THE_HIDDEN_EYE_COURT_OF_THE_HIDDEN_EYE"),
    "riders14.discern": (
        "Bonus Action and 1 Martial Focus: allies of your choice within 30 feet gain your Discern Illusions "
        "benefit for a number of rounds equal to your key ability modifier (at least 1).",
        "TAL_THE_HIDDEN_EYE_DISCERN_ILLUSIONS"),
    # --- Berserker / Wrestling / Iron Fist ----------------------------------------------------------
    "savage": (
        "Bonus Action: regain 1 Martial Focus after you reduce an eligible creature to 0 Hit Points with a "
        "melee or thrown weapon attack (or an Unarmed Strike), and only while you hold none.",
        "TAL_BERSERKER_SAVAGE"),
    "unarmed.grapple.tackle": (
        "Bonus Action in a turn you took the Dash action as your Action: attempt the Unarmed Strike's "
        "Grapple option against one creature within reach, using the same Strength or Dexterity save "
        "against your grapple DC, and with the attack that option normally replaces taken out.",
        "TAL_WRESTLING_TACKLE"),
    "dragon_step_clinch.maintain": (
        "No action: hold a grapple with a body clinch instead of a free hand. Your Speed drops by 10 feet "
        "while it lasts and the held creature gains Advantage on checks to escape unless it was Opened when "
        "the grapple began; you cannot maintain it while Prone, Restrained or Incapacitated.",
        "TAL_IRON_FIST_DRAGON_STEP_CLINCH"),
    "dragon_step_clinch.end": (
        "No action: end the body clinch. The grapple itself is unaffected.",
        "TAL_IRON_FIST_DRAGON_STEP_CLINCH"),
    # --- Formations ---------------------------------------------------------------------------------
    "formation.repair.restore": (
        "Action, 60 feet, 1 Cultivation Point: a damaged Node or Eye of your own array regains 2d8 + your "
        "Formation key ability modifier (3d8 at CL 11, 4d8 at CL 17), never above its maximum.",
        "tianxia.talent.formations.array_repair"),
    "formation.repair.undisrupt": (
        "Action, 60 feet, 1 Cultivation Point: end the disruption on one disrupted Node or Eye of your own "
        "array. No check is made.",
        "tianxia.talent.formations.array_repair"),
    # --- Blacksmith ---------------------------------------------------------------------------------
    "tempering_sequence.hardening": (
        "Action: spend every Forge Mark you placed on one workpiece (at least 3) for a Hardening Sequence. "
        "A weapon or tool gains +1 to attack rolls or its relevant checks; armor or a shield gains +1 AC.",
        "tianxia.talent.blacksmith.tempering_sequence"),
    "tempering_sequence.softening": (
        "Action: spend every Forge Mark you placed on one workpiece (at least 3) for a Softening Sequence. "
        "The next repair, crafting, modification or disarm attempt on it before the scene ends has Advantage.",
        "tianxia.talent.blacksmith.tempering_sequence"),
    "tempering_sequence.purifying": (
        "Action: spend every Forge Mark you placed on one workpiece (at least 3) for a Purifying Sequence. "
        "One mundane impurity, rust, poison residue, rot, corrosion or crafting complication on it is "
        "reduced; a magical curse or artifact flaw only if the GM allows it.",
        "tianxia.talent.blacksmith.tempering_sequence"),
    "tempering_sequence.awakening": (
        "Action: spend every Forge Mark you placed on one workpiece (at least 3) for an Awakening Sequence.",
        "tianxia.talent.blacksmith.tempering_sequence"),
    "field_repair.close_crack": (
        "Reaction and 1 Cultivation Point (CL 5+): a creature within reach has a weapon, shield, armor, tool "
        "or object damaged, so Set the Workpiece to it, place 1 Forge Mark, and Close the Crack on the same "
        "object as part of that one Reaction.",
        "tianxia.talent.blacksmith.field_repair"),
    "blacksmith.living_forge_mark": (
        "No action, once per turn while Incarnation of the Living Forge lasts: place 1 Forge Mark on a "
        "current workpiece.",
        "tianxia.talent.blacksmith.incarnation_of_the_living_forge"),
    # --- Flowers ------------------------------------------------------------------------------------
    "blossom.delayed_free": (
        "No action, once per turn while Ten-Thousand Bloom Scripture lasts: cause one of your dormant "
        "Blossoms within 60 feet to bloom. You still choose the Blossom talent and pay its CP cost (the "
        "Scripture reduces the first talent each turn by 1, minimum 1).",
        "TAL_FLOWERS_DELAYED_BLOOM"),
    # --- Weather / Trap -----------------------------------------------------------------------------
    "weather.thunder_shroud_move": (
        "No action, once per round: move your Thunder Shroud from the creature carrying it to another "
        "creature within 30 feet of that creature; the new target immediately makes the Shroud's saving "
        "throw.",
        "TAL_WEATHER_LIGHTNING_CHOOSES_THE_ROD"),
    "warn_trap": (
        "No action, 300 feet: warn any creatures you can see about one of your placed traps. A warned "
        "creature does not trigger that trap unless it chooses to.",
        "TAL_TRAP_WARNING_TRIGGER"),
    # --- Gravity ------------------------------------------------------------------------------------
    "gravity.anchor_share": (
        "Free, and only while Body Heavying is active: choose one willing ally within 5 feet. Forced "
        "movement against that ally is 10 feet shorter until the start of your next turn.",
        "TAL_GRAVITY_ANCHOR_STANCE"),
    # --- Beastmastery -------------------------------------------------------------------------------
    "mount.relay": (
        "No action, at the start of a turn you begin mounted: transfer onto another willing mount of your "
        "own within 15 feet that nobody is riding, paying the mounting movement cost.",
        "TAL_BEASTMASTERY_BEASTBACK_RELAY"),
    "mount.dash": ("Your Action: your mount takes the Dash action.", "TAL_BEASTMASTERY_MOUNTED_MANEUVERS"),
    "mount.disengage": ("Your Action: your mount takes the Disengage action.", "TAL_BEASTMASTERY_MOUNTED_MANEUVERS"),
    "mount.dodge": ("Your Action: your mount takes the Dodge action.", "TAL_BEASTMASTERY_MOUNTED_MANEUVERS"),
    "mount.skirmish": ("Bonus Action: your mount takes the Disengage action.",
                       "TAL_BEASTMASTERY_SKIRMISH_RIDER"),
    "mount.run_down": (
        "Your Action: your mount attempts Overrun against a creature within 10 feet -- a Strength "
        "(Athletics) contest, with Advantage if the mount is larger and Disadvantage if it is smaller. On a "
        "win the pair moves through the target's space.",
        "TAL_BEASTMASTERY_RUN_DOWN"),
    "mount.run_down_bonus": (
        "Bonus Action: your mount attempts Overrun with the same Strength (Athletics) contest as the Action "
        "version.",
        "TAL_BEASTMASTERY_RUN_DOWN"),
    "mount.shove_push": (
        "Your Action: your mount Shoves one creature within 10 feet. The target makes a Strength or "
        "Dexterity save against 8 + your Proficiency Bonus + the mount's Strength modifier; on a failure it "
        "is pushed 5 feet away.",
        "TAL_BEASTMASTERY_MOUNTED_MANEUVERS"),
    "mount.shove_prone": (
        "Your Action: your mount Shoves one creature within 10 feet. The target makes a Strength or "
        "Dexterity save against 8 + your Proficiency Bonus + the mount's Strength modifier; on a failure it "
        "is knocked Prone.",
        "TAL_BEASTMASTERY_MOUNTED_MANEUVERS"),
    "mount.charge_overrun": (
        "Part of Great Beast Charge, after your mount wins the Overrun contest: the pair moves through the "
        "target's space, and the charge ends with one melee attack.",
        "TAL_BEASTMASTERY_GREAT_BEAST_CHARGE"),
    "mount.rhythm2_move": (
        "The other participant's Reaction, once per turn after one of the pair hits: it moves up to 10 feet.",
        "TAL_BEASTMASTERY_ONE_RIDER_ONE_BEAST"),
    "mount.rhythm2_push": (
        "The other participant's Reaction, once per turn after one of the pair hits: it Shoves the target 5 "
        "feet away.",
        "TAL_BEASTMASTERY_ONE_RIDER_ONE_BEAST"),
    "mount.rhythm2_prone": (
        "The other participant's Reaction, once per turn after one of the pair hits: it Shoves the target "
        "Prone.",
        "TAL_BEASTMASTERY_ONE_RIDER_ONE_BEAST"),
    "mount.rhythm_focus": (
        "Free, once per round, when your mount takes Dash, Disengage or Dodge while you ride it: regain 1 "
        "Martial Focus.",
        "TAL_BEASTMASTERY_SHARED_SADDLE_RHYTHM"),
    "mount.rhythm_move": (
        "Free, once per round, when your mount takes Dash, Disengage or Dodge while you ride it: move 5 feet "
        "without provoking Opportunity Attacks.",
        "TAL_BEASTMASTERY_SHARED_SADDLE_RHYTHM"),
    "mount.rhythm_temp": (
        "Free, once per round, when your mount takes Dash, Disengage or Dodge while you ride it: the mount "
        "gains Temporary Hit Points equal to your Proficiency Bonus.",
        "TAL_BEASTMASTERY_SHARED_SADDLE_RHYTHM"),
    "mount.trample_push": (
        "Free, once per turn after your mount wins Overrun: push the target 10 feet.",
        "TAL_BEASTMASTERY_TRAMPLING_LINE"),
    "mount.trample_prone": (
        "Free, once per turn after your mount wins Overrun: knock the target Prone.",
        "TAL_BEASTMASTERY_TRAMPLING_LINE"),
    "mount.trample_damage": (
        "Free, once per turn after your mount wins Overrun: deal Bludgeoning damage equal to your "
        "Proficiency Bonus.",
        "TAL_BEASTMASTERY_TRAMPLING_LINE"),
    "mount.trample_move": (
        "Free, once per turn after your mount wins Overrun: your mount may move 10 additional feet.",
        "TAL_BEASTMASTERY_TRAMPLING_LINE"),
    # --- Barrage ------------------------------------------------------------------------------------
    "court_select_ally": (
        "Free: choose one ally to receive your Court of Falling Stars advantage -- its first eligible attack "
        "against a creature your Barrage hit twice has Advantage. You may choose up to your Proficiency "
        "Bonus allies.",
        "TAL_BARRAGE_COURT_OF_FALLING_STARS"),
    # --- Qi Cultivation -----------------------------------------------------------------------------
    "qi_path.armament.assault": (
        "Free, once per turn: switch your manifested Domain Armament to Assault Mode so it can make its "
        "Cultivation Attack on your turn.",
        "tianxia.path.qi_cultivation.feature.domain_armament"),
    "qi_path.armament.guard": (
        "Free, once per turn: switch your manifested Domain Armament to Guard Mode. At the end of your turn "
        "it protects one creature within 5 feet, giving that creature +2 AC against ranged attack rolls until "
        "the start of your next turn.",
        "tianxia.path.qi_cultivation.feature.domain_armament"),
}


# Keys whose lead deliberately speaks over another hook's words for the same row.
#
# ``unarmed.grapple.tackle`` is a cloned Unarmed Strike Grapple (combat/ext/wrestling_tackle.py): the
# generic Unarmed Strike helper (combat/ext/action_help.py) still answers it, but that text says "Action:
# use Grapple in place of one unarmed attack", which is wrong for Tackle -- a Bonus Action after a Dash
# Action, with the replaced attack taken out. The seam's own sentence is the one that fits the button.
SUPERSEDES: frozenset[str] = frozenset({"unarmed.grapple.tackle"})


def _key(row: dict[str, Any]) -> str:
    """The button's compiled name: "action:typed.<character-id>.<name>" -> "<name>"."""
    source = str(row.get("source_definition_id") or "")
    if not source.startswith("action:typed."):
        return ""
    return source.split(".", 2)[-1].split("#", 1)[0].split("+", 1)[0]


def _described_elsewhere(row: dict[str, Any]) -> bool:
    """Whether another plug-in's button_description already has words for this button.

    combat/action_text.py reads the hook results first-non-empty, in module order; this module's name
    sorts first, so an unconditional answer here would shadow that plug-in's own, more specific sentence
    and also drop the card's printed-record digest (combat/action_text.action_digest). Every hook is a
    pure presentation callback, so calling them once more here is read-only.
    """
    for function in subscribers("button_description"):
        if function is card_text:
            continue
        text = invoke("button_description", function, row)
        if isinstance(text, str) and text.strip():
            return True
    return False


@hook("button_description")
def card_text(row: dict[str, Any]) -> str | None:
    """The table's words for this button, or None when the button is not ours or another hook has words."""
    key = _key(row)
    entry = CARDS.get(key)
    if entry is None:
        return None
    if key not in SUPERSEDES and _described_elsewhere(row):
        return None
    lead, record = entry
    body = lead
    if record:
        from ..rule_help import printed_rule_text

        printed = printed_rule_text(record)
        if printed:
            body = f"{lead}\n\n{printed}"
    return body
