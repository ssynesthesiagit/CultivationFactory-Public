"""Glass's Faultline Mark reactions (A2GLASS, Glass sphere automation second pass).

Owner text (APP/authority/typed_mechanics/rules_text.json).  These three printed lines were entirely GM-run riders;
this module runs what a fight can see.

  Break the Proud Weapon (CL 12+)
    "When a marked creature hits with a weapon attack, you may use your Reaction and spend the mark.  The creature makes
    a Strength saving throw.  Failed Save: The weapon, natural weapon, or striking limb is fractured by clear lines until
    the start of your next turn.  The attack still resolves, but the marked creature has Disadvantage on the next attack
    roll it makes with the same weapon or limb before the effect ends. ... Successful Save: Reduce the triggering damage by
    your Proficiency Bonus."
    The whole line ran as a GM rider.  The printed trigger is the whole line as written -- no reading narrows it to the
    caster's own body, and none of it excludes a thrown or shot weapon -- so ``hit_response`` answers it: that hook runs
    once the roll is a hit and *before* damage resolves, which is the only point at which "reduce the triggering damage"
    can mean this hit rather than some later one.  The fracture is one named weapon or limb ("the same weapon or limb"),
    so it answers the ``attack_mode`` hook of the *fractured creature's own* next roll with that weapon, and it lasts
    until the start of the caster's next turn ("your next turn").  Break the Line on a nonmagical weapon damages an
    *object*, and objects are not damageable creatures in this engine, so that clause stays with the GM and is said out
    loud below.

  Spell-Line Crack (Hidden Crack Study, CL 10+)
    "When a marked creature casts a spell, spends CP, or activates a supernatural feature while you can see it through a
    Glass Surface, use your Reaction and spend the mark.  The creature makes a Wisdom saving throw.  Failed Save: Choose
    one: reduce the damage of the triggering effect by 2d8 + your Proficiency Bonus against one target; one target of the
    effect gains Advantage on one saving throw against it; if the effect requires Concentration, the creature has
    Disadvantage on the first Constitution saving throw it makes to maintain that Concentration before the end of its next
    turn.  Successful Save: The triggering creature cannot take Reactions until the start of its next turn.  Spell-Line Crack
    does not cancel the triggering effect."

  Flaw Within the Golden Technique (Spell-Line Crack, CL 15+)
    "When a creature with a Faultline Mark uses a Domain, Realm Evolution, major forged technique, or other high-cost
    supernatural feature within 60 feet, use your Reaction and spend the mark. ... Failed Save: Choose one: reduce the
    triggering effect's damage against all targets by 4d8; one ally affected by the triggering effect automatically succeeds
    on one saving throw against it; reduce the triggering effect's duration by 1 round, minimum 1 round; the creature cannot
    use the same feature again until the end of its next turn.  Successful Save: One ally affected by the triggering effect
    gains Resistance to one damage type dealt by the effect until the end of the current turn."

  Both share one shape -- a marked creature activates something, the caster spends a mark and a Reaction, one Wisdom
  saving throw, then four printed answers -- so they share one body here and differ only in their trigger, their reach and
  their answers.  A mark is never placed by this module: it spends the ones glass_refraction owns, so a mark means the same
  thing whichever talent placed it.

Recipient rule: a recipient is chosen by the side the printed text names, never by "everyone the caster can see".
  Both lines answer to a *marked* creature, and a Faultline Mark is Glass's own hostile-creature rule, so the caster's own
  side is never marked here.  Flaw's "one **ally** affected by the triggering effect" and its Successful Save are filtered
  to the caster's own side and asked over the creatures the effect actually reached; Spell-Line's "one **target** of the
  effect" is the effect's own aimed targets, which may be on either side because the printed line names no side.  An AI
  owner is handed the printed answer, never the union of the list it perceives.

Judgment calls, said rather than invented:
  - "high-cost supernatural feature" (Flaw) is read as a technique that declares a Cultivation Point or Qi cost, or a
    zone-creating Domain.  A free technique and a basic attack are not high-cost, so they never trigger the line.
  - "the same weapon or limb" is one weapon or limb for the life of the fracture; the first attack roll made with it is the
    one that pays, which the condition's own single removal enforces.
  - "one target of the effect" is the technique's own aimed target list.  An effect with no recorded target offers no target
    question and keeps the rest of its printed line.
  - The duration reduction is applied to the printed rounds of the interrupted effect through the engine's own round clock.
  - Not modelled, and left with the GM: Break the Line's damage to a weapon object, and Flaw's "unless the GM says the
    inheritance has already exposed a visible faultline".
  - Non-combat text stays text: Mirror-Clear Testimony's remembered contradiction, Hidden Crack Study's Study check, and the
    narrative question in Heaven Reveals the Single Faultline.
"""

from __future__ import annotations

from typing import Any

from . import hook, note

BLOCK = "a2_glass"
T = "TAL_GLASS_"
MARK = "Faultline Mark"
C = "condition:typed."

PRIDE = T + "BREAK_THE_PROUD_WEAPON"
SPELL_LINE = T + "SPELL_LINE_CRACK"
FLAW = T + "FLAW_WITHIN_THE_GOLDEN_TECHNIQUE"

FRACTURED = C + "glass_fractured_weapon"
CON_DISADV = C + "glass_flaw_concentration_save"
REACTION_DENIED = C + "glass_spell_line_no_reaction"
AUTO_SAVE = C + "glass_flaw_auto_save"
SAVE_ADV = C + "glass_spell_line_advantage"
RESIST_EFFECT = C + "glass_flaw_resist"
FEATURE_LOCKED = C + "glass_flaw_feature_locked"

# The engine's own damage-type vocabulary (combat/factory_compiler.py), offered to the player as plain names.
DAMAGE_TYPES = ("Acid", "Bludgeoning", "Cold", "Fire", "Force", "Lightning", "Necrotic", "Piercing", "Poison",
                "Psychic", "Radiant", "Slashing", "Thunder")


