"""Hunger's Digestive Mantle: every printed line of the Sphere a fight can see, automated (rider lane 9, 2026-09-29;
owner: "i want everything we can automated"; AUTO14, round 24).  Sphere Compendium, Hunger (owner's text:
authority/typed_mechanics/rules_text.json).

Most of Hunger happens *before* a fight (refining meals, Satiety kinds, Impurity), so what a table sees is Digestive Mantle
and the talents that change it.  The typed options give the Temporary HP; sealed second-pass rows apply standing parts; the
triggered parts never ran (gu.json's note on HUNGER_BASE_DIGESTIVE_MANTLE).  This module owns the Mantle itself: it keeps
the chosen benefit(s) on a condition ("condition:typed.digestive_mantle", read from the Mantle action's name, e.g.
"Digestive Mantle: Thick Hide") and runs them:

  Beast Strength   once before the Mantle ends, a melee attack or unarmed strike that hits adds PB damage.
  Predator Step    once, a hit on a creature you moved at least 10 feet straight toward this turn adds PB damage.
  Iron Stomach     a successful save against Poisoned (or disease) gives PB Temporary HP.
  Thick Hide       once per round, Bludgeoning, Piercing or Slashing damage drops by PB + key modifier (three times PB with
                   Nine-Beast Sovereign Course's Armored Hunger, twice PB with Beast-Bone Broth's Bone Satiety).
  Venom Belly /    once per turn, a hit deals PB + key modifier extra Poison / Fire damage; with Venom Sovereign the first such hit
  Furnace Belly    each turn also forces a Constitution save or Poisoned until the start of your next turn.
  Predator King    once before the Mantle ends, a hit on a Bloodied creature adds one roll of your damage die (Predator-King
                   Digestion).  Its Climb or Swim Speed equal to your Speed is your walking Speed on a table with no climbing
                   or swimming (the same reading combat/ext/painting_forms.py records for the Crane and the Serpent).
Talents: Bitter Medicine Belly (1 CP: PB Temporary HP on a successful save against Poisoned while the Mantle lasts), Marrow-Furnace
Pulse (once per turn, spending CP on a Hunger talent while the Mantle lasts gives PB Temporary HP; from a demon beast it
instead adds PB to one damage roll that turn and 1 Impurity when the Mantle ends), Three-Course Battle Body (the new Satiety
replaces the Mantle's benefit and gives PB Temporary HP, a number of times equal to your Proficiency Bonus per long rest),
The Empty Bowl Watches (Taste the Qi on a Bloodied or Poisoned creature while the Mantle lasts gives PB Temporary HP, once a
round, and Taste the Qi costs no Bonus Action once on each of your turns), Empty-Bowl Guard (out of food: the Mantle's
Temporary HP rises by PB, once per long rest).

**The kind of Satiety a Mantle burns.**  Several printed Hunger lines read the meal a Mantle was made from -- "using
Demon-Beast Satiety", "from Bone Satiety", "using Dragon-Marrow Satiety", "if none of the spent Satiety was Corrupted,
Demon-Beast, or Forbidden".  Refining that meal happens away from the table, so the table records the choice: when an actor who
owns a Hunger line that reads the meal activates the Mantle, this module asks which kind of Satiety is being spent (an AI
picks) and writes it on the Mantle's condition data as ``satiety``.  The six printed kinds are the whole menu, in the words
the player reads: "a normal meal", "a Corrupted Portion meal", "Demon-Beast Satiety (a demon beast's corrupted portion)",
"Bone Satiety (a spirit beast or monster portion with bone, shell, horn, claw, scale, carapace or hide)", "Dragon-Marrow
Satiety (a dragon, serpent, flood-beast, sky-beast or imperial guardian beast)", "Forbidden Satiety (a meal refined from a
cultivator by a Forbidden Hunger talent)".  A character whose own printed lines read no meal is never asked and records
nothing.

**Where the creature came from is a separate question.**  Predator-King Digestion reads "Satiety from a predator or apex
beast", which is a fact about the creature, not one of the six kinds: a predator's demon-beast portion is a demon-beast meal
*and* a predator meal, and a predator's bone portion is a bone meal *and* a predator meal.  So a row declares what it reads
(``reads`` for a kind, ``reads_provenance`` for where the creature came from) and each answer is recorded in its own place
(``satiety`` and ``provenance``), never one in place of the other.  Only an actor who owns a row that reads one is asked.

**Tables saved before that question existed.**  A fight sealed while the predator line was still read as a kind of meal holds a
row that declares ``reads: ["predator"]`` and an active Mantle that recorded ``satiety: "predator"``, and resuming a match
loads that sealed bundle unchanged, so a rules edit cannot reach it.  Such a table keeps both halves of the reading it was
saved with: ``predator`` stays on the meal menu for an actor who owns that kind of row, so every later activation can record
it again, and that recorded predator meal still opens the Predator-King damage die.  Nothing recompiles or rewrites the
saved fight to get there.

**Two benefits at once.**  "Choose two basic Mantle benefits instead of one" is printed four times (the base ability's
Demon-Beast Course, Demon-Beast Digestion, Maw of Ten Thousand Courses, Hundred-Flavour Mantle).  This module owns that one
rule too: when the actor's own Hunger lines allow more than one benefit, the extra benefit is asked at the Mantle's activation
and stored beside the first in the same condition data, so every triggered line above reads a list and applies for each
benefit it belongs to.  Only one of them may add damage or grant Resistance, which the ask refuses to break.  What a benefit
costs is a separate fact from how many there may be: the Satiety the Mantle already costs pays for the first benefit, and a
printed "choose two" (the base ability's Demon-Beast Course, Demon-Beast Digestion) adds another for free.  Only a talent
that prints a price per benefit (Maw of Ten Thousand Courses, ``satiety_per_benefit``) is charged for the benefits past that
free entitlement, and never for one the actor has no Satiety left to pay for.

**Ending a Mantle.**  "When that Mantle ends" is owed on both endings: the minute running out (``effect_expiring``) *and*
"Activating a new Digestive Mantle ends the previous one" (``replace_mantle``, which runs on technique_start, before the
new Mantle's own effects are applied).  ``_mantle_ends`` guards on its own ``ended`` flag so each Mantle pays once.

The Mantle is also registered as the named state ``digestive_mantle`` (the shared helper combat/ext/states.py) so
combat/ext/free_uses.py can offer a printed "without spending a Bonus Action" copy of another Hunger ability while it lasts
(The Empty Bowl Watches), and its condition data carries the recorded ``fly_speed_ft`` for Nine-Beast Sovereign Course's
Winged Hunger: combat/flight.py reads those keys out of any condition's data. New sealed policy rows install a sentinel
that ends flight at the end of the next turn while the Mantle continues; legacy bundles retain their own expiry.  Elemental Gut's one damage type is chosen here too (the typed option row cannot hold a chosen type) and is
recorded as ``element``.

Judgment calls: the extra damage lands as its own packet of the hit's type (Venom Belly's is Poison; Acid is the GM's pick);
"straight toward" is currently read as the move bringing you at least 10 feet nearer the creature; "a number of times equal to your
Proficiency Bonus per long rest" is per fight, counted from the actor's own recorded activations, because no long rest passes
inside a fight (the reading combat/ext/lane4_saves.py records); the AI takes every optional benefit.
"""

from __future__ import annotations

from ..paid_relocation import activation

from typing import Any

from . import effect, hook, note
from .needle import CHOICE, ask, checkpoint_id
from .retained_updates import record_instance_update
from .effect_durations import token as turn_token

