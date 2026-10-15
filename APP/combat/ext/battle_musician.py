"""Battle Musician (Tianxia Music Insight).

The printed combat clauses of this Insight, all owned by this plug-in:

* "Use Constitution as your Music key ability for Cadence talents."
  ``compile_action`` re-keys every printed Cadence-tagged Music talent
  (Battle Cadence, Echoing Step, March of the Immortal Host, Rhythmic
  Guard, Unbroken Rhythm, War Song, Weapon Hymn): the talent's compiled
  numbers read their key-ability modifier, technique save DC and the
  runtime "key_ability_modifier" formula from Constitution instead of the
  character's Music key ability. The swap is the printed rule itself, so it
  is unconditional -- no question is asked and no variant is offered.

* "You may spend Stamina instead of Cultivation Points for Battle Cadence,
  Rhythmic Guard, Echoing Step, March of the Immortal Host, and any other
  Music talent whose printed activation can be performed entirely through
  voice, breath, heartbeat, footwork, weapon impact, body percussion, or
  movement and does not require a separate instrument, fixed installation,
  or external performer."  The four named talents already print a Stamina
  alternative (Battle Cadence costs nothing), so the gap is the other
  embodied talents: ``payment_substitution`` offers to cover their printed
  CP cost with the same amount of Stamina, the same voluntary seam Iron
  Sword Body uses for its Stamina-for-CP quote. Talents tagged Instrument
  (a bell, a separate instrument), Soul-Sound (not a bodily medium),
  Domain, Ritual, or Echo Performer (an external performer) keep their
  printed costs.

* "When you take the Attack action while Keeping the Measure, you may use
  Opening Phrase once during that turn without spending its Bonus Action.
  You still pay every resource and cannot use Opening Phrase more times
  than its own rule permits."  ``compile_actions`` publishes one free
  (economy NONE) variant of each of Opening Phrase's four printed options.
  ``candidate_allowed`` offers them only while the fighter Keeps the
  Measure, has taken the Attack action this turn while Keeping the Measure
  (``action_completed`` records that, gated on the Measure at the moment
  the attack resolves), and has not spent this turn's free use. The
  variants carry Opening Phrase's own typed source, so the printed
  once-per-round-per-recipient rule and the "only while you Keep the
  Measure" rule keep applying through the existing gates, and the options
  cost nothing (Opening Phrase prints "Cost: None"), so every resource the
  rule says is still paid is paid.

Already automated by the engine, recorded here so the row is accounted
for: "Source CL: Music Source CL, using Body Refining CL for talents used
as Embodied Cadence" -- the Factory character model carries one Cultivation
Level, which is the Source CL of every sphere it learned, and the compiler
already reads it for Music talents; and "A qualifying embodied performance
may be maintained through those bodily media" -- Keep the Measure is
method-agnostic (combat/ext/music.py starts it from any legal method and
ends it only on its printed enders), so a performance kept through voice,
breath, heartbeat, footwork, weapon impact, body percussion or movement is
already maintainable, and a talent that expressly requires an instrument
or installation still requires it.

A character without the Insight owns none of its rows, so every hook
returns early and every other musician's key ability, costs, Opening
Phrase economy and Measure behave exactly as before.
"""
from __future__ import annotations

from typing import Any

from . import hook, note
from .passive_rows import row_of

INSIGHT = "insight.battle-musician"
BLOCK = "battle_musician"
MUSIC_SPHERE = "tianxia.sphere.music"
OPENING_PHRASE = "MUSIC_BASE_OPENING_PHRASE"
STAMINA = "resource:core.stamina"
# "Cultivation Points" is the character's current Path pool (Core
# Rules Reference: "CP means the character's current Path resource"),
# so a printed CP cost compiles to the pool the character pays it
# from -- Qi, Stamina or Resonance.
PATH_POOLS = ("resource:core.qi", "resource:core.stamina", "resource:core.resonance")

# The printed Cadence-tagged Music talents ("Use Constitution as your Music
# key ability for Cadence talents"): the tag is printed in each talent's
# header line, which the typed authority does not carry, so the plug-in
# records the set itself.
CADENCE_TALENTS = frozenset({
    "tianxia.talent.music.battle_cadence",
    "tianxia.talent.music.echoing_step",
    "tianxia.talent.music.march_of_the_immortal_host",
    "tianxia.talent.music.rhythmic_guard",
    "tianxia.talent.music.unbroken_rhythm",
    "tianxia.talent.music.war_song",
    "tianxia.talent.music.weapon_hymn",
})