# ------------------------------------------------------------------------------------------------ owning rows
@hook("compile_block")
def compile_rows(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Seal the printed numbers these three reactions read (Proficiency Bonus, Cultivation Level, Glass Save DC)."""
    if block != BLOCK:
        return None
    return [{**row, "block": BLOCK, "kind": spec.get("kind"), "pb": int(numbers.get("pb") or 2),
             "cl": int(numbers.get("cl") or 1), "dc": int(numbers.get("save_dc") or 10)}]


def rows(engine: Any, actor: Any, kind: str) -> list[dict[str, Any]]:
    return [row for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, [])
            if row.get("block") == BLOCK and row.get("kind") == kind]


def _numbers(engine: Any, actor: Any, kind: str) -> dict[str, int]:
    """The sealed printed numbers of the caster's own row.

    The Glass Save DC is read from the caster's compiled abilities at ask time (needle.save_dc, the Cultivation Save DC
    every other Glass talent compares against) rather than sealed here, so a fighter whose DC changes with its own stats
    or with an applied modifier is asked at the right number.
    """
    from . import needle

    row = (rows(engine, actor, kind) or [{}])[0]
    return {"pb": int(row.get("pb") or 2), "cl": int(row.get("cl") or 1),
            "dc": int(needle.save_dc(engine, actor))}


def _casters(engine: Any, kind: str) -> list[Any]:
    return [actor for actor in engine.state.actors.values() if actor.active and rows(engine, actor, kind)]


def _token(actor: Any, edge: str, ahead: int = 1) -> str:
    from .effect_durations import token

    return token(edge, actor.entity_id, int(actor.turns_started) + ahead)


def _marked(engine: Any, caster: Any, subject: Any) -> bool:
    from . import glass_refraction

    return glass_refraction.marked(subject, caster.entity_id)


def _ai_owns(engine: Any, actor: Any) -> bool:
    from . import glass_refraction

    return glass_refraction.ai_owns(engine, actor)


def _spend_mark(engine: Any, caster: Any, subject: Any, source: str) -> None:
    """Spend the caster's Faultline Mark through the shared Glass helper.

    A mark is one record with one meaning wherever it was placed, so the removal and the ``mark_spent`` announcement are
    ``glass_refraction.spend_mark``'s job and no second mark ledger exists here.
    """
    from . import glass_refraction

    glass_refraction.spend_mark(engine, caster, subject, source)


def _ask_spend(engine: Any, caster: Any, subject: Any, source: str, key: str, name: str, trigger: str, label: str) -> bool:
    """Whether to spend the mark and the Reaction on this printed line.  An AI owner answers for itself.

    A printed "you may" is a real question with a decline, so a MANUAL fighter still decides (corkboard #1545: a MANUAL
    controller receives the choice rather than having it auto-taken); the built-in AI takes the printed answer.
    """
    from .. import typed_reactions
    from .rider_choices import pick

    if not _marked(engine, caster, subject) or not typed_reactions._can_react(engine, caster):
        return False
    if not pick(engine, caster, key, name, ["use"], subject=subject, preferred=["use"],
                labels={"use": f"Spend your Reaction and {subject.display_name}'s Faultline Mark on {label}"}, trigger=trigger,
                optional=True, automatic=_ai_owns(engine, caster)):
        return False
    caster.reaction_available = False
    _spend_mark(engine, caster, subject, source)
    return True


def _saves(engine: Any, actor: Any, ability: str, dc: int, source: str) -> bool:
    roll = engine._roll_save(actor, ability, dc, source)
    return bool(int(getattr(roll, "total", 0)) >= dc)


# ------------------------------------------------------------------------------------------------ Break the Proud Weapon
def _attack_weapon(engine: Any, spec: dict[str, Any], source_id: Any) -> str:
    """Which weapon or natural limb this attack was actually made with.

    "the same weapon or limb" is a weapon identity, not a label, so the fracture records the identity the engine itself
    resolves for the strike (``combat/weapon_delivery.weapon_identity``, the shared reader ``combat/ext/weapon_hits.py``
    exposes for exactly this).  An attack the engine cannot attribute to one weapon -- a bare unarmed strike, a manoeuvre
    with no declared grip -- resolves to the empty identity and is the "striking limb" the printed line also names.
    """
    from ..weapon_delivery import weapon_identity

    typed = dict((spec or {}).get("typed") or {})
    try:
        return str(weapon_identity(engine, str(source_id or (spec or {}).get("source_definition_id") or ""), typed,
                                   (spec or {}).get("parameters") or {}) or "")
    except Exception:   # an unreadable catalog entry must not silence the printed line; it only widens the identity
        return ""


@hook("hit_response")
def break_the_proud_weapon(engine: Any, attacker: Any, target: Any, spec: dict[str, Any], total: Any, natural: Any,
                          effective_ac: Any) -> None:
    """Break the Proud Weapon: a marked creature's weapon hit pays a fracture or a smaller wound.

    This answers from ``hit_response`` -- "once the roll is a hit", before any damage resolves -- because the printed
    Successful Save reduces *the triggering damage*.  An ``after_hit`` answer runs once that damage has already been dealt
    and notified, so it could only ever discount some later blow; asking here binds the reduction to this hit.  The
    printed trigger is the whole line "When a marked creature hits with a weapon attack": no reading narrows it to the
    caster's own body, and none of it excludes a thrown or shot weapon.

    Returning None leaves the outcome untouched: the printed line never turns a hit into a miss, it only adds a fracture
    or takes damage off, so the hook claims the hit and the engine resolves it as it printed.
    """
    kind = str(((spec or {}).get("parameters") or {}).get("attack_kind") or "")
    if kind not in ("weapon", "unarmed") or target is None or not getattr(target, "active", False):
        return None
    source_id = str((spec or {}).get("source_definition_id") or "")
    action_name = str((spec or {}).get("action_name") or "") or "a weapon attack"
    for caster in _casters(engine, "pride"):
        if not _marked(engine, caster, attacker):
            continue
        if not _ask_spend(engine, caster, attacker, PRIDE, "glass_pride_weapon", "Break the Proud Weapon",
                          f"{attacker.display_name} hits with {action_name}",
                          "Break the Proud Weapon: fracture its weapon or limb, or take less damage from the blow"):
            continue
        numbers = _numbers(engine, caster, "pride")
        weapon = _attack_weapon(engine, spec, source_id)
        limb = _limb_name(engine, attacker, spec, weapon)
        if _saves(engine, attacker, "STR", numbers["dc"], PRIDE):
            # "Successful Save: Reduce the triggering damage by your Proficiency Bonus."  Bound to this attacker and this
            # victim, so it can only ever discount the very blow that earned it.
            _bind_pride_cut(engine, attacker, target, numbers["pb"])
            note(engine, PRIDE, caster,
                 f"Break the Proud Weapon: {attacker.display_name} saves, so this blow deals {numbers['pb']} less damage.")
            return None
        # "until the start of your next turn" -- the caster's next turn, which is whose turn the printed line counts.
        engine._apply_condition(attacker, FRACTURED, PRIDE, caster.entity_id, expires_on=_token(caster, "start"),
                                data={"label": "Break the Proud Weapon: this weapon or limb is fractured by clear lines. "
                                               "Its next attack roll with it has Disadvantage.",
                                      "weapon": weapon, "limb": limb,
                                      "caster_id": caster.entity_id})
        note(engine, PRIDE, caster,
             f"Break the Proud Weapon: {attacker.display_name}'s {limb} is fractured until the start of your next turn, "
             f"so its next attack roll with that same {limb} has Disadvantage. (Break the Line on a nonmagical weapon "
             f"stays with the GM.)")
    return None


def _limb_name(engine: Any, attacker: Any, spec: dict[str, Any], weapon: str) -> str:
    """The fighter-readable name of what was fractured: the weapon if the engine named one, else the striking limb."""
    if not weapon:
        return "striking limb" if str(((spec or {}).get("parameters") or {}).get("attack_kind") or "") == "unarmed" else "weapon"
    catalog = (getattr(engine, "action_catalog", {}) or {}).get(weapon)
    return str(getattr(catalog, "display_name", "") or "weapon")


def _bind_pride_cut(engine: Any, attacker: Any, victim: Any, amount: int) -> None:
    """Record the Successful Save's reduction against this one attacker-victim pair, for the hit that is resolving now."""
    engine.__dict__["_a2glass_pride_cut"] = {"attacker": attacker.entity_id, "victim": victim.entity_id,
                                             "amount": int(amount)}