BLOCK = "lane9_hunger"
MANTLE_ID = "HUNGER_BASE_DIGESTIVE_MANTLE"
H = "tianxia.talent.hunger."
MANTLE = "condition:typed.digestive_mantle"
MANTLE_STATE = "digestive_mantle"
BENEFITS = ("Beast Strength", "Predator Step", "Iron Stomach", "Thick Hide", "Venom Belly", "Furnace Belly", "Elemental Gut", "Deep Nourishment")
ADAPTATIONS = ("Winged Hunger", "Burrowing Hunger", "Armored Hunger", "Venom Sovereign")
# Kinds the printed Hunger lines name for the meal a Mantle burns, in the words the player reads. A plain meal comes first so
# an AI with no preference spends the ordinary one. These are the only kinds: a printed line that asks where the creature came
# from ("a predator or apex beast") asks about the creature, not the kind, and is recorded separately as provenance.
SATIETY_KINDS = ("normal", "corrupted", "demon_beast", "bone", "dragon_marrow", "forbidden")
SATIETY_LABELS = {
    "normal": "a normal meal",
    "corrupted": "a Corrupted Portion meal",
    "demon_beast": "Demon-Beast Satiety, refined from a demon beast's corrupted portion",
    "bone": "Bone Satiety, refined from a spirit beast or monster portion with bone, shell, horn, claw, scale, carapace or hide",
    "dragon_marrow": "Dragon-Marrow Satiety, refined from a dragon, serpent, flood-beast, sky-beast or imperial guardian beast",
    "demon_king": "Demon-King Satiety, refined from a Mighty Corrupted Portion of a demon beast",
    "forbidden": "Forbidden Satiety, refined from a cultivator by a Forbidden Hunger talent",
}
# Where the creature this meal was refined from came from, in the words the printed line uses. A row that reads one declares
# it in ``reads_provenance``; the answer is recorded beside the meal kind as ``provenance``, so one meal can satisfy both.
PROVENANCE_LABELS = {
    "predator_or_apex": "Satiety refined from a predator or an apex beast",
}
# The option that says "none of the ones above", so an ordinary meal is an answer rather than a refusal.
PROVENANCE_OTHER = "some_other_creature"
# The meal kind a table used to record for the predator line itself, before that line became a question about the creature.
# Only a fight sealed against that older rules data still declares ``reads: ["predator"]`` and stores this on its Mantle; for
# such a row ``predator`` stays a meal kind it reads, so its Mantle keeps the printed die and its next activation can record
# the meal again. A row compiled today declares ``reads_provenance`` instead and never sees this.
LEGACY_PREDATOR = "predator"
LEGACY_SATIETY_LABELS = {
    LEGACY_PREDATOR: "Satiety refined from a predator or an apex beast",
}
SATIETY_POOL = "resource:named.satiety"
# The printed kinds the Demon-Beast Course and Maw rules call impure: Corrupted, Demon-Beast or Forbidden Satiety.
UNPURE = ("corrupted", "demon_beast", "forbidden")
# Benefits that add damage or grant Resistance: the printed menus allow only one of the chosen benefits to do either.
ADDS_DAMAGE = ("Beast Strength", "Predator Step", "Venom Belly", "Furnace Belly")
GRANTS_RESISTANCE = ("Elemental Gut",)


@hook("compile_block")
def compile_rows(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block != BLOCK:
        return None
    return [{**row, "block": BLOCK, "kind": spec.get("kind"), "pb": int(numbers.get("pb") or 2), "key_mod": int(numbers.get("key_mod") or 0),
             "keeps_compiling": bool(spec.get("keeps_compiling")),
             **({"second_pass": 1} if spec.get("second_pass") == 1 else {}),
             **({"runtime": 1, "choice_owner": True} if spec.get("runtime") == 1 else {}),
             **({"benefits": int(spec["benefits"]), "required_benefits": bool(spec.get("required_benefits", True)),
                 "satiety_per_benefit": bool(spec.get("satiety_per_benefit")),
                 "benefits_for": [str(value) for value in spec.get("benefits_for") or ()]} if spec.get("benefits") else {}),
             **({"reads": [str(value) for value in spec.get("reads") or ()]} if spec.get("reads") else {}),
             **({"reads_provenance": [str(value) for value in spec.get("reads_provenance") or ()]} if spec.get("reads_provenance") else {})}]


def row_of(engine: Any, actor: Any, kind: str) -> dict[str, Any] | None:
    """The actor's own Hunger row of this kind, or None: the public shape combat/ext/passive_rows.py documents."""
    from .passive_rows import row_of as _row_of

    return _row_of(engine, actor.entity_id, BLOCK, kind)


def _block_rows(engine: Any, actor: Any) -> list[dict[str, Any]]:
    """Every Hunger row this actor's own compiled bundle gave it (nothing for a character with no Hunger talent)."""
    return [row for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, [])
            if row.get("block") == BLOCK]


def uses(engine: Any, actor: Any, feature_id: str) -> int:
    """How many times this actor has used ``feature_id`` in this fight, read from its own recorded activations.

    "A number of times equal to your Proficiency Bonus per long rest" is per fight: no long rest passes inside one, and a
    saved fight replays the same count (the reading combat/ext/lane4_saves.py records for a Proficiency-Bonus allowance).
    """
    return sum(1 for event in engine.events if event.event_type == "PASSIVE_TRIGGERED" and event.actor_id == actor.entity_id
               and str((event.payload or {}).get("feature_id") or "") == feature_id)


def record_use(engine: Any, actor: Any, feature_id: str, label: str) -> None:
    engine._append_event("PASSIVE_TRIGGERED", feature_id, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                         payload={"feature_id": feature_id, "label": label})


def mantle(actor: Any) -> Any:
    return next((c for c in actor.conditions.values() if c.condition_id == MANTLE), None)


def _has(actor: Any, benefit: str) -> Any:
    held = mantle(actor)
    return held if held is not None and benefit in ((held.data or {}).get("benefits") or []) else None


def state_id() -> str:
    """The shared named-state condition id (combat/ext/states.py) the Mantle also carries, so a printed "while Digestive
    Mantle is active" line can offer its own free copy of another Hunger ability (combat/ext/free_uses.py)."""
    from . import states

    return states.PREFIX + MANTLE_STATE


def _feature(ctx: Any) -> str:
    return str(ctx.typed.get("source") or "")


def _cp(actor: Any) -> str | None:
    from .d20_rewrite import pool_id

    return pool_id(actor, "cp")


def _reads(engine: Any, actor: Any, field: str = "reads") -> list[str]:
    """The Satiety kinds (``reads``) or provenances (``reads_provenance``) this actor owns a Hunger line that reads.

    One list per question, so a printed line that names a kind of meal and a printed line that names the creature it came
    from are both answered, and neither answer stands in for the other."""
    found: list[str] = []
    for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, []):
        for value in (row.get(field) or ()) if row.get("block") == BLOCK else ():
            if str(value) not in found:
                found.append(str(value))
    return found


def _bonus_benefits(engine: Any, actor: Any, kind: str) -> tuple[int, bool, str | None, int, str]:
    """"Choose two (or up to three) basic Mantle benefits instead of one": how many, whether all of them are required, the
    feature whose printed line pays a Satiety for each one beyond the first, how many of them that price does not reach, and
    that feature's own name (the fight log must never print an ability id).
    A talent's count applies only to the kinds of Satiety its own printed line names (``benefits_for``); Maw of Ten
    Thousand Courses counts any meal, Demon-Beast Digestion only a demon-beast one.  Only a talent that prints a cost
    sets ``satiety_per_benefit``: the base ability's own Demon-Beast Course and Demon-Beast Digestion both hand over a
    second benefit for the one Satiety the Mantle already costs, so they raise ``free`` and never set ``payer``."""
    count, required, payer, free, payer_name = 1, True, None, 1, ""
    for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, []):
        if row.get("block") != BLOCK or not row.get("benefits"):
            continue
        only = row.get("benefits_for") or ()
        if only and kind not in only:
            continue
        offered = int(row.get("benefits") or 1)
        if not row.get("satiety_per_benefit"):
            # Its printed line hands its benefits over for the Satiety the Mantle already costs. Read on its own, so a
            # priced talent below it cannot hide this one's free entitlement.
            free = max(free, offered)
        if offered < count:
            continue
        count = max(count, offered)
        required = required and bool(row.get("required_benefits", True))
        if row.get("satiety_per_benefit"):
            payer = str(row.get("feature_id") or MANTLE_ID)
            payer_name = str(row.get("name") or "")
    return count, required, payer, min(free, count), payer_name


def _owning_names(engine: Any, actor: Any, field: str, wanted: list[str]) -> str:
    """The printed names of this actor's own Hunger lines that read ``field``, for a prompt that has to say who is asking."""
    return ", ".join(sorted({str(row.get("name") or "a Hunger talent") for row in
                              (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, [])
                              if row.get("block") == BLOCK and wanted and any(value in (row.get(field) or ()) for value in wanted)}))


def _satiety_menu(wanted: list[str]) -> tuple[list[str], dict[str, str]]:
    """The six printed meal kinds, plus any talent-only kind an owned row reads (so a character who owns no such talent is
    never offered a kind no printed line of its own names).

    A row sealed against the older rules data reads the predator meal as a kind of its own, so ``predator`` joins the menu
    for its owner in that saved fight and in every later activation of it. A row compiled today reads provenance instead and
    is not on this path, so no other character is ever offered the kind."""
    extra = [kind for kind in wanted if kind in (SATIETY_LABELS.keys() | LEGACY_SATIETY_LABELS.keys()) and kind not in SATIETY_KINDS]
    return [*SATIETY_KINDS, *extra], {**SATIETY_LABELS, **{kind: SATIETY_LABELS.get(kind) or LEGACY_SATIETY_LABELS[kind] for kind in extra}}