# The other embodied Music talents: their printed activation is performed
# entirely through voice, breath, song, chant, hymn, lullaby, chorus,
# melody, harmony, rhythm or measure, with no separate instrument, fixed
# installation or external performer. The four talents the Insight names
# already print a Stamina alternative (Battle Cadence costs nothing), and
# bell talents (a bell is an instrument), Soul-Sound talents (not a bodily
# medium), Domains, the Ritual, and the Echo Performer talents (an external
# performer) are outside the printed media, so they keep their printed
# costs. Rallying Song and War Song print "CP or expend Martial Focus";
# the Insight adds the Stamina way to pay them.
EMBODIED_TALENTS = frozenset({
    "tianxia.talent.music.captivating_melody",
    "tianxia.talent.music.concerto_of_broken_breath",
    "tianxia.talent.music.disruptive_harmony",
    "tianxia.talent.music.dissonant_note",
    "tianxia.talent.music.harmonizing_breath",
    "tianxia.talent.music.healing_hymn",
    "tianxia.talent.music.lullaby_of_settled_breath",
    "tianxia.talent.music.mocking_rhythm",
    "tianxia.talent.music.rallying_song",
    "tianxia.talent.music.shared_measure",
    "tianxia.talent.music.shattering_chorus",
    "tianxia.talent.music.silence_breaking_note",
    "tianxia.talent.music.song_carried_across_mountains",
    "tianxia.talent.music.war_song",
})

# Turn-scoped receipts (cleared at the owner's next turn start by the
# engine's turn reset, which keeps only "_round_" and "once_per_round:" keys).
ATTACK_TAKEN = "battle_musician_attack_taken"
FREE_OPENING_USED = "battle_musician_free_opening_used"


# Keeping the Measure is the public music_measure condition (combat/ext/music.py).
MEASURE_CONDITION = "condition:typed.music_measure"


def _keeping_measure(actor: Any) -> bool:
    return any(condition.condition_id == MEASURE_CONDITION for condition in actor.conditions.values())


def owned(engine: Any, actor: Any) -> bool:
    return row_of(engine, actor.entity_id, BLOCK, BLOCK) is not None