@hook("attack_mode")
def fracture_disadvantage(ctx: Any, target: Any) -> str | None:
    """The printed fracture: the fractured creature's own next roll with that same weapon or limb, once.

    ``attack_mode`` is handed the *defender*; the fighter rolling the attack is ``ctx.actor``.  Reading the target's
    conditions here penalized whoever attacked the fractured creature and left its own attacks untouched, so this reads
    the attacker's own fracture, checks the strike really uses the fractured weapon or limb (identity recorded by
    ``_attack_weapon``), and consumes it as it answers -- "the next attack roll it makes ... before the effect ends".
    """
    from .weapon_hits import weapon_identity

    engine, attacker = ctx.engine, ctx.actor
    if attacker is None:
        return None
    for instance_id, held in list(attacker.conditions.items()):
        if held.condition_id != FRACTURED:
            continue
        fractured = str((held.data or {}).get("weapon") or "")
        struck = str(weapon_identity(ctx) or "")
        if fractured and struck != fractured:
            continue   # a different weapon or limb: the printed line names "the same weapon or limb"
        attacker.conditions.pop(instance_id, None)
        engine._append_event("CONDITION_REMOVED", PRIDE, actor_id=attacker.entity_id,
                             target_ids=(attacker.entity_id,),
                             payload={"condition_id": FRACTURED, "instance_id": instance_id, "reason": "CONSUMED"})
        note(engine, PRIDE, attacker,
             f"Break the Proud Weapon: your fractured {(held.data or {}).get('limb') or 'weapon or limb'} strikes with "
             f"Disadvantage.")
        return "DISADVANTAGE"
    return None


@hook("damage_pending")
def pride_damage_cut(engine: Any, target: Any, pending: int, source_definition_id: Any, source_actor_id: Any) -> int | None:
    """The Successful Save's printed reduction, applied to the very blow that earned it.

    The bound record names both the attacker and the victim, so a packet from any other attacker -- or against any other
    victim -- is left alone, and consuming it here keeps it to one hit.
    """
    from .attack_reduction import remember

    bound = engine.__dict__.pop("_a2glass_pride_cut", None)
    if not isinstance(bound, dict) or pending <= 0:
        return None
    if str(bound.get("victim") or "") != target.entity_id or str(bound.get("attacker") or "") != str(source_actor_id or ""):
        engine.__dict__["_a2glass_pride_cut"] = bound   # not this blow: keep the record for the hit it was earned on
        return None
    amount = int(bound.get("amount") or 0)
    if amount <= 0:
        return None
    return remember(engine, target, pending, max(0, pending - amount), [(amount, ())])


# ------------------------------------------------------------------------------------------------ the shared Crack body
def _costs_qi(action: Any) -> bool:
    """Whether this action spends Cultivation Points or Qi (Flaw's "high-cost").

    Read from both places the catalog keeps a price: the action definition's own ``costs`` and the typed parameters a
    typed row carries (``parameters.typed.costs``).  A row may declare its CP or Qi price in either, and a talent that
    answered only one would silently never fire.
    """
    prices = list(getattr(action, "costs", None) or [])
    typed = (getattr(action, "parameters", None) or {}).get("typed") or {}
    prices.extend(typed.get("costs") or [])
    for cost in prices:
        text = str(cost).lower()
        if ".cp" in text or "core.qi" in text or "core.cp" in text:
            return True
    return False


def _high_cost(action: Any) -> bool:
    """Flaw's "Domain, Realm Evolution, major forged technique, or other high-cost supernatural feature".

    Read from the action's own declared prices: a technique that spends Cultivation Points or Qi is high-cost by the printed
    wording.  A free technique and a basic attack are not, so they never trigger this line.
    """
    return action is not None and _costs_qi(action)