def _satiety(ctx: Any) -> str | None:
    """Ask which kind of Satiety this Mantle burns; None when no owned Hunger line reads it (nothing is asked or recorded)."""
    engine, actor = ctx.engine, ctx.actor
    # This printed option declares its meal even without a provenance-reading talent.
    # Preserve old sealed rows; new policy rows owe its two benefits and end debt.
    if row_of(engine, actor, "mantle_policy") and "Demon-Beast Course" in str(ctx.action.display_name):
        return "demon_beast"
    wanted = _reads(engine, actor, "reads")
    if not wanted:
        return None
    names = _owning_names(engine, actor, "reads", wanted)
    options, labels = _satiety_menu(wanted)
    picked = ask(engine, getattr(ctx, "intent", None), checkpoint_id(engine, "HUNGER_SATIETY", actor.entity_id), actor,
                 CHOICE + "hunger_satiety", options, labels=labels,
                 name="Digestive Mantle: which meal?", feature_id="Digestive Mantle", preferred=["normal"],
                 target_id=actor.entity_id,
                 prompt=f"Digestive Mantle spends one Satiety. {names} reads the kind of Satiety you burn, so the table "
                        f"records which meal it is. Choose the meal this Satiety came from.")
    return picked[0] if picked else None


def _provenance(ctx: Any) -> str:
    """Where the creature this Mantle's meal came from, recorded apart from the kind of meal; "" when no owned Hunger line
    reads it (nothing is asked or recorded).

    "When you activate Digestive Mantle using Satiety from a predator or apex beast" (Predator-King Digestion) is about the
    creature, so its answer is its own question and its own place on the Mantle: a predator's demon-beast portion answers
    both this and the meal question, and neither answer replaces the other.  Unanswered and declined alike mean "some other
    creature", the ordinary reading; nothing is invented to open an optional benefit."""
    engine, actor = ctx.engine, ctx.actor
    wanted = [value for value in _reads(engine, actor, "reads_provenance") if value in PROVENANCE_LABELS]
    if not wanted:
        return ""
    names = _owning_names(engine, actor, "reads_provenance", wanted)
    options = [*wanted, PROVENANCE_OTHER]
    picked = ask(engine, getattr(ctx, "intent", None), checkpoint_id(engine, "HUNGER_PROVENANCE", actor.entity_id), actor,
                 CHOICE + "hunger_provenance", options,
                 labels={value: PROVENANCE_LABELS[value] for value in wanted} | {PROVENANCE_OTHER: "some other creature"},
                 name="Digestive Mantle: which creature?", feature_id="Digestive Mantle",
                 preferred=[PROVENANCE_OTHER], allow_decline=True, target_id=actor.entity_id,
                 prompt=f"Digestive Mantle spends one Satiety. {names} asks where the creature this meal came from, which "
                        f"the table records apart from which kind of meal it is. Choose what this Satiety was refined from.")
    return picked[0] if picked and picked[0] in wanted else ""


def _reads_provenance(row: dict[str, Any], held: Any) -> bool:
    """Whether the provenance this Hunger row reads is the one recorded on this Mantle."""
    declared = [str(value) for value in row.get("reads_provenance") or ()]
    return bool(declared) and str((held.data or {}).get("provenance") or "") in declared


def _legacy_predator_meal(row: dict[str, Any], held: Any) -> bool:
    """Whether this Mantle was burned from the predator meal the way a table sealed before the provenance question records it.

    That data reads the predator line as a kind of meal -- the row declares ``reads: ["predator"]`` and the Mantle stores
    ``satiety: "predator"`` -- so the same printed die opens from that recorded meal. It needs both halves: a row that reads
    no such kind, and a Mantle that recorded no such meal, leave the printed line shut."""
    declared = [str(value) for value in row.get("reads") or ()]
    return LEGACY_PREDATOR in declared and str((held.data or {}).get("satiety") or "") == LEGACY_PREDATOR


def _opens_predator_die(row: dict[str, Any], held: Any) -> bool:
    """Whether this Hunger row's predator line is open for the Mantle it is reading, whichever shape the row was sealed with:
    today's rows answer it as the recorded provenance, and a table sealed against the older rules data answers it as the
    recorded meal. Both are the same printed question ("Satiety from a predator or apex beast"), so a fight the table was
    already playing keeps the die its row was compiled to grant rather than losing it to a later rules edit."""
    return _reads_provenance(row, held) or _legacy_predator_meal(row, held)


def _extra_benefit(ctx: Any, held: Any, wanted: int, required: bool, payer: str | None = None, free: int = 1,
                   payer_name: str = "") -> list[str]:
    """The printed "choose two (or more) basic Mantle benefits instead of one": the extra benefit(s), asked once, stored on the
    Mantle's own condition beside the first.  Only one chosen benefit may add damage and only one may grant Resistance.
    ``payer`` is the feature whose printed line spends a further Satiety for each benefit, and ``free`` is how many benefits
    that price does not reach -- the Mantle's own Satiety pays for the first, and a printed "choose two" for the next -- so the
    actor never holds a benefit they did not pay for and never pays twice for one they were given."""
    engine, actor = ctx.engine, ctx.actor
    current = list((held.data or {}).get("benefits") or [])
    banked = int((actor.resources or {}).get(SATIETY_POOL, 0))
    paid_count = 0
    while len(current) < wanted:
        # The balance to read is the one left, not how many benefits are already held: this benefit costs a Satiety of its
        # own only when it is past the free entitlement, and only if one is left to spend.
        paid = bool(payer) and len(current) >= free
        if paid and banked < 1:
            note(engine, payer, actor,
                 f"{payer_name or 'A Hunger talent'}: you have no Satiety left to spend, so the Mantle keeps "
                 f"{len(current)} {'benefit' if len(current) == 1 else 'benefits'} rather than {wanted}.")
            break
        chosen = [b for b in BENEFITS if b not in current
                  and not (b in ADDS_DAMAGE and any(picked in ADDS_DAMAGE for picked in current))
                  and not (b in GRANTS_RESISTANCE and any(picked in GRANTS_RESISTANCE for picked in current))]
        if not chosen:
            break
        # One question per benefit number: two asks inside the same intent must not share a checkpoint, or the second
        # reuses the first one's answer and answers an option that is no longer on the menu.
        picked = ask(engine, ctx.intent, checkpoint_id(engine, f"MANTLE_BENEFIT_{len(current) + 1}", actor.entity_id),
                     actor, CHOICE + "mantle_benefit",
                     chosen, labels={b: f"Digestive Mantle: {b}" for b in chosen}, preferred=_preferred(chosen),
                     target_id=actor.entity_id, maximum=1, minimum=1, allow_decline=not required,
                     name="Digestive Mantle", feature_id="Digestive Mantle",
                     prompt=f"Digestive Mantle: choose basic Mantle benefit number {len(current) + 1}. Only one chosen benefit may add "
                            f"damage and only one may give Resistance."
                            + (f" This one spends 1 more Satiety; you have {banked}." if paid else ""))
        if not picked:
            break
        current.append(picked[0])
        if paid:
            engine._spend_resource(actor, SATIETY_POOL, 1, payer)
            banked -= 1
            paid_count += 1
    if paid_count and (held.data or {}).get('runtime') == 1:
        _additional_meal_purity(ctx, held)
    return current


def _additional_meal_purity(ctx: Any, held: Any) -> None:
    """Every additional activation purchase counts toward Maw's end receipt."""
    engine, actor = ctx.engine, ctx.actor
    if held.data.get('runtime') != 1 or row_of(engine, actor, 'maw') is None:
        return
    picked = ask(engine, ctx.intent, checkpoint_id(engine, 'EXTRA_MEAL_PURITY', actor.entity_id), actor,
            CHOICE + 'extra_meal_purity', ['ordinary_only', 'includes_impure'], target_id=actor.entity_id,
            labels={'ordinary_only': 'Every additional Satiety was an ordinary meal',
                    'includes_impure': 'At least one was Corrupted, Demon-Beast or Forbidden Satiety'},
            name='Maw of Ten Thousand Courses', feature_id='Maw of Ten Thousand Courses',
            prompt='Maw of Ten Thousand Courses: did any additional Satiety you spent come from a Corrupted, '
                   'Demon-Beast or Forbidden meal? Only an entirely ordinary Mantle reduces Impurity when it ends.')
    held.data = {**held.data, 'additional_impure': bool(held.data.get('additional_impure')
                 or (picked and picked[0] == 'includes_impure'))}
    record_instance_update(engine, actor, 'condition', held.instance_id, held)