@hook("compile_block")
def compile_battle_musician(block: str, spec: dict[str, Any], row: dict[str, Any],
                            numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block != BLOCK:
        return None
    return [{**row, "block": BLOCK, "kind": spec.get("kind"), "numbers": dict(numbers)}]


# ------------------------------------------------------------------ cadence key ability
def _rekey(numbers: dict[str, Any]) -> dict[str, Any] | None:
    """Constitution keys this talent: swap the key-ability modifier, and the
    technique save DC (8 + PB + the key ability modifier) with it. None when
    the two modifiers already agree, so an already-Constitution-keyed talent
    keeps its own numbers."""
    key_mod = int(numbers.get("key_mod") or 0)
    con_mod = int(numbers.get("con_mod") or 0)
    if con_mod == key_mod:
        return None
    numbers = dict(numbers)
    numbers["key_mod"] = con_mod
    if "save_dc" in numbers:
        numbers["save_dc"] = int(numbers.get("save_dc") or 0) - key_mod + con_mod
    return numbers


@hook("compile_action")
def cadence_key(action: Any, info: dict[str, Any]) -> Any:
    """Constitution is the Music key ability for Cadence talents."""
    if INSIGHT not in info.get("owned_ids", ()):
        return None
    typed = (action.parameters or {}).get("typed") or {}
    if typed.get("source") not in CADENCE_TALENTS:
        return None
    numbers = _rekey(dict(typed.get("numbers") or {}))
    if numbers is None:
        return None
    return action.model_copy(update={
        "parameters": {**action.parameters, "typed": {**typed, "numbers": numbers}}})


@hook("compile_reaction")
def cadence_reaction_key(row: dict[str, Any], info: dict[str, Any]) -> dict[str, Any] | None:
    """A Cadence Reaction reads Constitution too (Rhythmic Guard). The row gets
    its own numbers copy, so the swap never reaches the character's other
    talents, which keep the character's shared numbers."""
    if INSIGHT not in info.get("owned_ids", ()):
        return None
    if str(row.get("feature_id") or "") not in CADENCE_TALENTS:
        return None
    numbers = _rekey(dict(row.get("numbers") or {}))
    if numbers is None:
        return None
    return {**row, "numbers": numbers}


# ------------------------------------------------------------------ the embodied Stamina payment
@hook("payment_substitution")
def embodied_stamina(engine: Any, actor: Any, source: str, costs: Any, missing: Any) -> Any:
    """Spend Stamina instead of CP for a Music talent performed through the body."""
    if not owned(engine, actor):
        return None
    action = engine.action_catalog.get(source)
    if action is None or action.owner_id != actor.entity_id:
        return None
    typed = (action.parameters or {}).get("typed") or {}
    if typed.get("source") not in EMBODIED_TALENTS:
        return None
    from ..alternative_payments import PaymentAlternative

    stamina = int(actor.resources.get(STAMINA) or 0)
    covered = {}
    for resource, amount in (costs or {}).items():
        # A CP cost is the character's Path pool; a Stamina pool is
        # already Stamina, so only another pool can be swapped for it.
        if resource in PATH_POOLS and resource != STAMINA and int(amount) > 0 and stamina >= int(amount):
            covered[resource] = int(amount)
    if not covered or any(resource not in covered for resource in (missing or ())):
        return None
    # The passive row this plug-in compiles carries the Insight's own
    # record id as its feature_id, which is what the payment flow's
    # ownership query reads.
    return PaymentAlternative(INSIGHT, "Battle Musician: spend Stamina instead of CP",
                              tuple(covered.items()),
                              costs=((STAMINA, sum(covered.values())),))


# ------------------------------------------------------------------ the free Opening Phrase
@hook("compile_actions")
def free_opening_phrase(info: dict[str, Any]) -> list[Any] | None:
    """One free Opening Phrase option for each of its four printed options."""
    if INSIGHT not in info.get("owned_ids", ()) or OPENING_PHRASE not in info.get("owned_ids", ()):
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    out = []
    for action in info.get("actions") or ():
        typed = (action.parameters or {}).get("typed") or {}
        if typed.get("source") != OPENING_PHRASE:
            continue
        out.append(ActionDefinition(
            source_definition_id=f"{action.source_definition_id}#battle_musician_free",
            display_name=(f"{action.display_name} (free with the Attack action, Battle Musician)"),
            owner_id=action.owner_id,
            economy=EconomyKind.NONE,
            resolution_kind=action.resolution_kind,
            target_kind=action.target_kind,
            range_ft=action.range_ft,
            costs=(),
            parameters={**action.parameters,
                        "typed": {**typed, "battle_musician_free": True},
                        "expected_damage": 0,
                        "description": ("Opening Phrase once this turn without spending its "
                                        "Bonus Action, after taking the Attack action while "
                                        "Keeping the Measure (Battle Musician).")}))
    return out or None


@hook("candidate_allowed")
def free_opening_gate(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """The free Opening Phrase needs the Measure, this turn's Attack action, and its own free use."""
    typed = (getattr(action, "parameters", None) or {}).get("typed") or {}
    if not typed.get("battle_musician_free"):
        return None

    if not owned(engine, actor) or not _keeping_measure(actor):
        return False
    if not actor.turn_flags.get(ATTACK_TAKEN) or actor.turn_flags.get(FREE_OPENING_USED):
        return False
    return True


@hook("action_completed")
def record_attack_and_use(engine: Any, actor: Any, economy: Any, source_definition_id: str) -> None:
    """Record the Attack action taken while Keeping the Measure, and this turn's free use."""
    action = engine.action_catalog.get(source_definition_id)
    if action is None or action.owner_id != actor.entity_id:
        return
    if source_definition_id.endswith("#battle_musician_free"):
        if owned(engine, actor):
            actor.turn_flags[FREE_OPENING_USED] = True
        return
    if economy != "ACTION" or not _is_attack_action(action):
        return
    # The printed trigger is taking the Attack action *while Keeping the Measure*.
    if owned(engine, actor) and _keeping_measure(actor):
        actor.turn_flags[ATTACK_TAKEN] = True
        note(engine, INSIGHT, actor,
             f"{actor.display_name} took the Attack action while Keeping the Measure, "
             "so Opening Phrase is free once this turn (Battle Musician).", (actor,))


def _is_attack_action(action: Any) -> bool:
    """Use compiled Attack-action identity, including Shove/Grapple without rolls.

    Weapon/improvised action IDs are the compiler's basic weapon identities;
    typed.attack_action marks natural and unarmed options and their variants.
    A technique's nested attack roll does not establish either identity.
    """
    import re

    typed = (action.parameters or {}).get("typed") or {}
    if typed.get("reaction_attack") or typed.get("opportunity_of") or typed.get("granted_attack"):
        return False
    return bool(typed.get("attack_action")) or bool(re.search(r"\.(?:weapon|improvised)\.", action.source_definition_id))