KINDS = ("spell_line", "flaw")
_CRACK_NAME = {"spell_line": "Spell-Line Crack", "flaw": "Flaw Within the Golden Technique"}


@hook("technique_start")
def spell_line_crack(engine: Any, actor: Any, action: Any) -> None:
    """Spell-Line Crack: a marked creature's spell, CP spend or supernatural feature, seen through a Glass Surface.

    Both Crack hooks dispatch into the same ``_crack`` for the same activation (one ``technique_start`` call each), so a
    caster who owns both talents is asked about both together there, instead of whichever hook happens to run first
    silently taking the only answer.
    """
    _crack(engine, actor, action)


@hook("technique_start")
def flaw_within_the_golden_technique(engine: Any, actor: Any, action: Any) -> None:
    """Flaw Within the Golden Technique: a marked creature's high-cost feature within 60 feet.

    This runs at ``technique_start`` -- as the feature is used, before its effects resolve -- because the printed line is a
    reaction to the creature *using* the feature ("When a creature with a Faultline Mark uses a Domain ... use your
    Reaction and spend the mark"), and because a mark spent later would already have been answered by the damage packet's
    own Refraction Responses.  See ``spell_line_crack`` above for how a caster owning both talents is handled.
    """
    _crack(engine, actor, action)


def _intent_id(engine: Any, action: Any) -> str:
    intent = getattr(engine, "_active_intent", None)
    return intent.intent_id if intent is not None else str(getattr(action, "source_definition_id", "") or "")


def _eligible(engine: Any, caster: Any, actor: Any, action: Any, kind: str) -> bool:
    """Whether ``kind``'s own printed trigger is met right now, for a caster who owns that talent's row."""
    if not rows(engine, caster, kind):
        return False
    if kind == "flaw":
        return engine._distance_actor_to_actor(caster, actor) <= 60 and _high_cost(action)
    return _through_glass(engine, caster, actor)


def _choose_kind(engine: Any, caster: Any, actor: Any, action: Any, legal: list[str]) -> str | None:
    """Both printed lines are legal at once: the owner (or AI) chooses which one answers this activation.

    Only one mark/Reaction answers one activation ("Flaw Within the Golden Technique" is itself gated behind owning
    Spell-Line Crack, and the two share one Faultline Mark economy), so this is one question, not two sequential ones
    where declining the first silently forfeits the second.
    """
    from .rider_choices import pick

    action_name = str(getattr(action, "display_name", "") or "") or "a supernatural feature"
    chosen = pick(engine, caster, "glass_crack_choice", "Faultline Mark", legal,
                 labels={kind: _CRACK_NAME[kind] for kind in legal}, subject=actor,
                 preferred=[legal[0]], optional=True, automatic=_ai_owns(engine, caster),
                 trigger=f"{actor.display_name} uses {action_name}",
                 prompt=f"{actor.display_name} uses {action_name}: both of your Faultline Mark reactions could answer "
                        f"this. Choose one, or decline -- only one can spend the mark.")
    return str(chosen[0]) if chosen else None


def _crack(engine: Any, actor: Any, action: Any) -> None:
    """One mark, one Reaction, one Wisdom saving throw, then the printed answers of whichever line answers.

    Both technique hooks call this for the same activation; dispatch per caster is recorded once (``dispatched``) so the
    second call is a no-op and a caster who owns both talents is asked about both together, not whichever is visited
    first -- and declining does not silently forfeit the other, because there is only ever one combined question.
    """
    if actor is None or not actor.active:
        return
    intent = _intent_id(engine, action)
    if engine.__dict__.get("_a2glass_intent") != intent:
        # A new activation starts fresh.
        engine.__dict__["_a2glass_crack"] = []
        engine.__dict__["_a2glass_intent"] = intent
        engine.__dict__["_a2glass_dispatched"] = set()
    dispatched = engine.__dict__.setdefault("_a2glass_dispatched", set())
    casters: dict[str, Any] = {}
    for kind in KINDS:
        for caster in _casters(engine, kind):
            casters.setdefault(caster.entity_id, caster)
    for caster in casters.values():
        if caster.team_id == actor.team_id or not _marked(engine, caster, actor):
            continue
        key = (caster.entity_id, actor.entity_id)
        if key in dispatched:
            continue
        legal = [kind for kind in KINDS if _eligible(engine, caster, actor, action, kind)]
        if not legal:
            continue
        dispatched.add(key)
        kind = legal[0] if len(legal) == 1 else _choose_kind(engine, caster, actor, action, legal)
        if kind is None:
            continue
        source = SPELL_LINE if kind == "spell_line" else FLAW
        name = _CRACK_NAME[kind]
        action_name = str(getattr(action, "display_name", "") or "") or "a supernatural feature"
        if not _ask_spend(engine, caster, actor, source, f"glass_{kind}", name,
                          f"{actor.display_name} uses {action_name}",
                          f"{name}: spend your Reaction and {actor.display_name}'s Faultline Mark to interrupt "
                          f"{action_name}, then roll its Wisdom saving throw"):
            continue
        numbers = _numbers(engine, caster, kind)
        if _saves(engine, actor, "WIS", numbers["dc"], source):
            _saved(engine, caster, actor, action, numbers, kind, source, name)
        else:
            _failed(engine, caster, actor, action, numbers, kind, source, name)