def _preferred(options: list[str]) -> list[str]:
    """The table's own first suggestion, only when it is actually on the menu (Never answer with a benefit already held)."""
    return [b for b in ("Thick Hide",) if b in options]


def _write_benefits(engine: Any, actor: Any, held: Any, benefits: list[str]) -> None:
    """The chosen benefits on the Mantle's own condition.  ``used`` is deliberately left alone: it counts the printed
    "once before the Mantle ends" uses, and only a *new* Mantle (hunger_used) starts that count again -- Three-Course
    Battle Body changes the benefit and does not end the Mantle."""
    data = held.data or {}
    data["benefits"] = benefits
    data["label"] = "Digestive Mantle: " + (", ".join(benefits) or "active")
    if data.get("adaptation"):
        data["label"] += f" ({data['adaptation']})"
    held.data = data
    record_instance_update(engine, actor, "condition", held.instance_id, held)


@hook("technique_start")
def replace_mantle(engine: Any, actor: Any, action: Any) -> None:
    """End the previous owned bundle before the new option applies its effects.

    Source identity covers old saves without tracked instance ids. Other
    abilities' buffs and other casters' effects remain untouched.
    """
    typed = (getattr(action, "parameters", None) or {}).get("typed") or {}
    if (typed.get("option_of") or typed.get("source")) != MANTLE_ID:
        return
    from types import SimpleNamespace
    from .end_effect import remove_instance

    ctx = SimpleNamespace(engine=engine, actor=actor, source=action.source_definition_id, action=action, typed=typed)
    # Costs were paid while the old Mantle was active. Preserve its CP-spend
    # rider before removing it; the turn flag prevents a duplicate later.
    _marrow_pulse(ctx)
    previous_mantle = mantle(actor)
    if previous_mantle is not None:
        # "Activating a new Digestive Mantle ends the previous one", and "when that Mantle ends" is owed on that ending
        # too -- not only when the minute runs out. technique_start runs before technique_used (typed_executor
        # .resolve_typed), so the debt has to be settled here or the removal below throws it away.
        _mantle_ends(engine, actor, previous_mantle)
    for kind, store in (("condition", actor.conditions), ("modifier", actor.modifiers)):
        for key, item in list(store.items()):
            previous = engine.action_catalog.get(item.source_definition_id)
            prior = (getattr(previous, "parameters", None) or {}).get("typed") or {}
            if item.source_actor_id == actor.entity_id and (
                    item.source_definition_id == MANTLE_ID or
                    (prior.get("option_of") or prior.get("source")) == MANTLE_ID):
                remove_instance(ctx, actor, kind, key, item)


@hook("technique_used")
def hunger_used(ctx: Any) -> None:
    engine, actor = ctx.engine, ctx.actor
    source, name = _feature(ctx), str(getattr(ctx.action, "display_name", "") or "")
    _marrow_pulse(ctx)  # before a new Mantle is put on: its own activation is not spent "while Digestive Mantle is active"
    if source == MANTLE_ID:
        benefits = [b for b in BENEFITS if b in name]
        adaptation = next((a for a in ADAPTATIONS if a in name), None)
        if mantle(actor) is not None:
            _mantle_ends(engine, actor, mantle(actor))  # "Activating a new Digestive Mantle ends the previous one."
            engine._remove_condition(actor, MANTLE, MANTLE_ID)
        engine._remove_condition(actor, state_id(), MANTLE_ID)
        engine._apply_condition(actor, MANTLE, MANTLE_ID, actor.entity_id, expires_on=ctx.expires_on() or "UNTIL_REMOVED",
                                data={"benefits": benefits, "adaptation": adaptation, "pb": int(ctx.numbers.get("pb") or 2),
                                      "key": int(ctx.numbers.get("key_mod") or 0), "used": [], "satiety": _satiety(ctx),
                                      "provenance": _provenance(ctx),
                                      **({"runtime": 1} if row_of(engine, actor, "mantle_policy") else {}),
                                      **({"fly_speed_ft": int(actor.speed_ft)} if adaptation == "Winged Hunger" else {}),
                                      "label": "Digestive Mantle: " + (", ".join(benefits) or "active") + (f" ({adaptation})" if adaptation else "")})
        # The same Mantle as the shared named state, so a printed "while Digestive Mantle is active" line can offer its own
        # no-Bonus-Action copy of another Hunger ability (combat/ext/free_uses.py reads the state by name).
        engine._apply_condition(actor, state_id(), MANTLE_ID, actor.entity_id, expires_on=ctx.expires_on() or "UNTIL_REMOVED",
                                data={"label": "Digestive Mantle", "name": MANTLE_STATE})
        held = mantle(actor)
        kind = str((held.data or {}).get("satiety") or "normal")
        extra, required, payer, free, payer_name = _bonus_benefits(engine, actor, kind)
        if kind == "demon_beast":
            # The base ability's Demon-Beast Course prints two benefits "instead of one" for a demon-beast meal; the Mantle
            # is already on with its first, and that second one is part of the same Satiety. So it is a free benefit: only
            # the ones past it are priced, and only when a talent prints a price (Maw of Ten Thousand Courses).
            extra, required, free = max(extra, 2), True, max(free, 2)
        if extra > 1 and held is not None:
            _write_benefits(engine, actor, held, _extra_benefit(ctx, held, extra, required, payer, free, payer_name))
        if (held.data or {}).get("runtime") == 1:
            _clear_standing(ctx)
            _hundred_flavour(ctx)
            _short_flight(ctx)
            _fang_begin(ctx)
        from .hunger_second_pass import begin_courses
        begin_courses(ctx)
        if "Elemental Gut" in (mantle(actor).data or {}).get("benefits") or []:
            _elemental_gut(ctx)
    elif source == H + "three_course_battle_body" and mantle(actor) is not None:
        _three_course(ctx)
    elif source == "HUNGER_BASE_TASTE_THE_QI":
        _empty_bowl(ctx)


def _three_course_left(engine: Any, actor: Any) -> int:
    """Three-Course Battle Body's printed Proficiency-Bonus allowance, less the uses this fight has recorded."""
    found = row_of(engine, actor, "three_course")
    return 0 if found is None else int(found.get("pb") or 2) - uses(engine, actor, H + "three_course_battle_body")