def _through_glass(engine: Any, caster: Any, creature: Any) -> bool:
    """Whether the caster can see ``creature`` through one of their own Glass Surfaces.

    Spell-Line Crack's trigger is "while you can see it through a Glass Surface": the sight path itself has to cross a
    surface the caster controls, not merely coexist with owning one somewhere else on the map (a pane behind the caster
    does not qualify a creature standing in front).  Glass Surfaces are transparent -- that is the sphere's own premise
    ("Your transparent panes..."), and Temper Glass Surface makes the caster's own body one, so sight that starts at the
    caster's own cell already starts on a surface when the caster is tempered.  The sight ray is the same center-to-center
    segment ``combat/space.effect_ray`` uses for physical effect propagation; its crossed cells are compared against the
    caster's own Glass Surface cells.  No Cover is ignored, and a caster with no glass of their own never answers.
    """
    from . import glass_refraction
    from ..action_geometry import point as actor_point
    from ..gate2_runtime_models import Position
    from ..space import effect_ray, projection

    surfaces = glass_refraction.surface_cells(engine, caster)
    if not surfaces:
        return False
    origin = actor_point(engine, caster)
    for cell in engine._actor_cells(creature):
        target = Position(x=cell[0], y=cell[1])
        if not engine._line_of_sight_actor_to_cell(caster, target):
            continue
        if surfaces & {projection(voxel) for voxel in effect_ray(origin, target)}:
            return True
    return False


def _effect_targets(engine: Any, actor: Any, action: Any) -> list[Any]:
    """The creatures the interrupted effect actually reaches -- its "target of the effect".

    Two ordinary sources, both already in the engine: the active intent's own aimed target list, and -- because a
    cell-aimed area has not calculated its recipients yet at ``technique_start`` (``typed_executor.resolve_typed`` only
    does that after every ``technique_start`` subscriber, this one included, has run) -- the creatures standing in the
    aim point's own area.  The area's own geometry lives on the action's compiled typed data (``parameters.typed.area``),
    the same place ``resolve_typed`` reads it from; the aim point is the intent's own ``destination`` (what
    ``resolve_typed`` passes as ``candidate.destination``) -- neither is a field of ``ActionIntent`` under any other
    name.  An unrelated creature in range is never offered.
    """
    intent = getattr(engine, "_active_intent", None)
    ids = tuple(getattr(intent, "target_ids", ()) or ())
    found = [engine.state.actors[actor_id] for actor_id in ids if actor_id in engine.state.actors]
    found = [creature for creature in found if creature.active]
    seen = {creature.entity_id for creature in found}
    typed = (getattr(action, "parameters", None) or {}).get("typed") or {}
    area = typed.get("area") or {}
    size = area.get("size_ft") if isinstance(area, dict) else None
    if actor is not None and size:
        try:
            from ..typed_executor import _area_targets

            aim_point = getattr(intent, "destination", None)
            for creature in _area_targets(engine, actor, aim_point, area, typed=typed):
                if creature.active and creature.entity_id not in seen:
                    seen.add(creature.entity_id)
                    found.append(creature)
        except Exception:   # an unreadable aim never invents a recipient; the aimed targets above still stand
            pass
    return found


def _allies(engine: Any, caster: Any, reached: list[Any]) -> list[Any]:
    """The printed "one **ally** affected by the triggering effect": the caster's own side only.

    Recipient rule: an enemy inside the reached list is never offered, and the whole list is never handed over as one
    preference.  Allies are ordered by how much they need it (current hit points), then by id, so the AI owner and a player
    are shown the same candidates in the same order.
    """
    return sorted((actor for actor in reached if actor.team_id == caster.team_id and actor is not caster),
                  key=lambda actor: (actor.current_hp, actor.entity_id))


def _ask_recipient(engine: Any, caster: Any, subject: Any, pool: list[Any], key: str, name: str, question: str,
                   purpose: str) -> Any | None:
    """Which one of the creatures the effect reached takes the printed answer.

    A printed "one target" / "one ally" is a player-owned decision, so a manual owner is asked over exactly the
    creatures the effect reached; an AI owner takes the first of the same ordered list.
    """
    from .rider_choices import pick

    if not pool:
        return None
    labels = {creature.entity_id: f"{creature.display_name} {purpose}" for creature in pool}
    chosen = pick(engine, caster, f"glass_{key}", name, [creature.entity_id for creature in pool], labels=labels,
                  subject=subject, preferred=[pool[0].entity_id], optional=False, automatic=_ai_owns(engine, caster),
                  prompt=question, automatic_options=[creature.entity_id for creature in pool])
    if not chosen:
        return pool[0] if _ai_owns(engine, caster) else None
    wanted = str(chosen[0])
    return next((creature for creature in pool if creature.entity_id == wanted), pool[0])


def _failed(engine: Any, caster: Any, actor: Any, action: Any, numbers: dict[str, int], kind: str, source: str,
            name: str) -> None:
    """The printed Failed Save: one question, the printed answers, applied to the effect that is still resolving.

    Every answer here is a real rule the engine already reads, not a label: the damage answers are rolled printed dice
    bound to the interrupted activation, the save answers are conditions carrying the engine's own ``save_auto`` /
    ``save_mode`` rule data consumed by one save, the feature answer filters that feature out of the fighter's real
    choices, and the Concentration answer is the engine's own ``concentration_mode`` rule data.
    """
    from .rider_choices import pick

    reached = _effect_targets(engine, actor, action)
    if kind == "flaw":
        options = ["reduce", "ally_saves", "shorten", "lock_feature"]
        labels = {"reduce": "The triggering effect deals 4d8 less damage to every target",
                  "ally_saves": "One ally the effect reached automatically succeeds on one saving throw against it",
                  "shorten": "The triggering effect lasts 1 round less (never less than 1 round)",
                  "lock_feature": f"{actor.display_name} cannot use that same feature again until the end of its next turn"}
    else:
        options = ["cut", "target_advantage"]
        labels = {"cut": f"The triggering effect deals 2d8 + {numbers['pb']} less damage against one target",
                  "target_advantage": "One target of the effect gains Advantage on one saving throw against it"}
        if getattr(action, "concentration", False):
            options.append("con_disadvantage")
            labels["con_disadvantage"] = ("It has Disadvantage on the first Constitution saving throw it makes to keep its "
                                          "Concentration")
    chosen = pick(engine, caster, f"glass_{kind}_outcome", name, options, labels=labels, subject=actor,
                  preferred=[options[0]], trigger=f"{actor.display_name} fails its Wisdom saving throw", optional=False,
                  automatic=_ai_owns(engine, caster))
    if not chosen:
        return
    answer = str(chosen[0])
    if answer == "reduce":
        amount = _roll_dice(engine, caster, 4, 8, 0, source)   # "reduce ... by 4d8"
        _bind_crack(engine, actor, None, amount, source)       # "against all targets"
        note(engine, source, caster, f"{name}: the triggering effect deals {amount} less damage to every target.")
    elif answer == "cut":
        amount = _roll_dice(engine, caster, 2, 8, numbers["pb"], source)   # "by 2d8 + your Proficiency Bonus"
        chosen_target = _ask_recipient(engine, caster, actor, reached, f"{name}_cut", name,
                                       "Choose the one target this reduces.", "against one target")
        if chosen_target is None:
            note(engine, source, caster, f"{name}: it dealt no damage, so there is no target to reduce.")
            return
        _bind_crack(engine, actor, chosen_target, amount, source)
        note(engine, source, caster, f"{name}: {chosen_target.display_name} takes {amount} less damage from it.")
    elif answer in ("ally_saves", "target_advantage"):
        pool = _allies(engine, caster, reached) if answer == "ally_saves" else reached
        if not pool:
            note(engine, source, caster, f"{name}: no one the effect reached is affected by that answer.")
            return
        who = _ask_recipient(
            engine, caster, actor, pool, f"{name}_{'auto' if answer == 'ally_saves' else 'target'}", name,
            "Choose the one ally that automatically succeeds." if answer == "ally_saves" else
            "Choose the one target that gains the benefit.",
            "automatically succeeds on one saving throw against it" if answer == "ally_saves" else "against it")
        if who is None:
            note(engine, source, caster, f"{name}: the effect reached no target that could take that benefit.")
            return
        condition = AUTO_SAVE if answer == "ally_saves" else SAVE_ADV
        # The engine reads ``save_auto``/``save_mode`` rule data at every save, and a "next" one is used up by the first
        # save it changes. ``save_mode`` is the engine's own per-ability dict of mode strings (typed_conditions.json,
        # gate2_engine.direct_save_mode/_roll_save, condition_text.mechanics all read it that way); "Advantage on one
        # saving throw" names no ability, so every ability gets the same string, the same shape qi_subpaths_1.py uses
        # for an unnamed-ability grant.
        rule = ({"save_auto": True, "next": True} if answer == "ally_saves"
                else {"save_mode": {ability: "ADVANTAGE" for ability in ("STR", "DEX", "CON", "INT", "WIS", "CHA")},
                      "next": True})
        engine._apply_condition(who, condition, source, caster.entity_id, expires_on=_token(who, "end"),
                                data={"label": f"{name}: this fighter "
                                               f"{'automatically succeeds' if answer == 'ally_saves' else 'has Advantage'} on "
                                               f"one saving throw against the interrupted effect",
                                      "rule": rule, "effect": str(getattr(action, "source_definition_id", "") or ""),
                                      "intent": _intent_id(engine, action)})
        note(engine, source, caster, f"{name}: {who.display_name} answers one saving throw against it.")
    elif answer == "shorten":
        engine.__dict__["_a2glass_shorten"] = {"intent": _intent_id(engine, action),
                                               "effect": str(getattr(action, "source_definition_id", "") or ""),
                                               "before": {(who.entity_id, iid) for who in reached
                                                          for iid in who.conditions},
                                               "zones_before": set(engine.state.zones.keys()),
                                               "zone_ids": set(),
                                               "done": set()}
        note(engine, source, caster, f"{name}: the triggering effect lasts 1 round less (never less than 1 round).")
    elif answer == "lock_feature":
        engine._apply_condition(actor, FEATURE_LOCKED, source, caster.entity_id, expires_on=_token(actor, "end"),
                                data={"label": f"{name}: it cannot use that same feature again until the end of its next turn",
                                      "feature": str(getattr(action, "source_definition_id", "") or "")})
        note(engine, source, caster, f"{name}: {actor.display_name} cannot use that feature again this turn.")
    elif answer == "con_disadvantage":
        # "the first Constitution saving throw it makes to maintain that Concentration" is the engine's own
        # concentration_mode rule data, and a "next" one is used up by the save it changes (combat/concentration.py).
        engine._apply_condition(actor, CON_DISADV, source, caster.entity_id, expires_on=_token(actor, "end"),
                                data={"label": f"{name}: Disadvantage on its first Constitution saving throw to keep its "
                                               f"Concentration",
                                      "rule": {"concentration_mode": "DISADVANTAGE", "next": True}})
        note(engine, source, caster, f"{name}: {actor.display_name} struggles to hold its Concentration.")


def _effect_damage_types(action: Any) -> list[str]:
    """The damage types the triggering effect's own typed rows actually deal, upper-cased, in their printed order.

    Flaw's Successful Save offers "Resistance to one damage type dealt by the effect": the effect's own typed damage
    rows (``combat/effect_harm.rows``, the same public walker ``area_recipients.py`` uses) are the only honest source --
    not the engine's whole damage-type vocabulary, most of which this effect never deals.
    """
    from ..effect_harm import rows as effect_rows

    typed = (getattr(action, "parameters", None) or {}).get("typed") or {}
    seen: set[str] = set()
    found: list[str] = []
    for row in effect_rows(typed.get("effects")):
        if row.get("type") != "damage":
            continue
        for kind in row.get("damage_types") or ():
            upper = str(kind).upper()
            if upper not in seen:
                seen.add(upper)
                found.append(upper)
    return found