@hook("candidate_allowed")
def three_course_is_offered_only_while_the_mantle_is_up(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """Three-Course Battle Body prints "When Digestive Mantle is active" and "replace your current basic Mantle benefit",
    so with no Mantle there is nothing to replace and the action is not offered.  Its printed allowance is enforced on the
    button too: once spent, it is no longer a choice to take (the Satiety is never charged for a use that may not happen)."""
    typed = (getattr(action, "parameters", None) or {}).get("typed") or {}
    if (typed.get("option_of") or typed.get("source")) != H + "three_course_battle_body":
        return None
    return mantle(actor) is not None and _three_course_left(engine, actor) > 0


def _three_course(ctx: Any) -> None:
    """Three-Course Battle Body: "you may use a Bonus Action to consume 1 additional Satiety and replace your current basic
    Mantle benefit with a different basic Mantle benefit"; gain PB Temporary HP; a number of times equal to PB per long rest."""
    engine, actor = ctx.engine, ctx.actor
    found = row_of(engine, actor, "three_course")
    if found is None:
        return
    feature = H + "three_course_battle_body"
    left = _three_course_left(engine, actor)
    if left <= 0:
        note(engine, feature, actor, f"Three-Course Battle Body: you have used it {int(found.get('pb') or 2)} times since your last long rest.")
        return
    held = mantle(actor)
    current = list((held.data or {}).get("benefits") or [])
    options = [b for b in BENEFITS if b not in current]
    if not options:
        return
    record_use(engine, actor, feature, "Three-Course Battle Body")
    picked = ask(engine, ctx.intent, checkpoint_id(engine, f"THREE_COURSE_{len(current)}", actor.entity_id), actor,
                 CHOICE + "three_course", options,
                 labels={b: f"Three-Course Battle Body: {b}" for b in options}, preferred=_preferred(options), target_id=actor.entity_id,
                 name="Three-Course Battle Body", feature_id="Three-Course Battle Body",
                 prompt="Three-Course Battle Body: you burn one more Satiety and your Digestive Mantle's benefit becomes the one "
                        "you choose. You have used this " + str(int(found.get("pb") or 2) - left) + " of "
                        + str(int(found.get("pb") or 2)) + " times since your last long rest.")
    if picked:
        if (held.data or {}).get("runtime") == 1:
            _clear_standing(ctx)
            held.data.pop("element", None)
            held.data.pop("secondary", None)
        _write_benefits(engine, actor, held, [picked[0]])
        if (held.data or {}).get("runtime") == 1:
            _standing(ctx)
            _elemental_gut(ctx)
        engine._grant_temp_hp(actor, int(found.get("pb") or 2), feature, actor.entity_id)
        note(engine, feature, actor, f"Three-Course Battle Body: the Mantle becomes {picked[0]}.")


def _marrow_pulse(ctx: Any) -> None:
    """Marrow-Furnace Pulse: "While Digestive Mantle is active, once per turn when you spend CP on a Hunger talent, you may gain Temporary
    HP equal to your Proficiency Bonus." From a demon-beast Mantle it is "instead" +PB on one damage roll that turn, and 1
    Impurity when the Mantle ends (that half runs from ``_mantle_ends``)."""
    engine, actor = ctx.engine, ctx.actor
    found = row_of(engine, actor, "marrow")
    if found is None or mantle(actor) is None or not _feature(ctx).startswith((H, "HUNGER_BASE")):
        return
    if not any(str(resource).startswith(("resource:core.qi", "resource:core.stamina")) for resource, _amount in getattr(ctx.action, "costs", ()) or ()):
        return
    if actor.turn_flags.get("hunger_marrow") == actor.turns_started:
        return
    actor.turn_flags["hunger_marrow"] = actor.turns_started
    pb = int(found.get("pb") or 2)
    if (mantle(actor).data or {}).get("satiety") == "demon_beast":
        actor.turn_flags["hunger_marrow_damage"] = pb
        if (mantle(actor).data or {}).get("runtime") == 1:
            mantle(actor).data["marrow_debt"] = True
            record_instance_update(engine, actor, "condition", mantle(actor).instance_id, mantle(actor))
        note(engine, H + "marrow_furnace_pulse", actor,
             f"Marrow-Furnace Pulse: one damage roll this turn gains +{pb}, and you gain 1 Impurity when the Mantle ends.")
        return
    engine._grant_temp_hp(actor, pb, H + "marrow_furnace_pulse", actor.entity_id)


def change_impurity(engine: Any, actor: Any, amount: int, feature: str, why: str) -> None:
    """Public Impurity settlement for Hunger and hunger_second_pass.

    Impurity is a plain integer pool, so gaining it is one capped gain and reducing it one clamped spend (the two
    engine entry points a typed gain_resource / spend_resource row uses)."""
    pool = "resource:named.impurity"
    held = {**dict(getattr(actor, "resources", {}) or {}), **dict(getattr(actor, "resource_maximums", {}) or {})}
    if pool not in held:
        return
    if amount >= 0:
        engine._gain_resource(actor, pool, int(amount), feature)
    elif actor.resources.get(pool, 0) > 0:
        engine._spend_resource(actor, pool, min(-int(amount), int(actor.resources[pool])), feature)
    note(engine, feature, actor, why)


def _mantle_ends(engine: Any, actor: Any, held: Any) -> None:
    """Everything the printed rules owe when a Digestive Mantle ends: the base ability's Demon-Beast Course Impurity, the
    Constitution save Demon-Beast Digestion takes in its place, Marrow-Furnace Pulse's demon-beast Impurity, and Maw of Ten
    Thousand Courses' reduction.  Runs once per Mantle, whether a new one replaced it or its minute ran out."""
    data = held.data or {}
    if data.get("ended"):
        return
    data["ended"] = True
    record_instance_update(engine, actor, "condition", held.instance_id, held)
    from .hunger_second_pass import end_courses
    end_courses(engine, actor, held)
    kind = str(data.get("satiety") or "normal")
    if row_of(engine, actor, "marrow") is not None and kind == "demon_beast" and (data.get("marrow_debt") or actor.turn_flags.get("hunger_marrow_damage")):
        actor.turn_flags.pop("hunger_marrow_damage", None)
        change_impurity(engine, actor, 1, H + "marrow_furnace_pulse",
                  "Marrow-Furnace Pulse: the demon-beast Mantle ends, and you gain 1 Impurity.")
    if row_of(engine, actor, "maw") is not None and kind == "normal" and not data.get('additional_impure'):
        # "When the Mantle ends, reduce your Impurity by 1 if none of the spent Satiety was Corrupted, Demon-Beast, or Forbidden."
        change_impurity(engine, actor, -1, H + "maw_of_ten_thousand_courses",
                  "Maw of Ten Thousand Courses: the Mantle ends and every Satiety it burned was an ordinary meal, so you lose 1 Impurity.")
    if kind != "demon_beast":
        return
    if "demon_beast" in _reads(engine, actor, "reads") and row_of(engine, actor, "demon") is not None:
        # Demon-Beast Digestion changes the base rule: a Constitution save against your Hunger Save DC instead of flat Impurity.
        dc = hunger_save_dc(engine, actor)
        roll = engine._roll_save(actor, "CON", dc, H + "demon_beast_digestion")
        if roll is not None and int(roll.total) < dc:
            change_impurity(engine, actor, 1, H + "demon_beast_digestion",
                      f"Demon-Beast Digestion: the Mantle ends and your Constitution save against DC {dc} fails, so you gain 1 Impurity.")
        else:
            note(engine, H + "demon_beast_digestion", actor,
                 f"Demon-Beast Digestion: the Mantle ends and you hold your Constitution save against DC {dc}.")
        return
    # The base ability's own line: "Demon-Beast Course: ... Gain 1 Impurity when the Mantle ends unless another talent changes this."
    change_impurity(engine, actor, 1, MANTLE_ID, "Demon-Beast Course: the demon-beast Mantle ends, and you gain 1 Impurity.")


def hunger_save_dc(engine: Any, actor: Any) -> int:
    """Public Hunger Save DC for this owner and hunger_second_pass pressure.

    Read the sealed technique save DC its own actions carry, else 10.
    """
    for action in engine.action_catalog.values():
        if action.owner_id != actor.entity_id:
            continue
        dc = int((((action.parameters or {}).get("typed") or {}).get("numbers") or {}).get("save_dc") or 0)
        if dc:
            return dc
    return 10


def _foundation(engine: Any, actor: Any) -> bool:
    """Foundation Realm or above: the printed Realm bands are Mortal 1-4, Foundation 5-9, Core Formation 10-14, Nascent Soul 15+."""
    from .passive_rows import known_level

    level = known_level(engine, actor)
    return level is not None and level >= 5


def _empty_bowl(ctx: Any) -> None:
    engine, actor = ctx.engine, ctx.actor
    found = row_of(engine, actor, "empty_bowl")
    if found is None or mantle(actor) is None or actor.turn_flags.get("hunger_empty_bowl") == engine.state.round_number:
        return
    for target in ctx.targets or []:
        if target is None:
            continue
        bloodied = target.current_hp * 2 <= target.maximum_hp
        poisoned = any(c.condition_id.endswith("poisoned") for c in target.conditions.values())
        if bloodied or poisoned:
            actor.turn_flags["hunger_empty_bowl"] = engine.state.round_number  # "only once per round"
            engine._grant_temp_hp(actor, int(found.get("pb") or 2), H + "the_empty_bowl_watches", actor.entity_id)
            return


@effect("hunger_adaptation")
def adaptation(ctx: Any, eff: dict[str, Any]) -> None:
    """Nine-Beast Sovereign Course's sovereign adaptation, chosen as one option of the Mantle.

    Nothing is applied here: the Mantle's own condition carries the choice (read back from the action's name) and each
    adaptation's line is run from where it belongs -- ``fly_speed_ft`` in the condition data (combat/flight.py) for Winged
    Hunger, ``thick_hide`` for Armored Hunger, ``_venom_sovereign`` for Venom Sovereign, and ``Burrowing Hunger`` stays a
    GM line because a table map carries no earth, sand or stone for a creature to burrow through.
    """


@hook("effect_expiring")
def mantle_expiring(engine: Any, holder: Any, row: Any) -> None:
    """The Mantle's own minute running out is "when that Mantle ends" for every printed line that waits for it."""
    held = mantle(holder)
    if held is not None and (held.data or {}).get("runtime") == 1:
        if getattr(row, "condition_id", None) == SECONDARY:
            secondary = held.data.pop("secondary", None)
            _write_benefits(engine, holder, held, [b for b in held.data.get("benefits", []) if b != secondary])
        elif getattr(row, "condition_id", None) == WINGED:
            held.data.pop("fly_speed_ft", None)
            record_instance_update(engine, holder, "condition", held.instance_id, held)
    if getattr(row, "condition_id", None) == MANTLE and holder.entity_id:
        _mantle_ends(engine, holder, row)


# ------------------------------------------------------------------------------------------------ the benefits
def _last_type(engine: Any, actor: Any, target: Any) -> str:
    last = next((e for e in reversed(engine.events[-30:]) if e.event_type == "DAMAGE_COMMITTED" and e.actor_id == actor.entity_id
                 and target.entity_id in (e.target_ids or ())), None)
    return str((last.payload or {}).get("damage_type") or "UNTYPED") if last is not None else "UNTYPED"


def _bloodied(target: Any) -> bool:
    return int(getattr(target, "current_hp", 0)) * 2 <= int(getattr(target, "maximum_hp", 0))


def _die_size(engine: Any, actor: Any) -> int:
    """One roll of the actor's own damage die: the biggest weapon damage die any of its own attacks uses, else a d8
    ("your Martial Arts die, weapon damage die, or a d8, whichever is most appropriate to your build").

    A compiled weapon attack carries it at ``typed["weapon"]["damage"]["sides"]`` (combat/factory_compiler.py), never at
    the top level of ``typed``."""
    sides = 0
    for action in engine.action_catalog.values():
        if action.owner_id != actor.entity_id or not str(action.source_definition_id).startswith("action:"):
            continue
        typed = (action.parameters or {}).get("typed") or {}
        weapon = typed.get("weapon") or {}
        damage = weapon.get("damage") if isinstance(weapon, dict) and isinstance(weapon.get("damage"), dict) else {}
        rolled = int(damage.get("count") or 0) and int(damage.get("sides") or 0)
        if rolled:
            sides = max(sides, int(damage["sides"]))
    return max(4, sides) if sides else 8


def _once(engine: Any, actor: Any, held: Any, name: str) -> bool:
    used = list((held.data or {}).get("used") or [])
    if name in used:
        return False
    held.data["used"] = [*used, name]
    record_instance_update(engine, actor, "condition", held.instance_id, held)
    return True


@hook("event")
def track_moves(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """Predator Step needs where its holder moved from and to this turn."""
    if event_type != "MOVEMENT_COMMITTED":
        return
    actor = engine.state.actors.get(str(kwargs.get("actor_id") or ""))
    if actor is None or _has(actor, "Predator Step") is None or engine.state.current_actor_id != actor.entity_id:
        return
    path = [p for p in (kwargs.get("payload") or {}).get("path") or [] if isinstance(p, dict)]
    if len(path) >= 2 and not (kwargs.get("payload") or {}).get("forced"):
        moves = [m for m in actor.turn_flags.get("hunger_moves") or [] if m[0] == actor.turns_started]
        actor.turn_flags["hunger_moves"] = [*moves, [actor.turns_started, path[0]["x"], path[0]["y"], path[-1]["x"], path[-1]["y"]]]


def _moved_toward(engine: Any, actor: Any, target: Any) -> bool:
    step = engine.grid.square_size_ft
    for turn, sx, sy, ex, ey in actor.turn_flags.get("hunger_moves") or []:
        if turn != actor.turns_started:
            continue
        before = max(abs(sx - target.position.x), abs(sy - target.position.y)) * step
        after = max(abs(ex - target.position.x), abs(ey - target.position.y)) * step
        if before - after >= 10:
            return True
    return False


@hook("after_hit")
def mantle_hit(ctx: Any, target: Any, kind: str) -> None:
    engine, actor = ctx.engine, ctx.actor
    held = mantle(actor)
    if held is None or not target.active:
        return
    data = held.data or {}
    pb, key = int(data.get("pb") or 2), int(data.get("key") or 0)
    benefits = data.get("benefits") or []
    melee = ctx.typed.get("range_ft") is None or int(ctx.typed.get("range_ft") or 0) <= 5
    if "Beast Strength" in benefits and melee and kind in ("weapon", "unarmed") and _once(engine, actor, held, "beast"):
        engine._commit_damage(target, pb, _last_type(engine, actor, target), MANTLE_ID, actor.entity_id, None, reaction_depth=1)
    if "Predator Step" in benefits and _moved_toward(engine, actor, target) and _once(engine, actor, held, "predator"):
        engine._commit_damage(target, pb, _last_type(engine, actor, target), MANTLE_ID, actor.entity_id, None, reaction_depth=1)
    king = row_of(engine, actor, "predator_king")
    if king is not None and "Predator Step" in benefits and _opens_predator_die(king, held) \
            and _bloodied(target) and _once(engine, actor, held, "predator_king"):
        # "When you activate Digestive Mantle using Satiety from a predator or apex beast ... once before the Mantle ends,
        # when you hit a Bloodied creature with an attack, you may add damage equal to one roll of your Martial Arts die,
        # weapon damage die, or a d8" (Predator-King Digestion). Where the creature came from is recorded beside the kind of
        # meal, so a predator's demon-beast or bone portion is both that meal and this provenance.
        from ..gate2_runtime_models import DiceSpec

        sides = _die_size(engine, actor)
        feature = H + "predator_king_digestion"
        roll = engine.roller.roll(DiceSpec(count=1, sides=sides, modifier=0), actor_id=actor.entity_id, reason=f"DAMAGE:{feature}")
        engine._record_roll(roll)
        engine._commit_damage(target, int(roll.total), _last_type(engine, actor, target), feature, actor.entity_id, None,
                              reaction_depth=1)
    for benefit, kind_ in (("Venom Belly", "POISON"), ("Furnace Belly", "FIRE")):
        if benefit in benefits and actor.turn_flags.get(f"hunger_{benefit}") != _turn_key(engine):
            actor.turn_flags[f"hunger_{benefit}"] = _turn_key(engine)  # "Once per turn when you hit with an attack"
            engine._commit_damage(target, pb + key, kind_, MANTLE_ID, actor.entity_id, None, reaction_depth=1)
            if benefit == "Venom Belly" and data.get("adaptation") == "Venom Sovereign" and target.active:
                _venom_sovereign(engine, actor, target)


@hook("damage_roll_bonus")
def hunger_damage_bonus(ctx: Any, effect_row: Any = None, kinds: Any = None) -> int | None:
    """Marrow-Furnace Pulse from a demon-beast Mantle: "+PB to one damage roll that turn"."""
    amount = int(getattr(ctx.actor, "turn_flags", {}).get("hunger_marrow_damage") or 0)
    if not amount:
        return None
    ctx.actor.turn_flags["hunger_marrow_damage"] = 0  # "one damage roll that turn"
    return amount


def _turn_key(engine: Any) -> str:
    return f"{engine.state.round_number}:{engine.state.current_actor_id}"


ELEMENTS = ("acid", "cold", "fire", "lightning", "necrotic", "poison", "thunder")


def _elemental_gut(ctx: Any) -> None:
    """Elemental Gut: "Choose Acid, Cold, Fire, Lightning, Necrotic, Poison, or Thunder, as appropriate to the Satiety
    source.  You gain Resistance to that damage type while the Mantle lasts."

    The typed option row cannot hold one chosen type (it lists all seven), so the table is asked which one fits the meal
    this Mantle burned -- the ``satiety`` recorded on the Mantle's own condition is named in the prompt -- and the
    Resistance is applied to that type alone for the Mantle's own minute."""
    from ..typed_executor import run_effects

    engine, actor = ctx.engine, ctx.actor
    held = mantle(actor)
    if held is None or "Elemental Gut" not in ((held.data or {}).get("benefits") or []) or (held.data or {}).get("element"):
        return
    meal = SATIETY_LABELS.get(str((held.data or {}).get("satiety") or "normal"), "a normal meal")
    lasting = ('until the end of your next turn' if held.data.get('runtime') == 1
               and held.data.get('secondary') == 'Elemental Gut' else 'while the Mantle lasts')
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "ELEMENTAL_GUT", actor.entity_id), actor,
                 CHOICE + "elemental_gut", list(ELEMENTS), labels={kind: f"Elemental Gut: Resistance to {kind.title()}" for kind in ELEMENTS},
                 preferred=["poison"], target_id=actor.entity_id, maximum=1, minimum=1, name="Digestive Mantle",
                 feature_id="Digestive Mantle",
                 prompt=f"Digestive Mantle: this Mantle burns {meal}. Elemental Gut gives you Resistance to the one damage "
                        f"type that suits it {lasting}. Choose that damage type.")
    if not picked:
        return
    held.data = {**(held.data or {}), "element": picked[0]}
    record_instance_update(engine, actor, "condition", held.instance_id, held)
    source_ctx = ctx.with_source(MANTLE_ID) if held.data.get("runtime") == 1 else ctx
    run_effects(source_ctx, [{"type": "resistance", "applies_to": "self", "damage_types": [picked[0]],
                       "duration": ctx.expires_on() or "one_minute",
                       **({"expires_on": (turn_token('end', actor.entity_id, actor.turns_started + 1)
                            if held.data.get('secondary') == 'Elemental Gut' else held.expires_on)}
                          if held.data.get('runtime') == 1 else {}),
                       "evidence": f"You gain Resistance to that damage type {lasting}"}])
    note(engine, MANTLE_ID, actor, f"Elemental Gut: you have Resistance to {picked[0]} damage {lasting}.")