def _saved(engine: Any, caster: Any, actor: Any, action: Any, numbers: dict[str, int], kind: str, source: str,
           name: str) -> None:
    """The printed Successful Save, which differs between the two lines."""
    from .rider_choices import pick

    if kind == "flaw":
        dealt = _effect_damage_types(action)
        if not dealt:
            note(engine, source, caster, f"{name}: it saves, and the triggering effect deals no damage type to resist.")
            return
        allies = _allies(engine, caster, _effect_targets(engine, actor, action))
        if not allies:
            note(engine, source, caster, f"{name}: it saves, and no ally it reached can take the Resistance.")
            return
        who = _ask_recipient(engine, caster, actor, allies, f"{name}_resist", name,
                             "Choose the one ally that gains the Resistance.", "gains Resistance")
        if who is None:
            note(engine, source, caster, f"{name}: it saves, and no ally it reached takes the Resistance.")
            return
        options = [kind for kind in DAMAGE_TYPES if kind.upper() in dealt]
        chosen_type = pick(engine, caster, f"{name}_resist_kind", name, options,
                           labels={kind: f"Resistance to {kind} damage until the end of this turn" for kind in options},
                           subject=who, preferred=[options[0]], optional=False, automatic=_ai_owns(engine, caster),
                           prompt=f"{name}: {who.display_name} resists one kind of damage the triggering effect dealt, "
                                  f"until the end of this turn. Choose which kind.")
        damage_type = str((chosen_type or [options[0]])[0]).upper()
        # "Resistance to one damage type dealt by the effect until the end of the current turn" is the engine's own
        # damage_resistances rule data (combat/ext/standard_conditions.py), and the printed clock is this turn's end.
        engine._apply_condition(who, RESIST_EFFECT, source, caster.entity_id, expires_on="END_OF_CURRENT_TURN",
                                data={"label": f"{name}: Resistance to {str((chosen_type or [options[0]])[0])} damage "
                                               f"until the end of this turn",
                                      "rule": {"damage_resistances": [damage_type]}})
        note(engine, source, caster, f"{name}: it saves, and {who.display_name} resists "
                                     f"{str((chosen_type or [options[0]])[0])} damage from it until the end of this "
                                     f"turn.")
        return
    # Spell-Line Crack: "The triggering creature cannot take Reactions until the start of its next turn."  That is the
    # engine's own no_reactions rule data, which sets reaction_available False the moment it applies.
    engine._apply_condition(actor, REACTION_DENIED, source, caster.entity_id, expires_on=_token(actor, "start"),
                            data={"label": "Spell-Line Crack: it cannot take Reactions until the start of its next turn",
                                  "rule": {"no_reactions": True}})
    note(engine, source, caster, f"{name}: {actor.display_name} saves and cannot take Reactions until the start of its next "
                                 f"turn.")