def _venom_sovereign(engine: Any, actor: Any, target: Any) -> None:
    from ..typed_executor import run_effects
    from .. import typed_reactions

    dc = next((int(((a.parameters or {}).get("typed") or {}).get("numbers", {}).get("save_dc") or 0) for a in engine.action_catalog.values()
               if a.owner_id == actor.entity_id and (((a.parameters or {}).get("typed") or {}).get("numbers") or {}).get("save_dc")), 10)
    roll = engine._roll_save(target, "CON", dc, H + "nine_beast_sovereign_course")
    if roll is not None and int(roll.total) < dc:
        ctx = typed_reactions._generic_context(engine, actor, target, {"feature_id": H + "nine_beast_sovereign_course", "name": "Venom Sovereign",
                                                                         "effects": [], "numbers": {}})
        run_effects(ctx, [{"type": "condition", "condition": "poisoned", "applies_to": "target", "duration": "until_start_of_next_turn"}])


@hook("incoming_damage")
def thick_hide(engine: Any, target: Any, amount: int, damage_type: str, source_definition_id: str, source_actor_id: str | None) -> int | None:
    held = _has(target, "Thick Hide")
    if held is None or amount <= 0 or str(damage_type).upper() not in ("BLUDGEONING", "PIERCING", "SLASHING"):
        return None
    if target.turn_flags.get("hunger_thick_hide") == engine.state.round_number:
        return None
    target.turn_flags["hunger_thick_hide"] = engine.state.round_number  # "Once per round"
    data = held.data or {}
    pb = int(data.get("pb") or 2)
    key = int(data.get("key") or 0)
    if data.get("adaptation") == "Armored Hunger":
        cut = 3 * pb + key  # Nine-Beast Sovereign Course
    elif "bone" in _reads(engine, target, "reads") and str(data.get("satiety") or "") == "bone" and _foundation(engine, target):
        cut = 2 * pb + key  # Beast-Bone Broth "At Foundation Realm, Thick Hide from Bone Satiety reduces damage by twice your PB"
    else:
        cut = pb + key
    from .hunger_second_pass import scale_cut
    cut = scale_cut(engine, target, held, cut)
    note(engine, MANTLE_ID, target, f"Thick Hide: the blow drops by {min(cut, amount)}.")
    return min(cut, amount)