@hook("save")
def one_shot_save(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    """The one-shot save answers of both Crack lines, read at a real save and consumed by it.

    ``save_auto`` makes the save succeed outright and ``save_mode`` grants Advantage; both are rule data this plug-in
    writes on its own conditions (Glass's Spell-Line "one target ... Advantage on one saving throw" and Flaw's "one ally
    ... automatically succeeds").  A "next" one is used up by the first save it changes, so each is answered exactly once.
    """
    modes, used = [], []
    intent = _intent_id(ctx.engine, ctx.action)
    for instance_id, condition in list(subject.conditions.items()):
        if condition.condition_id not in (AUTO_SAVE, SAVE_ADV):
            continue
        data = condition.data or {}
        if data.get("intent") != intent or data.get("effect") != str(getattr(ctx.action, "source_definition_id", "") or ""):
            continue   # only the save of the effect this grant was made against, in the activation that made it
        rule = data.get("rule") or {}
        save_mode = rule.get("save_mode")
        if rule.get("save_auto"):
            modes.append("AUTO_SUCCESS")
        elif isinstance(save_mode, dict) and ability in save_mode and str(save_mode[ability]).upper() in ("ADVANTAGE", "DISADVANTAGE"):
            modes.append(str(save_mode[ability]).upper())
        else:
            continue
        if rule.get("next"):
            used.append((instance_id, condition))
    if not modes:
        return None
    for instance_id, condition in used:
        subject.conditions.pop(instance_id, None)
        ctx.engine._append_event("CONDITION_REMOVED", str(condition.source_definition_id or ""),
                                 actor_id=subject.entity_id, target_ids=(subject.entity_id,),
                                 payload={"condition_id": condition.condition_id, "instance_id": instance_id,
                                          "reason": "CONSUMED"})
    # AUTO_SUCCESS is not one of the engine's d20 modes, so it is delivered as a bonus no save can roll past.
    bonus = 1000 if "AUTO_SUCCESS" in modes else 0
    return {"bonus": bonus, "modes": [mode for mode in modes if mode in ("ADVANTAGE", "DISADVANTAGE")]}


@hook("candidate_allowed")
def feature_locked_candidate(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """Flaw's "the creature cannot use the same feature again until the end of its next turn".

    The printed lock is the engine's own choice filter: a fighter is never offered an action this condition names, so
    the locked feature cannot be used again before the condition's own end.  Other fighters and other features are
    untouched.
    """
    feature = str(getattr(action, "source_definition_id", "") or "")
    if not feature:
        return None
    for condition in actor.conditions.values():
        if condition.condition_id != FEATURE_LOCKED or str((condition.data or {}).get("feature") or "") != feature:
            continue
        return False
    return None


# ------------------------------------------------------------------------------------------------ Crack damage answers
def _roll_dice(engine: Any, roller: Any, count: int, sides: int, modifier: int, source: str) -> int:
    """The printed dice of a Crack answer, rolled once and recorded like any other roll."""
    from ..gate2_runtime_models import DiceSpec

    roll = engine.roller.roll(DiceSpec(count=int(count), sides=int(sides), modifier=int(modifier)),
                              actor_id=roller.entity_id, reason=f"DAMAGE_REDUCTION:{source}")
    engine._record_roll(roll)
    return max(0, int(getattr(roll, "total", 0) or 0))


def _bind_crack(engine: Any, actor: Any, target: Any, amount: int, source: str) -> None:
    """Bind a damage answer to the activation it interrupted: its actor, and one chosen target or every target."""
    pending_reductions = engine.__dict__.setdefault("_a2glass_crack", [])
    pending_reductions.append({"actor": actor.entity_id,
                               "target": str(getattr(target, "entity_id", "") or ""),
                               "amount": int(amount), "source": str(source)})


@hook("damage_pending")
def crack_damage(engine: Any, target: Any, pending: int, source_definition_id: Any, source_actor_id: Any) -> int | None:
    """Both lines' damage answers, applied to the effect they interrupted and to nobody else.

    A bound answer names the creature that used the interrupted feature and either one chosen target or every target, so
    an unrelated packet -- a different creature's own attack, or a different target of another effect -- is never
    discounted.  ``technique_used`` clears what is left when the activation ends.
    """
    from .attack_reduction import remember

    if pending <= 0:
        return None
    reductions = engine.__dict__.get("_a2glass_crack") or []
    for entry in list(reductions):
        if str(entry.get("actor") or "") != str(source_actor_id or ""):
            continue
        wanted = str(entry.get("target") or "")
        if wanted and wanted != target.entity_id:
            continue
        amount = max(0, int(entry.get("amount") or 0))
        if amount <= 0:
            continue
        if wanted:
            reductions.remove(entry)   # one chosen target takes its answer once; "all targets" answers every packet
        return remember(engine, target, pending, max(0, pending - amount), [(amount, ())])
    return None


@hook("zone_created")
def flaw_shorten_zone_created(ctx: Any, zone: Any) -> None:
    """Record a zone the triggering effect just created, so ``crack_activation_end`` can shorten it once committed.

    ``zone_created`` only permits adding ``trigger_profile`` metadata (it fires before the zone's own creation event is
    recorded), so duration is changed later, once the zone is fully committed -- the same two-step a round-counted
    condition gets from ``flaw_shorten_landed`` below.
    """
    pending = ctx.engine.__dict__.get("_a2glass_shorten")
    if not pending or pending["intent"] != ctx.intent.intent_id or zone.source_definition_id != pending["effect"]:
        return
    if zone.zone_id in pending["zones_before"]:
        return
    pending["zone_ids"].add(zone.zone_id)


@hook("technique_used")
def crack_activation_end(ctx: Any) -> None:
    """An activation that has run its effects owes no Crack damage answer to anything after it.

    Flaw's duration-shortening answer also lands here: any zone the triggering effect created this activation
    (``flaw_shorten_zone_created``) is fully committed by the time the activation ends, so its round-counted duration is
    safe to shorten the same way a condition's own expiry is -- one round earlier, never below 1.
    """
    from .retained_updates import record_zone_update

    actor_id = str(getattr(getattr(ctx, "actor", None), "entity_id", "") or "")
    pending = ctx.engine.__dict__.get("_a2glass_shorten")
    if pending and pending["intent"] == ctx.intent.intent_id:
        for zone_id in pending.get("zone_ids") or ():
            zone = ctx.engine.state.zones.get(zone_id)
            if zone is not None and zone.active and zone.duration_rounds and zone.duration_rounds > 1:
                zone.duration_rounds -= 1
                # A bare attribute mutation after ZONE_CREATED has already been recorded would desync a cold replay
                # (the recorded event still carries the original duration); record_zone_update re-records the zone's
                # full, now-shortened snapshot the documented replay-safe way (combat/ext/retained_updates.py).
                record_zone_update(ctx.engine, zone)
        ctx.engine.__dict__["_a2glass_shorten"] = None
    reductions = engine_reductions(ctx.engine)
    if not reductions:
        return
    ctx.engine.__dict__["_a2glass_crack"] = [entry for entry in reductions if str(entry.get("actor") or "") != actor_id]


def engine_reductions(engine: Any) -> list[dict[str, Any]]:
    return list(engine.__dict__.get("_a2glass_crack") or [])


@hook("condition_applied")
def flaw_shorten_landed(ctx: Any, name: str, subject: Any) -> None:
    """Flaw's "reduce the triggering effect's duration by 1 round, minimum 1 round", on the conditions that effect lands.

    Runs once each typed condition has landed.  Only conditions the interrupted effect created (its source, in its
    activation) on creatures it reached are touched, each once, and a round-counted expiry moves one round earlier.  A
    one-round effect is left alone because "minimum 1 round" is printed.
    """
    from .effect_durations import parse_round, round_token
    from .retained_updates import record_instance_update

    pending = ctx.engine.__dict__.get("_a2glass_shorten")
    if not pending or pending["intent"] != ctx.intent.intent_id:
        return
    state = ctx.engine.state
    for instance_id, condition in list(subject.conditions.items()):
        key = (subject.entity_id, instance_id)
        if key in pending["done"] or key in pending["before"] or condition.source_definition_id != pending["effect"]:
            continue
        pending["done"].add(key)
        parsed = parse_round(condition.expires_on)
        if not parsed or parsed[0] - int(state.round_number) <= 1:
            continue
        condition.expires_on = round_token(ctx.engine, parsed[0] - int(state.round_number) - 1)
        # Replay-safe the same way: CONDITION_APPLIED has already been recorded with the original expiry.
        record_instance_update(ctx.engine, subject, "condition", instance_id, condition)


@hook("status_description")
def crack_status(engine: Any, holder: Any, row: Any, data: Any) -> dict[str, str] | None:
    """A newcomer-readable line for every condition this module leaves on a fighter's sheet."""
    readable = {
        FRACTURED: "This fighter's weapon or limb is cracked by clear lines. Its next attack roll with that same weapon or "
                   "limb has Disadvantage, and the crack lasts until the start of the Glass fighter's next turn.",
        CON_DISADV: "This fighter has Disadvantage on the first Constitution saving throw it makes to keep holding "
                    "Concentration.",
        REACTION_DENIED: "This fighter cannot take Reactions until the start of its next turn.",
        AUTO_SAVE: "This fighter automatically succeeds on one saving throw against the interrupted effect.",
        SAVE_ADV: "This fighter has Advantage on one saving throw against the interrupted effect.",
        RESIST_EFFECT: "This fighter takes half damage of one kind (say, Fire) until the end of this turn.",
        FEATURE_LOCKED: "This fighter cannot use that same feature again until the end of its next turn.",
    }
    condition_id = str((row or {}).get("condition_id") or "")
    if condition_id not in readable:
        return None
    return {"text": str((data or {}).get("label") or "") or readable[condition_id],
            "handling": readable[condition_id]}