@hook("after_save")
def mantle_save(ctx: Any, subject: Any, ability: str, named: Any, failed: bool) -> None:
    engine = ctx.engine
    held = mantle(subject)
    if failed or held is None:
        return
    names = {str(n).lower() for n in named or ()}
    if not names & {"poisoned", "disease", "diseased"}:
        return
    data = held.data or {}
    if "Iron Stomach" in (data.get("benefits") or []):
        engine._grant_temp_hp(subject, int(data.get("pb") or 2), MANTLE_ID, subject.entity_id)
    found = row_of(engine, subject, "bitter")
    cp = _cp(subject)
    if found and "poisoned" in names and cp is not None and subject.resources.get(cp, 0) >= 1:
        picked = ask(engine, ctx.intent, checkpoint_id(engine, "BITTER_MEDICINE", subject.entity_id), subject, CHOICE + "bitter_medicine", ["use"],
                     labels={"use": "Bitter Medicine Belly (1 CP): Temporary HP equal to your Proficiency Bonus"}, allow_decline=True,
                     target_id=subject.entity_id, prompt="You shrug off the poison: Bitter Medicine Belly?")
        if picked:
            with activation(engine, subject, H + "bitter_medicine_belly"):
                engine._spend_resource(subject, cp, 1, H + "bitter_medicine_belly")
                engine._grant_temp_hp(subject, int(found.get("pb") or 2), H + "bitter_medicine_belly", subject.entity_id)

BENEFIT_TEXT = {
    'Beast Strength': 'Beast Strength — Advantage on Strength checks and saves; add PB damage to one melee or unarmed hit',
    'Predator Step': 'Predator Step — +10 feet Speed; add PB damage to one hit after moving 10 feet toward its target',
    'Iron Stomach': 'Iron Stomach — Advantage against Poisoned and Disease; a successful save grants PB Temporary HP',
    'Thick Hide': 'Thick Hide — once per round, reduce physical damage by PB plus your Hunger ability modifier',
    'Venom Belly': 'Venom Belly — once per turn, add PB plus your Hunger ability modifier as Poison or Acid damage on a hit (GM decides from the source)',
    'Furnace Belly': 'Furnace Belly — once per turn, add PB plus your Hunger ability modifier as Fire damage on a hit',
    'Elemental Gut': 'Elemental Gut — choose one damage type to resist',
    'Deep Nourishment': 'Deep Nourishment — Advantage on Constitution saves against travel or deprivation Exhaustion',
}
SECONDARY = 'condition:typed.hunger_secondary'
WINGED = 'condition:typed.hunger_winged_expiry'
FANG = H + 'devour_the_venom_keep_the_fang'


@effect('hunger_runtime')
def runtime_marker(ctx: Any, row: dict[str, Any]) -> None:
    """Owned sealed passive rows execute these reviewed combat effects."""


def _modern(actor: Any) -> Any:
    held = mantle(actor)
    return held if held is not None and held.data.get('runtime') == 1 else None


def _clear_standing(ctx: Any) -> None:
    """Remove only the caster's basic Mantle buffs, preserving its state/adaptations."""
    from .end_effect import remove_instance
    engine, actor = ctx.engine, ctx.actor
    for kind, store in (('condition', actor.conditions), ('modifier', actor.modifiers)):
        for key, item in list(store.items()):
            action = engine.action_catalog.get(item.source_definition_id)
            typed = (getattr(action, 'parameters', None) or {}).get('typed') or {}
            owned = item.source_actor_id == actor.entity_id and (item.source_definition_id == MANTLE_ID or
                    (typed.get('option_of') or typed.get('source')) == MANTLE_ID)
            if owned and (kind == 'modifier' or item.condition_id not in (MANTLE, state_id(), SECONDARY, WINGED)):
                remove_instance(ctx, actor, kind, key, item)


def _standing(ctx: Any) -> None:
    from ..typed_executor import run_effects
    held = _modern(ctx.actor)
    if held is None:
        return
    rows = []
    for benefit in held.data.get('benefits', []):
        expiry = (turn_token('end', ctx.actor.entity_id, ctx.actor.turns_started + 1)
                  if benefit == held.data.get('secondary') else held.expires_on)
        if benefit == 'Beast Strength':
            rows.append({'type': 'advantage', 'on': 'Strength checks'})
        elif benefit == 'Predator Step':
            rows.append({'type': 'speed', 'flat': 10})
        elif benefit == 'Deep Nourishment':
            rows.append({'type': 'advantage', 'on': 'Constitution saving throws against Exhaustion caused by travel, starvation, thirst, exposure, disease, or hostile terrain'})
        else:
            continue
        rows[-1].update(applies_to='self', expires_on=expiry)
    run_effects(ctx.with_source(MANTLE_ID), rows)


def _hundred_flavour(ctx: Any) -> None:
    engine, actor = ctx.engine, ctx.actor
    held = mantle(actor)
    current = list(held.data.get('benefits', []))
    if row_of(engine, actor, 'hundred') is None or actor.resources.get(SATIETY_POOL, 0) < 1 or len(current) != 1:
        _standing(ctx)
        return
    choices = [b for b in BENEFITS if b not in current and not (b in ADDS_DAMAGE and current[0] in ADDS_DAMAGE)]
    picked = ask(engine, ctx.intent, checkpoint_id(engine, 'HUNDRED_FLAVOUR', actor.entity_id), actor,
        CHOICE + 'hundred_flavour', choices, allow_decline=True,
        labels={b: 'Secondary Mantle: ' + BENEFIT_TEXT[b] for b in choices}, target_id=actor.entity_id,
        name='Hundred-Flavour Mantle', feature_id='Hundred-Flavour Mantle',
        prompt='Hundred-Flavour Mantle: spend 1 additional Satiety for a second benefit until the end of your next turn. '
               'Your first benefit lasts for the full Mantle. Only one may add damage. PB means your Proficiency Bonus. You may decline.')
    if picked:
        engine._spend_resource(actor, SATIETY_POOL, 1, H + 'hundred_flavour_mantle')
        _additional_meal_purity(ctx, held)
        held.data['secondary'] = picked[0]
        _write_benefits(engine, actor, held, [*current, picked[0]])
        engine._apply_condition(actor, SECONDARY, MANTLE_ID, actor.entity_id,
            expires_on=turn_token('end', actor.entity_id, actor.turns_started + 1), data={'label': 'Secondary Mantle: ' + picked[0]})
    _standing(ctx)


def _short_flight(ctx: Any) -> None:
    held = mantle(ctx.actor)
    if held.data.get('adaptation') == 'Winged Hunger':
        ctx.engine._apply_condition(ctx.actor, WINGED, MANTLE_ID, ctx.actor.entity_id,
            expires_on=turn_token('end', ctx.actor.entity_id, ctx.actor.turns_started + 1),
            data={'label': 'Winged Hunger: until the end of your next turn'})


def _save_mode(actor: Any, ability: str, named: Any) -> str | None:
    held = _modern(actor)
    if held is None:
        return None
    benefits = held.data.get('benefits', [])
    names = {str(n).lower() for n in named or ()}
    if 'Beast Strength' in benefits and str(ability).upper() == 'STR':
        return 'ADVANTAGE'
    if 'Iron Stomach' in benefits and names & {'poisoned', 'disease', 'diseased'}:
        return 'ADVANTAGE'
    return None


@hook('save')
def modern_mantle_save(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    mode = _save_mode(subject, ability, named)
    return {'bonus': 0, 'modes': [mode]} if mode else None


@hook('save_mode')
def modern_native_save(engine: Any, target: Any, ability: str, dc: int, source_id: str, roll_context: Any) -> str | None:
    return _save_mode(target, ability, (roll_context or {}).get('named'))


def _fang_begin(ctx: Any) -> None:
    from ..typed_executor import run_effects
    engine, actor = ctx.engine, ctx.actor
    if row_of(engine, actor, 'fang') is None:
        return
    from .end_effect import remove_instance
    for iid, item in list(actor.modifiers.items()):
        if item.source_definition_id == FANG and item.source_actor_id == actor.entity_id:
            remove_instance(ctx, actor, 'modifier', iid, item)
    picked = ask(engine, ctx.intent, checkpoint_id(engine, 'FANG_MEAL', actor.entity_id), actor,
        CHOICE + 'fang_meal', ['acid', 'poison', 'necrotic'], allow_decline=True,
        automatic=False, default='decline',
        labels={k: 'Qualifying meal: Resistance to ' + k.title() for k in ('acid', 'poison', 'necrotic')},
        target_id=actor.entity_id, name='Devour the Venom, Keep the Fang', feature_id='Devour the Venom, Keep the Fang',
        prompt='Devour the Venom, Keep the Fang: if this Satiety is venomous, poisonous, acidic, diseased or corrupted, '
               'choose the appropriate damage type. Otherwise decline. Resistance lasts until the start of your next turn; '
               'you may later spend a Reaction and 1 CP to resist one matching damage instance and gain Temporary HP.')
    if picked:
        held = mantle(actor)
        # The answer declares both eligibility and the appropriate type. Unknown
        # provenance is never upgraded by the automatic first-option policy.
        held.data = {**held.data, 'fang_meal_eligible': True, 'fang_type': picked[0]}
        record_instance_update(engine, actor, 'condition', held.instance_id, held)
        run_effects(ctx.with_source(FANG), [{'type': 'resistance', 'applies_to': 'self', 'damage_types': picked,
            'duration': 'until_start_of_next_turn', 'evidence': 'Resistance to the chosen damage type'}])


@hook('damage_defended')
def fang_defended(engine: Any, target: Any, damage_type: str, source_id: str,
                  source_actor_id: str | None, defenses: dict[str, bool]) -> None:
    """Retain the actual packet result, including consumed next-hit Resistance."""
    if _modern(target) is not None and row_of(engine, target, 'fang') is not None:
        engine.__dict__.setdefault('_hunger_defended', []).append((target.entity_id, str(damage_type).lower(),
            source_id, source_actor_id, bool(defenses.get('resist') or defenses.get('resistance_suppressed'))))


@hook('final_damage')
def fang_damage(engine: Any, target: Any, amount: int, damage_type: str, source_id: str,
                source_actor_id: str | None, intent: Any) -> dict[str, int] | None:
    from .. import typed_reactions
    held, found, dtype, cp = _modern(target), row_of(engine, target, 'fang'), str(damage_type).lower(), _cp(target)
    row = {**(found or {}), 'feature_id': FANG, 'name': 'Devour the Venom, Keep the Fang'}
    receipts = engine.__dict__.get('_hunger_defended', [])
    resisted = False
    packet = (target.entity_id, dtype, source_id, source_actor_id)
    for index in range(len(receipts) - 1, -1, -1):
        if receipts[index][:4] == packet:
            resisted = receipts.pop(index)[4]
            break
    if (held is None or found is None or not held.data.get('fang_meal_eligible')
            or amount <= 0 or dtype != held.data.get('fang_type') or cp is None
            or target.resources.get(cp, 0) < 1 or not typed_reactions.can_use_reaction(engine, target, target, row)):
        return None
    from .choice_prompt import action_context
    trigger = action_context(engine, engine.state.actors.get(source_actor_id), source_id, target)
    if not trigger['action_name']:
        # Generic reactions synthesize an action from their sealed row rather
        # than installing it in the catalog. Name that packet, never the outer
        # intent (which may be another creature's action).
        trigger['action_name'] = next((str(r.get('name') or '') for r in
            (getattr(engine, 'typed_reaction_rows', {}) or {}).get(source_actor_id, [])
            if r.get('feature_id') == source_id), '')
    picked = ask(engine, intent, checkpoint_id(engine, 'FANG_DAMAGE', target.entity_id), target,
        CHOICE + 'fang_damage', ['use'], allow_decline=True, target_id=target.entity_id,
        labels={'use': 'Reaction and 1 CP: resist this damage and gain Temporary HP'},
        name='Devour the Venom, Keep the Fang', feature_id='Devour the Venom, Keep the Fang',
        prompt_context={**trigger,
                        'cost': 'Reaction and 1 CP', 'paying_pool': cp},
        prompt=f'Devour the Venom, Keep the Fang: spend your Reaction and 1 CP to resist this {dtype} damage instance '
               f'and gain {int(found.get("pb") or 2)} Temporary HP?')
    if not picked:
        return None
    engine._spend_resource(target, cp, 1, FANG)
    typed_reactions.open_reaction(engine, row, target, (target.entity_id,), 'FANG_DAMAGE')
    engine._grant_temp_hp(target, int(found.get('pb') or 2), FANG, target.entity_id)
    return {'amount': amount if resisted else amount // 2}


# This Insight uses the existing transactional d20 rewrite owner. It needs no
# Mantle, Reaction, or new engine checkpoint; scene usage is once per fight.
from .d20_rewrite import Rule, register


def _iron_belly_poison(engine: Any, holder: Any, context: Any) -> bool:
    return 'poisoned' in context.named


register(Rule('hunger_iron_belly', 'Iron Belly Foundation', rolls=('save',), abilities=('CON',),
              costs=((("cp", 1),),), limit='fight', guard=_iron_belly_poison))


@hook('choice_reactors')
def iron_belly_choosers(engine: Any) -> tuple[str, ...]:
    """Enroll manual/Ask-me owners even when someone else forces their save."""
    return tuple(sorted(actor_id for actor_id, rows in (getattr(engine, 'typed_passive_rows', {}) or {}).items()
                        if any(r.get('block') == 'd20_rewrite' and r.get('kind') == 'hunger_iron_belly' for r in rows)))
