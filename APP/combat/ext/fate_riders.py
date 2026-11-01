"""Fate lines that were left to the GM (rider lane 9, 2026-09-29; owner: "i want everything we can automated").  Sphere Compendium, Fate

Shared public helper: consumed by fate_insights.py. Its exported functions are
the stable cross-plugin API; private helpers stay private.
(owner's text: authority/typed_mechanics/rules_text.json).  combat/ext/d20_rewrite_fate.py already plays Rewrite the Disaster and Fortune
Reversal, combat/ext/d20_rewrite_auspices.py and d20_floor.py three Auspice Releases; this module adds the rest that combat can run.
Second pass (A2FATESECO): Lone Lantern now grants isolated proficient-skill self-Help as a Bonus Action and a
Reaction Release before an attack, with conditional Advantage for one minute. New Help from another creature
is withheld until the bearer's next turn; previously granted assistance still requires the retained rider.
Turning Wheel's Release is offered before the d20 draw; its passive roll bonus also reaches native saves/attacks,
and its attack-face damage bonus reaches native rolled weapon damage without doubling typed packets.

Rows: feature block "lane9_fate" (combat/rules/feature_blocks.d/riders_lane9.json); typed effects "fate_*" below.

  Fate Die                 d4 (CL 1-4), d6 (5-10), d8 (11-16), d10 (17-20) -- "Fate Die" in the Sphere; Fate-Sovereign Incarnation makes it at
                           least a d10 (condition rule "fate_die_min", read by typed_reactions' Twist of Fate roll and fate_die below).
  Consequence Edict        once per round, a creature inside the aura that damages another creature takes Psychic damage equal to the
                           owner's PB; new typed auras ask for up to PB immune creatures at creation (including nobody).
                           Legacy saved auras retain their original owner/allies default.
  Hallow Mandate Edict    the owner picks a creature category when the aura is created; creatures of that kind have
                           Disadvantage attacking its allies inside, and at CL 10 those allies save with Advantage against being
                           Charmed, Frightened or possessed by them. The menu is the printed list plus the categories the
                           fight's creatures actually carry (the printed "another supernatural category appropriate to the
                           campaign" cannot be named freely, so that part stays the GM's and the row keeps a rider saying so);
                           auras saved before this row existed keep their own behaviour and are never touched, while an aura
                           compiled by the reviewed base is owned here and its leftover blanket save advantage is dropped
                           (see _drop_hallow_blanket).
  Undo Harm Edict          the first time each round a creature inside takes damage it gains Temporary HP (PB; + 5 / 10 / 15 at CL 5 / 11 /
                           17) before the damage; they vanish when it leaves the aura or the Edict ends.
  Purity Edict (CL 10)     the first time each round a creature inside regains HP, it regains PB more.
  Serendipity Edict        once per round, an ally inside adds 1d4 to an attack roll or saving throw (added as the roll is made).
  Court of the Heavenly   once per round an ally inside adds 1d6 to an attack roll, ability check or saving throw (added as the roll is made).
  Ledger
  Red Thread Auspice       + the number of conscious allies within 5 feet to its saving throws, at most your PB.
  Quiet Mandate Edict      a creature inside is Silenced (combat/speech.py: no ability that needs its voice) -- the zone's own "inside" rule.
  Subvert Harm             Reaction, 4 CP: a creature within 60 feet would deal damage (not area damage) to another creature; it makes a
                           Charisma save -- on a failure it takes the damage itself (same type), on a success the damage drops by the Fate Die.
  Violence Word            failed save: on its next turn its Action can only be a weapon attack, Unarmed Strike, natural weapon attack or
                           cost-free damaging technique against the nearest creature (one that is equally near is its pick); it ends when
                           that attack is made or its next turn ends.
  Freedom Word             a Grappled (or escape-save Restrained) target makes one escape attempt at once, without its Action.
  Jinxed Name              failed save: once per round -1d4 on its attack roll, ability check or saving throw, repeating the save at the end
                           of each of its turns; success: -1d4 on its next attack roll or ability check before the start of your next turn.
  Chain of Misfortune      failed save: the first time each round it misses an attack, fails a saving throw or falls Prone, you choose 2d8
                           Psychic, no Reactions (to the start of its next turn), Speed -10 (to the start of its next turn) or an ally's
                           Advantage on its next attack against it (to the start of your next turn); it repeats the save at the end of each
                           of its turns.  Successful save: the next miss or failed save before your next turn costs it its Reactions until
                           the start of its following turn.
  Calamity Finds a Path    two listed effects on a failed save, one on a success (until the start of your next turn): Prone, drops its
                           weapon, no Reactions, Speed 0, AC -2, healing halved.
  Borrowed Lifespan        once per Long Rest per protected creature; then the cost is chosen: 2 x CL Necrotic to you, one Exhaustion
  Talisman                 level on the protected creature, 2 Heaven's Notice, or the repayment oath (it cannot benefit again -- already so).
  Guiding Star Auspice     during the bearer's own turn, typed attacks against it have Disadvantage; Release (its Reaction, as it would
                           provoke an Opportunity Attack): for 1 minute it provokes none.
  Moving Star Auspice      Release (Reaction, even while Incapacitated) as it would gain Incapacitated, Paralyzed, Stunned or Unconscious: it
                           ignores that condition until the end of its next turn.
  Turning Wheel Auspice    1d6 on granting: 1-2 +N attack and damage rolls, 3-4 +N saving throws, 5-6 +N ability checks (N = 1, 2 at CL 11,
                           3 at CL 17); the damage bonus modifies the normal damage roll before defenses.
  Marked by the Ledger     after the marked creature drops to 0 HP, a Bonus Action on a later turn moves the mark to a creature within 60 feet.
  Fate-Sovereign           the Fate Die becomes a d10; at the start of each of your turns one ally within 30 feet gains +1 AC, +1 to saving
  Incarnation              throws, or Advantage on its next attack roll, until the start of your next turn.

  Empress of Hidden Growth  Action (2 CP) or the 10-minute procedure (out of combat). The bearer may release it after its own attack
  Auspice                  roll, ability check, saving throw or reaction contest roll, before the outcome, adding the caster's PB (a player
                           is asked; an AI bearer never releases by default); the Auspice ends. Each creature takes at most the caster's PB
                           grants per fight ("per Long Rest": a fight is the rest here), counted on the caster and withheld by candidate_allowed.
                           Explicit rolled-skill Expertise blocks Release. Unknown legacy ranks/other second-PB effects remain GM judged.

Judgment calls: "once per round" on an Edict is per aura (Consequence) or per creature where the text says "a creature ... the first time"
(Undo Harm, Purity); the AI picks for the Fate caster where a choice is printed (needle.ask: a player is asked); Chain of Misfortune's
new typed Chain rows also use actual failed ability-check receipts, including the defender's opposed check;
hazard damage still needs explicit provenance. A longer effect Moving Star
ignored is not re-applied after its turn; Violence Word leaves Bonus Actions and movement free.
"""

from __future__ import annotations

from ..paid_relocation import activation

from typing import Any

from . import effect, hook, note
from .needle import CHOICE, ask, checkpoint_id

BLOCK = "lane9_fate"
T = "TAL_FATE_"
CONSEQUENCE, UNDO, PURITY, SERENDIPITY = T + "CONSEQUENCE_EDICT", T + "UNDO_HARM_EDICT", T + "PURITY_EDICT", T + "SERENDIPITY_EDICT"
COURT, RED_THREAD = T + "COURT_OF_THE_HEAVENLY_LEDGER", T + "RED_THREAD_AUSPICE"
HALLOW = T + "HALLOW_MANDATE_EDICT"
# The printed category list ("Choose aberrations, celestials, elementals, fey, fiends, undead, demons,
# ghosts, or another supernatural category appropriate to the campaign"). creature_kinds normalises the
# plurals; nothing is inferred from a name, so an unlabelled creature is never affected.
HALLOW_KINDS = ("aberrations", "celestials", "elementals", "fey", "fiends", "undead", "demons", "ghosts")
HALLOW_SAVE_NAMES = frozenset({"charmed", "frightened", "possessed"})
SUBVERT, VIOLENCE_ID, FREEDOM, JINX_ID = T + "SUBVERT_HARM", T + "VIOLENCE_WORD", T + "FREEDOM_WORD", T + "JINXED_NAME"
CHAIN_ID, CALAMITY, BORROWED = T + "CHAIN_OF_MISFORTUNE", T + "CALAMITY_FINDS_A_PATH", T + "BORROWED_LIFESPAN_TALISMAN"
LEDGER, SOVEREIGN_ID, WHEEL_ID = T + "MARKED_BY_THE_LEDGER", T + "FATE_SOVEREIGN_INCARNATION", T + "TURNING_WHEEL_AUSPICE"
C = "condition:typed."
SAVE_AGAINST_C = "condition:typed.save_against"
VIOLENCE, JINX, JINX_ONCE, CHAIN, CHAIN_WARN = C + "violence_word", C + "jinxed_name", C + "jinxed_once", C + "chain_of_misfortune", C + "chain_warning"
AUSPICE, GUIDING_FREE, MOVING_IGNORE, WHEEL = C + "fate_auspice", C + "guiding_star_free", C + "moving_star_ignore", C + "turning_wheel"
SOVEREIGN, BOON, CALAMITY_C, CHAIN_OPENING = C + "fate_sovereign", C + "sovereign_boon", C + "calamity", C + "chain_opening"
MOVING_NAMES = ("incapacitated", "paralyzed", "stunned", "unconscious")


# ------------------------------------------------------------------------------------------------ rows and helpers
@hook("compile_block")
def compile_rows(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block != BLOCK:
        return None
    return [{**row, "block": BLOCK, "kind": spec.get("kind"), "pb": int(numbers.get("pb") or 2), "cl": int(numbers.get("cl") or 1),
             "keeps_compiling": bool(spec.get("keeps_compiling"))}]


def rows(engine: Any, actor: Any, kind: str) -> list[dict[str, Any]]:
    return [row for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, [])
            if row.get("block") == BLOCK and row.get("kind") == kind]


def _held(actor: Any, condition_id: str) -> list[Any]:
    return [c for c in actor.conditions.values() if c.condition_id == condition_id]


def _feature(engine: Any, source: Any) -> str:
    action = engine.action_catalog.get(str(source or ""))
    return str((((action.parameters or {}).get("typed") or {}).get("source") or "")) if action is not None else ""


def _zones(engine: Any, feature: str) -> list[Any]:
    from .. import zones

    return [zone for zone in zones.typed_zones(engine) if zone.active and _feature(engine, zone.source_definition_id) == feature]


def _inside(engine: Any, actor: Any, zone: Any) -> bool:
    from .. import zones

    return actor.active and zones.actor_inside_zone(engine, actor, zone)


def _numbers(zone: Any) -> dict[str, Any]:
    return dict(zone.trigger_profile.get("numbers") or {})


def _once_a_round(engine: Any, key: Any, *, consume: bool = True) -> bool:
    """Persist fight-wide, exact-instance use marks on a saved roster carrier.

    _round_ flags survive turn resets, table reloads and preview clones. Keys
    include the zone/curse instance, so replacement effects get their own limit.
    """
    import json

    key = "_round_fate_use:" + json.dumps(key, separators=(",", ":"))
    # Reuse the original carrier if the roster grows (summons may sort before
    # it). Defeated actors remain in saved fight state, so they retain limits.
    carrier = next((a for a in engine.state.actors.values() if key in a.turn_flags),
                   engine.state.actors[sorted(engine.state.actors)[0]])
    seen = carrier.turn_flags
    if seen.get(key) == engine.state.round_number:
        return False
    if consume:
        seen[key] = engine.state.round_number
    return True


def _roll(engine: Any, actor: Any, sides: int, reason: str, count: int = 1) -> int:
    from ..gate2_runtime_models import DiceSpec

    roll = engine.roller.roll(DiceSpec(count=count, sides=sides, modifier=0), actor_id=actor.entity_id, reason=reason)
    engine._record_roll(roll)
    return int(roll.total)


def fate_die(engine: Any, actor: Any, cl: int) -> int:
    """The Fate Die's size for this creature: by CL, at least any fate_die_min its conditions give (Fate-Sovereign Incarnation)."""
    from ..typed_executor import condition_rules

    sides = 4 if cl <= 4 else 6 if cl <= 10 else 8 if cl <= 16 else 10
    return max([sides, *(int(rule["fate_die_min"]) for rule in condition_rules(actor) if rule.get("fate_die_min"))])


def _cp(actor: Any) -> str | None:
    from .d20_rewrite import pool_id

    return pool_id(actor, "cp")


def _dc(engine: Any, actor: Any) -> int:
    """The creature's technique save DC (its typed actions carry it in their numbers)."""
    for action in engine.action_catalog.values():
        if action.owner_id == actor.entity_id:
            numbers = ((action.parameters or {}).get("typed") or {}).get("numbers") or {}
            if numbers.get("save_dc"):
                return int(numbers["save_dc"])
    return 10


def _subjects(ctx: Any, eff: dict[str, Any]) -> list[Any]:
    """Who a helpful effect lands on; an Ally-or-self ability aimed at its user reaches the context with no target, so the user is it."""
    from .. import typed_executor

    # Honor the accepted single self target before an ally effect's fallback
    # gathers nearby creatures. Their presence must not redirect the Auspice.
    if ctx.intent is not None and tuple(getattr(ctx.intent, "target_ids", ()) or ()) == (ctx.actor.entity_id,):
        return [ctx.actor]
    return [s for s in typed_executor.default_subjects(ctx, eff, harmful=False) if s is not None]


def _token(edge: str, actor: Any, turns_ahead: int = 1) -> str:
    from .effect_durations import token

    return token(edge, actor.entity_id, int(actor.turns_started) + turns_ahead)


def _ctx(engine: Any, actor: Any, other: Any, feature: str, name: str) -> Any:
    from .. import typed_reactions

    return typed_reactions.generic_reaction_context(engine, actor, other, {"feature_id": feature, "name": name, "effects": [], "numbers": {}})


# ------------------------------------------------------------------------------------------------ Edicts
def _designated(engine: Any, zone: Any) -> set[str]:
    """New auras retain the owner's selection; legacy auras keep their default."""
    if "fate_designated" in zone.trigger_profile:
        return set(zone.trigger_profile["fate_designated"])
    owner = engine.state.actors.get(zone.owner_id)
    if owner is None:
        return set()
    allies = sorted((a.entity_id for a in engine.state.actors.values() if a.team_id == owner.team_id and a is not owner))
    return set([owner.entity_id, *allies][:int(_numbers(zone).get("pb") or 2)])


def _choose_designated(engine: Any, payload: dict[str, Any]) -> None:
    zone = engine.state.zones.get((payload.get("zone") or {}).get("zone_id"))
    if zone is None or "fate_designated" in zone.trigger_profile or _feature(engine, zone.source_definition_id) != CONSEQUENCE:
        return
    action = engine.action_catalog.get(zone.source_definition_id)
    typed = action.parameters.get("typed") or {}
    if not any(eff.get("immunity_choice") for eff in typed.get("effects") or [] if eff.get("type") == "zone"):
        return
    owner = engine.state.actors.get(zone.owner_id)
    if owner is None:
        return
    options = sorted(a.entity_id for a in engine.state.actors.values() if a.active)
    allies = [owner.entity_id, *[aid for aid in options if aid != owner.entity_id and
                                engine.state.actors[aid].team_id == owner.team_id]]
    cap = int(_numbers(zone).get("pb") or 2)
    from .. import stealth
    automatic_allies = [aid for aid in allies if aid == owner.entity_id or stealth.sees(engine, owner, engine.state.actors[aid])]
    selected = ask(engine, getattr(engine, "_active_intent", None),
        checkpoint_id(engine, "CONSEQUENCE_IMMUNITY", owner.entity_id, zone.zone_id),
        owner, CHOICE + "consequence_immunity", options,
        labels={aid: engine.state.actors[aid].display_name for aid in options},
        preferred=allies[:cap], automatic_options=automatic_allies, minimum=0, maximum=cap, allow_decline=True, default_count=min(cap, len(allies)),
        prompt=f"Consequence Edict: {owner.display_name} creates the aura; exempt up to {cap} creatures from its Psychic damage, or decline to exempt nobody",
        name="Consequence Edict: choose immune creatures", feature_id=CONSEQUENCE)
    zone.trigger_profile["fate_designated"] = selected
    # The native reducer restores full zone snapshots. Re-record this same
    # instance after selection, as other zone-profile consumers do; the stored
    # key above prevents the creation observer from asking again.
    engine._append_event("ZONE_CREATED", zone.source_definition_id, actor_id=zone.owner_id,
                         payload={"zone": zone.model_dump(mode="json")})
    names = ", ".join(engine.state.actors[aid].display_name for aid in selected) or "nobody"
    note(engine, CONSEQUENCE, owner, f"Consequence Edict exempts {names} while this aura lasts.")


def _hallow_kind(zone: Any) -> str:
    """The creature category this Hallow aura was created for ("" until the owner chooses).

    Legacy auras (compiled before this row asked for one) have no such key at all and are left
    exactly as they were; see :func:`_hallow_owned`.
    """
    return str((zone.trigger_profile or {}).get("fate_hallow_kind") or "")


def _hallow_owned(engine: Any, zone: Any) -> bool:
    """Whether this aura is a Hallow row the plug-in owns: the owner's compiled row carries ``kind_choice``.

    The typed core cannot express "of the chosen kind", so auras whose compiled row still asks for
    one are handled here (a source-qualified implementation only), while a saved fight from before
    this row kept its own behaviour and is never touched.
    """
    if "fate_hallow_kind" in (zone.trigger_profile or {}):
        return True
    action = engine.action_catalog.get(str(zone.source_definition_id or ""))
    typed = ((action.parameters if action is not None else None) or {}).get("typed") or {}
    return _feature(engine, zone.source_definition_id) == HALLOW and any(
        eff.get("kind_choice") for eff in typed.get("effects") or [] if eff.get("type") == "zone")


def _campaign_kinds(engine: Any) -> list[str]:
    """"Another supernatural category appropriate to the campaign": the printed categories this fight's creatures carry.

    Read from the same persisted creature labels :mod:`creature_kinds` matches on, so a category is only
    offered when a creature in the fight actually has it -- the table names the kind, nothing is inferred.
    """
    from . import creature_kinds

    listed = {creature_kinds.normalize(kind) for kind in HALLOW_KINDS}
    return sorted({label for actor in engine.state.actors.values() if actor.active
                   for label in creature_kinds.labels(actor)} - listed)


def _choose_hallow_kind(engine: Any, payload: dict[str, Any]) -> None:
    """Hallow Mandate: the owner picks the printed creature category the aura judges.

    Stored on the aura's trigger_profile as a plain string so it survives a table commit and reload.
    A declined or unanswered choice judges no kind (nothing is guessed from names). A saved aura from
    before this row existed carries no marker and is never asked about or altered.
    """
    zone = engine.state.zones.get((payload.get("zone") or {}).get("zone_id"))
    if zone is None or "fate_hallow_kind" in (zone.trigger_profile or {}) or not _hallow_owned(engine, zone):
        return
    owner = engine.state.actors.get(zone.owner_id)
    if owner is None:
        return
    kinds = list(HALLOW_KINDS)
    labels = {k: k.capitalize() for k in kinds}
    campaign = _campaign_kinds(engine)
    for extra in campaign:
        kinds.append(extra)
        labels[extra] = extra.capitalize()
    prompt = (f"Hallow Mandate Edict: {owner.display_name} creates the aura; choose which kind of creature it judges "
              f"(their attacks against your allies inside the aura have Disadvantage)")
    if campaign:
        prompt += (f". Also offered: another kind of creature this fight uses -- "
                   f"{', '.join(labels[k] for k in campaign)}")
    chosen = ask(engine, getattr(engine, "_active_intent", None),
                 checkpoint_id(engine, "HALLOW_KIND", owner.entity_id, zone.zone_id),
                 owner, CHOICE + "hallow_kind", kinds,
                 labels=labels, preferred=["undead"],
                 allow_decline=True, name="Hallow Mandate Edict: choose the creature category",
                 prompt=prompt,
                 feature_id=HALLOW)
    kind = str((chosen or [""])[0])
    zone.trigger_profile["fate_hallow_kind"] = kind
    # The native reducer restores full zone snapshots; re-record this same instance after the choice,
    # as the Consequence selection does. The stored key stops the creation observer asking again.
    engine._append_event("ZONE_CREATED", zone.source_definition_id, actor_id=zone.owner_id,
                         payload={"zone": zone.model_dump(mode="json")})
    shown = (labels.get(kind) or kind) if kind else ""
    note(engine, HALLOW, owner, (f"Hallow Mandate Edict judges {shown} creatures while this aura lasts." if kind
                                 else "Hallow Mandate Edict judges no creature category while this aura lasts."))


def _hallow_judged(engine: Any, zone: Any, subject: Any) -> bool:
    """Whether this Hallow aura currently judges `subject` (a creature of the chosen category)."""
    from . import creature_kinds

    kind = _hallow_kind(zone)
    return bool(kind) and creature_kinds.matches(subject, kind)


def _hallow_cl(engine: Any, zone: Any) -> int:
    """The casting CL of a Hallow aura, read from the owner's compiled Hallow action."""
    for action in engine.action_catalog.values():
        if action.owner_id != zone.owner_id or _feature(engine, action.source_definition_id) != HALLOW:
            continue
        return int((((action.parameters or {}).get("typed") or {}).get("numbers") or {}).get("cl") or 1)
    return 1


def _hallow_ally_inside(engine: Any, zone: Any, subject: Any) -> bool:
    """Whether `subject` is an ally of the aura's owner and stands inside the aura."""
    owner = engine.state.actors.get(zone.owner_id)
    if owner is None or subject.team_id != owner.team_id:
        return False
    return _inside(engine, subject, zone)


@hook("attack_mode")
def hallow_attack_mode(ctx: Any, target: Any) -> str | None:
    """Hallow Mandate: "Creatures of the chosen kind have Disadvantage on attack rolls against your allies inside the aura"."""
    for zone in _zones(ctx.engine, HALLOW):
        if _hallow_owned(ctx.engine, zone) and _hallow_judged(ctx.engine, zone, ctx.actor) \
                and _hallow_ally_inside(ctx.engine, zone, target):
            return "DISADVANTAGE"
    return None


def _hallow_save_advantage(ctx: Any, subject: Any, named: Any) -> list[str]:
    """At CL 10, allies inside a Hallow aura roll with Advantage against being Charmed, Frightened or possessed BY the judged kind.

    The single implementation of that printed clause: the typed core carries the aura only, because it cannot
    say "of the chosen kind", and the source-qualified mode comes from here. An aura compiled by the reviewed
    base (AUTO112) could only say it as one aura-wide blanket condition, and that aura also stored its chosen
    category -- so this plug-in owns it (:func:`_hallow_owned`) and the leftover blanket is dropped rather than
    left to keep granting Advantage against every creature (:func:`_drop_hallow_blanket`). An aura saved before
    the row existed was never owned and keeps its own behaviour.
    """
    if not (set(named or ()) & HALLOW_SAVE_NAMES):
        return []
    modes: list[str] = []
    for zone in _zones(ctx.engine, HALLOW):
        if not _hallow_owned(ctx.engine, zone):
            continue
        # Base-compiled blankets persist after movement. Retire this owned source's blanket even
        # outside the aura; spatial eligibility applies only to the replacement benefit below.
        _drop_hallow_blanket(ctx.engine, zone, subject)
        if _hallow_ally_inside(ctx.engine, zone, subject) and _hallow_cl(ctx.engine, zone) >= 10 \
                and _hallow_judged(ctx.engine, zone, ctx.actor):
            modes.append("ADVANTAGE")
    return modes


def _drop_hallow_blanket(engine: Any, zone: Any, subject: Any) -> None:
    """Remove the blanket save-advantage this aura's own compiled row left on an ally, and nothing else.

    Scoped to the aura's own source definition, so another ability's save advantage on the same ally is never
    touched, and to auras this plug-in owns, so a saved aura from before the row existed keeps its behaviour.
    The removal is a recorded CONDITION_REMOVED event like any other, so a table replay of an upgraded fight
    stays exact.
    """
    for held in list(_held(subject, SAVE_AGAINST_C)):
        if held.source_definition_id != zone.source_definition_id:
            continue  # another ability's save advantage is independent
        del subject.conditions[held.instance_id]
        engine._append_event("CONDITION_REMOVED", zone.source_definition_id, actor_id=zone.owner_id,
                             target_ids=(subject.entity_id,),
                             payload={"condition_id": held.condition_id, "instance_id": held.instance_id,
                                      "reason": "HALLOW_SOURCE_QUALIFIED"})


def _consequence(engine: Any, damager_id: Any, target_ids: Any, payload: dict[str, Any]) -> None:
    damager = engine.state.actors.get(str(damager_id or ""))
    if damager is None or not damager.active or int(payload.get("reduced_to") or 0) <= 0:
        return
    if not any(t != damager.entity_id for t in target_ids or ()):
        return  # "damages another creature"
    for zone in _zones(engine, CONSEQUENCE):
        if not _inside(engine, damager, zone) or damager.entity_id in _designated(engine, zone):
            continue
        if not _once_a_round(engine, ("consequence", zone.zone_id)):
            continue
        pb = int(_numbers(zone).get("pb") or 2)
        note(engine, CONSEQUENCE, damager, f"Consequence Edict: {damager.display_name} takes {pb} Psychic damage for the harm it dealt.")
        engine._commit_damage(damager, pb, "PSYCHIC", CONSEQUENCE, zone.owner_id, None, reaction_depth=1)


@hook("damage_pending")
def undo_harm(engine: Any, target: Any, pending: int, source_definition_id: Any, source_actor_id: Any) -> int | None:
    if pending <= 0:
        return None
    for zone in _zones(engine, UNDO):
        if not _inside(engine, target, zone) or not _once_a_round(engine, ("undo", zone.zone_id, target.entity_id)):
            continue
        numbers = _numbers(zone)
        cl = int(numbers.get("cl") or 1)
        amount = int(numbers.get("pb") or 2) + (15 if cl >= 17 else 10 if cl >= 11 else 5 if cl >= 5 else 0)
        before = int(target.temporary_hp)
        engine._grant_temp_hp(target, amount, UNDO, zone.owner_id)
        if amount > before:
            engine._apply_condition(target, C + "undo_hp", UNDO, zone.owner_id,
                                    expires_on="UNTIL_REMOVED", data={"zone": zone.zone_id, "amount": amount})
        break
    return None


def _undo_vanish(engine: Any) -> None:
    """"These Temporary HP vanish when the creature leaves the aura or the Edict ends.\""""
    for target in engine.state.actors.values():
        for held in list(_held(target, C + "undo_hp")):
            zone = engine.state.zones.get(str(held.data["zone"]))
            if zone is not None and zone.active and _inside(engine, target, zone):
                continue
            _forget_undo(engine, target, held)
            lost = min(int(target.temporary_hp), int(held.data["amount"]))
            before = int(target.temporary_hp)
            target.temporary_hp -= lost
            # The existing HP ledger event carries exact before/after values;
            # runtime-control snapshots do not include Temporary HP.
            engine._append_event("TEMP_HP_GRANTED", UNDO, actor_id=held.source_actor_id,
                                 target_ids=(target.entity_id,), payload={"offered": 0, "before": before,
                                 "after": int(target.temporary_hp), "reason": "UNDO_GRANT_ENDED"})
            note(engine, UNDO, target, f"Undo Harm Edict: {target.display_name}'s {lost} Temporary HP vanish.")


def _forget_undo(engine: Any, target: Any, held: Any) -> None:
    """Remove only this grant's obligation; another aura/grant is independent."""
    del target.conditions[held.instance_id]
    engine._append_event("CONDITION_REMOVED", UNDO, actor_id=held.source_actor_id,
                         target_ids=(target.entity_id,), payload={"condition_id": held.condition_id,
                         "instance_id": held.instance_id, "reason": "GRANT_ENDED"})


def _purity(engine: Any, target_ids: Any, payload: dict[str, Any]) -> None:
    if int(payload.get("after") or 0) <= int(payload.get("before") or 0) or engine.__dict__.get("_fate_in_purity"):
        return
    for target_id in target_ids or ():
        subject = engine.state.actors.get(target_id)
        if subject is None:
            continue
        for zone in _zones(engine, PURITY):
            numbers = _numbers(zone)
            if int(numbers.get("cl") or 1) < 10 or not _inside(engine, subject, zone):
                continue
            if not _once_a_round(engine, ("purity", zone.zone_id, subject.entity_id)):
                continue
            engine.__dict__["_fate_in_purity"] = True
            try:
                from .healing_policy import ordinary_preparation
                if ordinary_preparation(engine, subject):
                    from .life_state import heal_to
                    heal_to(engine, subject, int(numbers.get("pb") or 2), PURITY, zone.owner_id)
                else:
                    before = subject.current_hp
                    subject.current_hp = min(subject.maximum_hp, before + int(numbers.get("pb") or 2))
                    engine._append_event("HEALING_APPLIED", PURITY, actor_id=zone.owner_id, target_ids=(subject.entity_id,),
                                         payload={"offered": int(numbers.get("pb") or 2), "before": before, "after": subject.current_hp})
            finally:
                engine.__dict__["_fate_in_purity"] = False
            break


def _court(engine: Any, actor: Any, ctx: Any = None) -> int:
    """Court of the Heavenly Ledger: "Once per round, when an ally inside the Domain makes an attack roll, ability check, or saving throw, you
    may roll 1d6 and add it to the roll" (added as the roll is made)."""
    for zone in _zones(engine, COURT):
        owner = engine.state.actors.get(zone.owner_id)
        if owner is None or owner.team_id != actor.team_id or not _inside(engine, actor, zone):
            continue
        key = ("court", zone.zone_id)
        if _once_a_round(engine, key, consume=False):
            trigger = getattr(getattr(ctx, "action", None), "display_name", "roll")
            picked = ask(engine, getattr(ctx, "intent", None) or getattr(engine, "_active_intent", None),
                         checkpoint_id(engine, "COURT_BONUS", zone.zone_id, actor.entity_id), owner,
                         CHOICE + "court_bonus", ["add"], labels={"add": "Add 1d6 (once per round)"},
                         allow_decline=True, target_id=actor.entity_id,
                         prompt=f"Court of the Heavenly Ledger: add 1d6 to {actor.display_name}'s {trigger} before the outcome is known? Once per round; no additional CP cost.")
            if not picked:
                continue
            _once_a_round(engine, key)
            bonus = _roll(engine, owner, 6, "HEAVENLY_LEDGER")
            note(engine, COURT, actor, f"Court of the Heavenly Ledger: {actor.display_name} adds {bonus} (1d6) to the roll.")
            return bonus
    return 0


def _empress_release(engine: Any, actor: Any, ctx: Any, roll_id: str, roll: Any = None) -> int:
    """Empress of Hidden Growth Auspice, Release: "The target releases this Auspice after rolling but before the outcome is known,
    adding your Proficiency Bonus to the roll." "Your" is the caster's: the stored PB is the caster's, not the bearer's. The
    bearer may release it on its own attack roll, ability check, saving throw or reaction contest roll (a player is asked; an AI
    bearer releases only when the choice is answered, never by default). The Auspice ends with it."""
    from .d20_floor import end_auspice

    held = _auspice(actor, "empress")
    if held is None:
        return 0
    from ..ability_checks import roll_skill_proficiency

    if roll is not None and roll_skill_proficiency(engine, actor, roll) == 2:
        return 0
    pb = int((held.data or {}).get("pb") or 2)
    trigger = getattr(getattr(ctx, "action", None), "display_name", "roll")
    picked = ask(engine, getattr(ctx, "intent", None) or getattr(engine, "_active_intent", None),
                 checkpoint_id(engine, "EMPRESS_RELEASE", roll_id, actor.entity_id), actor,
                 CHOICE + "empress_release", ["release"], labels={"release": f"Release: add the caster's Proficiency Bonus (+{pb})"},
                 allow_decline=True, target_id=actor.entity_id, default="decline",
                 prompt=f"Empress of Hidden Growth Auspice: add the caster's Proficiency Bonus (+{pb}) to {actor.display_name}'s {trigger} "
                        f"before the outcome is known? No action or Reaction cost; releasing ends the Auspice. "
                        f"If another effect already adds Proficiency Bonus a second time, you cannot add this bonus; ask the GM if unsure.")
    if not picked:
        return 0
    end_auspice(engine, actor, held, "RELEASED")
    note(engine, held.source_definition_id, actor, f"Empress of Hidden Growth Auspice: {actor.display_name} releases it and adds the caster's Proficiency Bonus (+{pb}) to the roll.")
    return pb


def _red_thread(engine: Any, subject: Any) -> int:
    """Red Thread Auspice: "a bonus to saving throws equal to the number of conscious allies within 5 feet of it, maximum your PB." """
    held = _auspice(subject, "red_thread")
    if held is None:
        return 0
    pb = int((held.data or {}).get("pb") or 2)
    near = sum(1 for a in engine.state.actors.values() if a.active and a is not subject and a.team_id == subject.team_id
               and a.current_hp > 0 and engine._distance_actor_to_actor(a, subject) <= 5)
    return min(near, pb)


def _serendipity(engine: Any, actor: Any, ctx: Any = None) -> int:
    for zone in _zones(engine, SERENDIPITY):
        owner = engine.state.actors.get(zone.owner_id)
        if owner is None or owner.team_id != actor.team_id or not _inside(engine, actor, zone):
            continue
        key = ("serendipity", zone.zone_id)
        if _once_a_round(engine, key, consume=False):
            trigger = getattr(getattr(ctx, "action", None), "display_name", "roll")
            picked = ask(engine, getattr(ctx, "intent", None) or getattr(engine, "_active_intent", None),
                         checkpoint_id(engine, "SERENDIPITY", zone.zone_id, actor.entity_id), actor,
                         CHOICE + "serendipity", ["add"], labels={"add": "Add 1d4 (once per round)"},
                         allow_decline=True, target_id=actor.entity_id,
                         prompt=f"Serendipity Edict: add 1d4 to {actor.display_name}'s {trigger} before the outcome is known? Once per round; no additional CP cost.")
            if not picked:
                continue
            _once_a_round(engine, key)
            bonus = _roll(engine, actor, 4, "SERENDIPITY_EDICT")
            note(engine, SERENDIPITY, actor, f"Serendipity Edict: {actor.display_name} adds {bonus} (1d4) to the roll.")
            return bonus
    return 0


# ------------------------------------------------------------------------------------------------ Subvert Harm
@hook("incoming_damage")
def subvert_harm(engine: Any, target: Any, amount: int, damage_type: str, source_definition_id: str, source_actor_id: str | None) -> int | None:
    from .. import typed_reactions

    attacker = engine.state.actors.get(source_actor_id or "")
    if attacker is None or attacker is target or amount <= 0 or not attacker.active or str(source_definition_id).startswith(T):
        return None
    action = engine.action_catalog.get(str(source_definition_id))
    typed = ((action.parameters or {}).get("typed") or {}) if action is not None else {}
    if action is None or typed.get("area") or str(getattr(action, "target_kind", "")).upper().endswith("AREA"):
        return None  # "This cannot affect area damage, reflected damage, environmental damage"
    for reactor in list(engine.state.actors.values()):
        found = rows(engine, reactor, "subvert") if reactor.active else []
        if not found or reactor.team_id == attacker.team_id or engine._distance_actor_to_actor(reactor, attacker) > 60:
            continue
        cp = _cp(reactor)
        if cp is None or reactor.resources.get(cp, 0) < 4 or not typed_reactions.can_react(engine, reactor):
            continue
        heavy = amount >= 8 or amount >= target.current_hp + target.temporary_hp
        picked = ask(engine, getattr(engine, "_active_intent", None), checkpoint_id(engine, "SUBVERT_HARM", reactor.entity_id, attacker.entity_id), reactor,
                     CHOICE + "subvert_harm", ["use"], labels={"use": f"Subvert Harm (Reaction, 4 CP): {attacker.display_name} deals the {amount} to itself"},
                     allow_decline=True, target_id=attacker.entity_id, default="first" if heavy else "decline",
                     prompt=f"{attacker.display_name} would deal {amount} {damage_type} damage to {target.display_name}: Subvert Harm?")
        if not picked:
            continue
        with activation(engine, reactor, SUBVERT):
            engine._spend_resource(reactor, cp, 4, SUBVERT)
            reactor.reaction_available = False
            engine._append_event("REACTION_WINDOW_OPENED", SUBVERT, actor_id=reactor.entity_id, target_ids=(attacker.entity_id, target.entity_id),
                                 payload={"checkpoint": "DAMAGE_PENDING"})
            dc = _dc(engine, reactor)
            roll = engine._roll_save(attacker, "CHA", dc, SUBVERT)
            if roll is not None and int(roll.total) < dc:
                note(engine, SUBVERT, reactor, f"Subvert Harm: {attacker.display_name} deals the {amount} {damage_type} damage to itself.")
                engine._commit_damage(attacker, amount, damage_type, SUBVERT, attacker.entity_id, None, reaction_depth=2)
                return amount
            cut = _roll(engine, reactor, fate_die(engine, reactor, int(found[0]["cl"])), "FATE_DIE")
            note(engine, SUBVERT, reactor, f"Subvert Harm: {attacker.display_name} resists; the damage drops by {cut} (Fate Die).")
            return min(amount, cut)
    return None


# ------------------------------------------------------------------------------------------------ Words
@effect("fate_violence")
def violence_word(ctx: Any, eff: dict[str, Any]) -> None:
    for subject in ctx.targets or []:
        if subject is not None and subject.active:
            ctx.engine._apply_condition(subject, VIOLENCE, ctx.source, ctx.actor.entity_id, expires_on="END_OF_HOLDER_NEXT_TURN",
                                        data={"label": "Violence Word: on its next turn its Action must be an attack against the nearest creature"})


def _nearest(engine: Any, actor: Any) -> set[str]:
    others = [a for a in engine.state.actors.values() if a.active and a is not actor]
    if not others:
        return set()
    near = min(engine._distance_actor_to_actor(actor, other) for other in others)
    return {a.entity_id for a in others if engine._distance_actor_to_actor(actor, a) == near}


def _forced_attack(action: Any) -> bool:
    """A weapon attack, Unarmed Strike, natural weapon attack or damaging cantrip (a cost-free damaging technique)."""
    from ..typed_executor import _walk_rows

    typed = (action.parameters or {}).get("typed") or {}
    attacks = [row for row in _walk_rows(typed.get("effects")) if isinstance(row, dict) and row.get("type") == "attack"]
    if not attacks:
        return False
    kinds = {str(row.get("attack_kind") or "") for row in attacks}
    return bool(kinds & {"weapon", "unarmed", "melee", "natural"}) or not tuple(getattr(action, "costs", ()) or ())


@hook("candidate_allowed")
def violence_candidates(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    from ..gate2_runtime_models import EconomyKind

    if action is None or not _held(actor, VIOLENCE) or engine.state.current_actor_id != actor.entity_id:
        return None
    if getattr(action, "economy", None) != EconomyKind.ACTION:
        return None  # Bonus Actions and movement stay free
    return _forced_attack(action) and bool(set(getattr(candidate, "target_ids", ()) or ()) & _nearest(engine, actor)) and len(candidate.target_ids) == 1


@hook("technique_used")
def fate_used(ctx: Any) -> None:
    source = str(ctx.typed.get("source") or "")
    engine = ctx.engine
    if _held(ctx.actor, VIOLENCE) and any(str(row.get("type")) == "attack" for row in (ctx.typed.get("effects") or []) if isinstance(row, dict)):
        engine._remove_condition(ctx.actor, VIOLENCE, VIOLENCE_ID)  # the forced attack is made
    if source == FREEDOM:
        _freedom(ctx)
    elif source == SOVEREIGN_ID:
        engine._apply_condition(ctx.actor, SOVEREIGN, SOVEREIGN_ID, ctx.actor.entity_id, expires_on=ctx.expires_on() or "UNTIL_REMOVED",
                                data={"rule": {"fate_die_min": 10}, "label": "Fate-Sovereign Incarnation: Fate Die d10; an ally's boon each turn"})


def _freedom(ctx: Any) -> None:
    from .. import typed_executor

    aimed = [t for t in ctx.targets or [] if t is not None]
    if not aimed and ctx.intent is not None and ctx.actor.entity_id in (getattr(ctx.intent, "target_ids", ()) or ()):
        aimed = [ctx.actor]  # aimed at its user: the context carries no target
    for target in aimed:
        if not target.active:
            continue
        grips = [c for c in target.conditions.values() if (c.data or {}).get("escape_dc") is not None or (c.data or {}).get("escape_save")]
        if not grips:
            continue
        note(ctx.engine, FREEDOM, target, f"Freedom Word: {target.display_name} makes an escape attempt without its Action.")
        typed_executor.block_escape_grapple(_ctx(ctx.engine, target, None, FREEDOM, "Freedom Word"), {"type": "escape_grapple"})


# ------------------------------------------------------------------------------------------------ Jinxed Name
@effect("fate_jinx")
def jinxed_name(ctx: Any, eff: dict[str, Any]) -> None:
    from .. import typed_executor

    dc = int(ctx.numbers.get("save_dc") or 10)
    for subject in ctx.targets or []:
        if subject is None or not subject.active:
            continue
        if eff.get("once"):
            ctx.engine._apply_condition(subject, JINX_ONCE, ctx.source, ctx.actor.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN",
                                        data={"label": "Jinxed Name: -1d4 on its next attack roll or ability check"})
        else:
            ctx.engine._apply_condition(subject, JINX, ctx.source, ctx.actor.entity_id,
                                        expires_on=typed_executor.effect_expiry(ctx, eff, subject, condition=True) or "UNTIL_REMOVED",
                                        data={"repeat_save": {"ability": "CHA", "dc": dc, "when": "end"},
                                              "label": "Jinxed Name: once a round -1d4 on an attack roll, ability check or saving throw"})


def _jinx(engine: Any, actor: Any, roll: str) -> int:
    if _held(actor, JINX) and _once_a_round(engine, ("jinx", actor.entity_id)):
        cut = _roll(engine, actor, 4, "JINXED_NAME")
        note(engine, JINX_ID, actor, f"Jinxed Name: {actor.display_name} subtracts {cut} (1d4) from the {roll}.")
        return -cut
    if roll != "saving throw" and _held(actor, JINX_ONCE):
        engine._remove_condition(actor, JINX_ONCE, JINX_ID)
        cut = _roll(engine, actor, 4, "JINXED_NAME")
        note(engine, JINX_ID, actor, f"Jinxed Name: {actor.display_name} subtracts {cut} (1d4) from the {roll}.")
        return -cut
    return 0


# ------------------------------------------------------------------------------------------------ roll hooks (Jinx, Serendipity, Wheel, boon)
def _wheel(actor: Any, kind: str) -> int:
    return sum(int((c.data or {}).get("bonus") or 0) for c in _held(actor, WHEEL) if (c.data or {}).get("kind") == kind)


@hook("attack_bonus")
def fate_attack_bonus(ctx: Any, actor: Any) -> int | None:
    total = _jinx(ctx.engine, actor, "attack roll")
    return total or None


@hook("check_bonus")
def fate_check_bonus(ctx: Any, actor: Any) -> int | None:
    total = _jinx(ctx.engine, actor, "ability check")
    return total or None


@hook("save")
def fate_save(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    total = _jinx(ctx.engine, subject, "saving throw")
    total += _red_thread(ctx.engine, subject)
    total += sum(1 for c in _held(subject, BOON) if (c.data or {}).get("boon") == "save")
    modes = _hallow_save_advantage(ctx, subject, named)
    if not total and not modes:
        return None
    return {"bonus": total, "modes": modes}


@hook("d20_bonus")
def optional_fate_bonus(engine: Any, roll: Any, intent: Any) -> dict[str, Any] | None:
    """Optional Fate dice after rolling, before the normal pipeline's outcome."""
    from types import SimpleNamespace
    from .roll_context import roll_description

    # Legacy reasons do not all carry a category prefix. Reaction contests
    # represent attack rolls or ability checks (Court allows both); Counterweave
    # is a check. Initiative, chance, stored dice and weapon integrity are not
    # creature attack/check/save rolls and remain ineligible.
    category = str(roll.reason).partition(":")[0]
    category = {"QI_HAZARD_DEX_SAVE": "SAVE", "REACTION_COUNTER": "CHECK",
                "REACTION_CONTEST": "CONTEST"}.get(category, category)
    roll_name = {"ATTACK": "attack roll", "CHECK": "ability check", "SAVE": "saving throw",
                 "CONTEST": "attack roll or ability check"}.get(category)
    if roll_name is None:
        return None
    actor = engine.state.actors.get(roll.actor_id)
    if actor is None or roll.natural_result is None:
        return None
    action = next((a for a in engine.action_catalog.values() if a.source_definition_id in str(roll.reason)), None)
    trigger = roll_description(engine, roll) or ("Dexterity saving throw against the Qi hazard" if roll.reason == "QI_HAZARD_DEX_SAVE"
               else f"{roll_name} for {action.display_name}" if action else roll_name)
    ctx = SimpleNamespace(intent=intent, action=SimpleNamespace(display_name=f"{trigger} (d20 {roll.natural_result}, total {roll.total})"))
    bonus = _court(engine, actor, ctx)
    if category in ("ATTACK", "SAVE"):
        bonus += _serendipity(engine, actor, ctx)
    if category in ("ATTACK", "CHECK", "SAVE", "CONTEST"):
        bonus += _empress_release(engine, actor, ctx, str(roll.roll_id), roll)
    return {"source_id": "fate:optional_roll_bonus", "bonus": bonus} if bonus else None


@hook("ac")
def fate_ac(engine: Any, target: Any) -> int | None:
    total = sum(1 for c in _held(target, BOON) if (c.data or {}).get("boon") == "ac")
    total -= sum(2 for c in _held(target, CALAMITY_C) if "ac" in ((c.data or {}).get("picked") or []))
    return total or None


@hook("flight")
def sovereign_flight(engine: Any, actor: Any) -> dict[str, int]:
    """The existing timed Incarnation grants its printed Fly Speed and Hover."""
    return {"fly_speed_ft": 40, "flight_hover": 1} if _held(actor, SOVEREIGN) else {}


@hook("attack_mode")
def fate_attack_mode(ctx: Any, target: Any) -> str | None:
    engine, actor = ctx.engine, ctx.actor
    for c in _held(actor, BOON):
        if (c.data or {}).get("boon") == "advantage":
            engine._remove_condition(actor, BOON, SOVEREIGN_ID)
            return "ADVANTAGE"
    if _auspice(target, "guiding_star") is not None and engine.state.current_actor_id == target.entity_id:
        return "DISADVANTAGE"  # "During the target's turn, attack rolls made against it have Disadvantage."
    for c in _held(target, CHAIN_OPENING):
        if (c.data or {}).get("ally") == actor.entity_id:
            engine._remove_condition(target, CHAIN_OPENING, CHAIN_ID)
            return "ADVANTAGE"
    return None


@hook("damage_roll_bonus")
def wheel_damage(ctx: Any, effect_row: dict[str, Any] | None = None, kinds: list[str] | None = None) -> int | None:
    """Turning Wheel's attack face also adds to every damage roll, not fixed damage."""
    return _wheel(ctx.actor, "attack") or None


@effect("fate_wheel")
def turning_wheel(ctx: Any, eff: dict[str, Any]) -> None:
    from .. import typed_executor

    cl = int(ctx.numbers.get("cl") or 1)
    bonus = 3 if cl >= 17 else 2 if cl >= 11 else 1
    for subject in _subjects(ctx, eff):
        if not subject.active:
            continue
        face = _roll(ctx.engine, ctx.actor, 6, "TURNING_WHEEL")
        kind = "attack" if face <= 2 else "save" if face <= 4 else "check"
        for old in _held(subject, WHEEL):
            ctx.engine._remove_condition(subject, WHEEL, ctx.source)
        words = {"attack": "attack rolls and damage rolls", "save": "saving throws", "check": "ability checks"}[kind]
        ctx.engine._apply_condition(subject, WHEEL, ctx.source, ctx.actor.entity_id,
                                    expires_on=typed_executor.effect_expiry(ctx, eff, subject, condition=True) or "UNTIL_REMOVED",
                                    data={"kind": kind, "bonus": bonus, "face": face, "label": f"Turning Wheel ({face}): +{bonus} to {words}"})
        ctx.rider(f"Turning Wheel Auspice: 1d6 = {face} -- +{bonus} to {words}.")


# ------------------------------------------------------------------------------------------------ Chain of Misfortune
@effect("fate_chain")
def chain_of_misfortune(ctx: Any, eff: dict[str, Any]) -> None:
    from .. import typed_executor

    dc = int(ctx.numbers.get("save_dc") or 10)
    for subject in ctx.targets or []:
        if subject is None or not subject.active:
            continue
        if eff.get("warning"):
            ctx.engine._apply_condition(subject, CHAIN_WARN, ctx.source, ctx.actor.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN",
                                        data={"label": "Chain of Misfortune: its next miss or failed save costs its Reactions"})
            continue
        ctx.engine._apply_condition(subject, CHAIN, ctx.source, ctx.actor.entity_id,
                                    expires_on=typed_executor.effect_expiry(ctx, eff, subject, condition=True) or "UNTIL_REMOVED",
                                    data={"repeat_save": {"ability": "CHA", "dc": dc, "when": "end"},
                                          **({"failed_check": True} if eff.get("failed_check") else {}),
                                          "label": "Chain of Misfortune: its first misstep each round lets the curser choose a misfortune"})


def _no_reactions(engine: Any, subject: Any, source: str, source_actor: str, turns_ahead: int = 1) -> None:
    engine._apply_condition(subject, C + "reaction_denied", source, source_actor, expires_on=_token("start", subject, turns_ahead),
                            data={"label": "No Reactions"})


def _misstep(engine: Any, subject: Any, prone: bool = False, failed_check: bool = False) -> None:
    for warn in [] if prone or failed_check else _held(subject, CHAIN_WARN):  # warning excludes checks and prone
        engine._remove_condition(subject, CHAIN_WARN, CHAIN_ID)
        _no_reactions(engine, subject, CHAIN_ID, warn.source_actor_id, 2 if engine.state.current_actor_id == subject.entity_id else 1)
        note(engine, CHAIN_ID, subject, f"Chain of Misfortune: {subject.display_name} cannot take Reactions until the start of its following turn.")
    for curse in _held(subject, CHAIN):
        if failed_check and not (curse.data or {}).get("failed_check"):
            continue  # legacy sealed curses keep their original triggers
        if not _once_a_round(engine, ("chain", curse.instance_id)):
            continue
        caster = engine.state.actors.get(curse.source_actor_id)
        if caster is None:
            continue
        options = {"damage": "2d8 Psychic damage", "reactions": "no Reactions until the start of its next turn",
                   "speed": "Speed -10 until the start of its next turn", "opening": "an ally within 30 feet gets Advantage on its next attack against it"}
        allies = sorted((a for a in engine.state.actors.values() if a.active and a.team_id == caster.team_id and a is not subject
                         and engine._distance_actor_to_actor(a, subject) <= 30), key=lambda a: (engine._distance_actor_to_actor(a, subject), a.entity_id))
        if not allies:
            options.pop("opening")
        picked = ask(engine, getattr(engine, "_active_intent", None), checkpoint_id(engine, "CHAIN_OF_MISFORTUNE", caster.entity_id, subject.entity_id), caster,
                     CHOICE + "chain_of_misfortune", list(options), labels=options, preferred=["damage"], target_id=subject.entity_id,
                     prompt=f"Chain of Misfortune: {subject.display_name} stumbles -- choose its misfortune")
        choice = picked[0] if picked else "damage"
        note(engine, CHAIN_ID, subject, f"Chain of Misfortune: {options[choice]}.")
        if choice == "damage":
            engine._commit_damage(subject, _roll(engine, caster, 8, "CHAIN_OF_MISFORTUNE", 2), "PSYCHIC", CHAIN_ID, caster.entity_id, None, reaction_depth=1)
        elif choice == "reactions":
            _no_reactions(engine, subject, CHAIN_ID, caster.entity_id)
        elif choice == "speed":
            engine._add_modifier(subject, CHAIN_ID, "speed_ft", "ADD", -10, "SELF", expires_on=_token("start", subject))
        else:
            engine._apply_condition(subject, CHAIN_OPENING, CHAIN_ID, caster.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN",
                                    data={"ally": allies[0].entity_id, "label": f"Chain of Misfortune: {allies[0].display_name}'s next attack has Advantage"})


@hook("after_miss")
def chain_on_miss(ctx: Any, target: Any) -> None:
    _misstep(ctx.engine, ctx.actor)
    if _held(ctx.actor, VIOLENCE):
        ctx.engine._remove_condition(ctx.actor, VIOLENCE, VIOLENCE_ID)


@hook("after_hit")
def violence_done(ctx: Any, target: Any, kind: str) -> None:
    if _held(ctx.actor, VIOLENCE):
        ctx.engine._remove_condition(ctx.actor, VIOLENCE, VIOLENCE_ID)


@hook("after_save")
def chain_on_save(ctx: Any, subject: Any, ability: str, named: Any, failed: bool) -> None:
    if failed:
        _misstep(ctx.engine, subject)


# ------------------------------------------------------------------------------------------------ Calamity Finds a Path
CALAMITY_OPTIONS = {"prone": "falls Prone", "drop": "drops one held object", "reactions": "cannot take Reactions", "speed": "Speed becomes 0",
                    "ac": "AC is reduced by 2", "healing": "healing it receives is halved"}


@effect("fate_calamity")
def calamity(ctx: Any, eff: dict[str, Any]) -> None:
    from ..typed_executor import run_effects

    count = int(eff.get("count") or 1)
    for subject in ctx.targets or []:
        if subject is None or not subject.active:
            continue
        picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "CALAMITY", ctx.actor.entity_id, subject.entity_id), ctx.actor, CHOICE + "calamity",
                     list(CALAMITY_OPTIONS), labels=CALAMITY_OPTIONS, preferred=["prone", "ac", "reactions", "speed", "healing", "drop"][:count],
                     minimum=count, maximum=count, target_id=subject.entity_id, prompt=f"Calamity Finds a Path: choose {count}")
        picked = list(picked or [])[:count] or ["prone", "ac"][:count]
        ctx.rider("Calamity Finds a Path: " + "; ".join(CALAMITY_OPTIONS[p] for p in picked) + " (until the start of your next turn).")
        if "prone" in picked:
            run_effects(ctx, [{"type": "condition", "condition": "prone", "applies_to": "target"}])
        if "drop" in picked:
            _drop_held(ctx, subject)
        if "reactions" in picked:
            ctx.engine._apply_condition(subject, C + "reaction_denied", ctx.source, ctx.actor.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN",
                                        data={"label": "No Reactions (Calamity Finds a Path)"})
        rules = {**({"speed_zero": True} if "speed" in picked else {}), **({"healing_halved": True} if "healing" in picked else {})}
        if rules or "ac" in picked:
            ctx.engine._apply_condition(subject, CALAMITY_C, ctx.source, ctx.actor.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN",
                                        data={"rule": rules, "picked": picked, "label": "Calamity: " + ", ".join(CALAMITY_OPTIONS[p] for p in picked)})


def _drop_held(ctx: Any, subject: Any) -> None:
    """"drops one held object": its first held weapon (combat/carry.py), dropped as typed_executor's drop_item does."""
    from .. import carry, typed_executor

    items = (carry.carrying_of(ctx.engine, subject.entity_id) or {}).get("items") or []
    key = next((str(i.get("key")) for i in items if i.get("weapon_action") and carry.holds(ctx.engine, subject, str(i.get("key")))), None)
    if key is not None:
        typed_executor.block_drop_item(_ctx(ctx.engine, subject, None, CALAMITY, "Calamity Finds a Path"), {"type": "drop_item", "item": key})


# ------------------------------------------------------------------------------------------------ Auspices: Guiding Star, Moving Star
@effect("fate_auspice")
def auspice_mark(ctx: Any, eff: dict[str, Any]) -> None:
    from .. import typed_executor

    for subject in _subjects(ctx, eff):
        if subject.active:
            ctx.engine._apply_condition(subject, AUSPICE, ctx.source, ctx.actor.entity_id,
                                        expires_on=typed_executor.effect_expiry(ctx, eff, subject, condition=True) or "UNTIL_REMOVED",
                                        data={"auspice": eff.get("auspice"), "pb": int(ctx.numbers.get("pb") or 2),
                                              "label": eff.get("pill_label") or (
                                                  "Empress of Hidden Growth Auspice (after your roll: add the caster's Proficiency Bonus; no action or Reaction cost; ends on Release or when the caster's Concentration ends)"
                                                  if eff.get("auspice") == "empress" else
                                                  f"{str(eff.get('auspice') or '').replace('_', ' ').title()} Auspice (Release: Reaction)")})
            if eff.get("auspice") == "empress":
                _empress_count_up(ctx.actor, subject)


def _empress_key(creature_id: str) -> str:
    return f"_round_fate_empress:{creature_id}"


def _empress_count_up(caster: Any, subject: Any) -> None:
    """Empress of Hidden Growth Auspice: each grant from this caster to a creature counts once (kept with the fight, not reset per turn)."""
    key = _empress_key(subject.entity_id)
    caster.turn_flags[key] = int(caster.turn_flags.get(key, 0)) + 1


@hook("candidate_allowed")
def empress_per_creature_cap(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """"A creature cannot receive this Auspice from you more than PB times per Long Rest": a fight is the rest here, so the
    caster's own grant count per creature (kept with the fight) stops the offer once it reaches the caster's Proficiency Bonus."""
    typed = ((getattr(action, "parameters", None) or {}).get("typed") or {}) if action is not None else {}
    if typed.get("source") != T + "EMPRESS_OF_HIDDEN_GROWTH_AUSPICE":
        return None
    for target_id in candidate.target_ids or ():
        if int(actor.turn_flags.get(_empress_key(target_id), 0)) >= int(actor.proficiency_bonus):
            return False
    return None


def _auspice(actor: Any, name: str) -> Any:
    return next((c for c in _held(actor, AUSPICE) if (c.data or {}).get("auspice") == name), None)


@hook("opportunity_allowed")
def guiding_star_protection(engine: Any, reactor: Any, mover: Any) -> bool | None:
    """Observe only protection that has already been released."""
    return False if _held(mover, GUIDING_FREE) else None


@hook("opportunity_response")
def guiding_star(engine: Any, reactor: Any, mover: Any) -> bool | None:
    from .. import typed_reactions
    from .d20_floor import end_auspice

    if _held(mover, GUIDING_FREE):
        return False
    held = _auspice(mover, "guiding_star")
    if held is None or not typed_reactions.can_react(engine, mover):
        return None
    picked = ask(engine, getattr(engine, "_active_intent", None), checkpoint_id(engine, "GUIDING_STAR", mover.entity_id), mover, CHOICE + "guiding_star",
                 ["release"], labels={"release": "Release Guiding Star Auspice (Reaction): no Opportunity Attacks for 1 minute"}, allow_decline=True,
                 target_id=mover.entity_id, prompt=f"{reactor.display_name} could make an Opportunity Attack: release Guiding Star?")
    if not picked:
        return None
    with activation(engine, mover, held.source_definition_id):
        mover.reaction_available = False
        end_auspice(engine, mover, held, "RELEASED")
        engine._apply_condition(mover, GUIDING_FREE, held.source_definition_id, held.source_actor_id, expires_on=_token("start", mover, 10),
                                data={"label": "Guiding Star (released): provokes no Opportunity Attacks for 1 minute"})
        note(engine, held.source_definition_id, mover, f"Guiding Star Auspice released: {mover.display_name} provokes no Opportunity Attacks for 1 minute.")
        return False


@hook("condition_immune")
def moving_star(engine: Any, actor: Any, name: str) -> bool | None:
    from .d20_floor import end_auspice

    name = str(name or "").lower()
    if name not in MOVING_NAMES:
        return None
    if any(name in ((c.data or {}).get("names") or []) for c in _held(actor, MOVING_IGNORE)):
        return True
    held = _auspice(actor, "moving_star")
    if held is None or not actor.active or not actor.reaction_available:  # "even while Incapacitated by the triggering effect"
        return None
    picked = ask(engine, getattr(engine, "_active_intent", None), checkpoint_id(engine, "MOVING_STAR", actor.entity_id, name), actor, CHOICE + "moving_star",
                 ["release"], labels={"release": f"Release Moving Star Auspice (Reaction): ignore {name.title()} until the end of your next turn"},
                 allow_decline=True, target_id=actor.entity_id, prompt=f"{actor.display_name} would be {name.title()}: release Moving Star?")
    if not picked:
        return None
    with activation(engine, actor, held.source_definition_id):
        actor.reaction_available = False
        end_auspice(engine, actor, held, "RELEASED")
        engine._apply_condition(actor, MOVING_IGNORE, held.source_definition_id, held.source_actor_id, expires_on="END_OF_HOLDER_NEXT_TURN",
                                data={"names": [name], "label": f"Moving Star (released): ignores {name.title()} until the end of its next turn"})
        return True


# ------------------------------------------------------------------------------------------------ Borrowed Lifespan Talisman
def _borrowed_key(subject: Any) -> str:
    """Per-caster/per-creature Long Rest use; fights have no Long Rest transition.

    The engine retains _round_ flags at turn starts, and table capture/reload and
    preview clones all copy them. Repayment oaths outside combat remain GM work.
    """
    return "_round_fate_borrowed_lifespan:" + subject.entity_id


@hook("ally_row_allowed")
def borrowed_once_each(engine: Any, reactor: Any, subject: Any, row: dict[str, Any]) -> bool | None:
    if row.get("feature_id") != BORROWED:
        return None
    return not reactor.turn_flags.get(_borrowed_key(subject))


def _borrowed_cost(engine: Any, reactor_id: Any, target_ids: Any) -> None:
    from .d20_rewrite import pool_id

    reactor = engine.state.actors.get(str(reactor_id or ""))
    subject = engine.state.actors.get(next(iter(target_ids or ()), ""))
    if reactor is None or subject is None:
        return
    reactor.turn_flags[_borrowed_key(subject)] = 1
    found = rows(engine, reactor, "borrowed")
    cl = int(found[0]["cl"]) if found else 15
    options = {"oath": f"{subject.display_name} swears the repayment oath (it cannot benefit again)", "notice": "you gain 2 Heaven's Notice",
               "exhaustion": f"{subject.display_name} gains one Exhaustion level", "necrotic": f"you take {2 * cl} Necrotic damage"}
    picked = ask(engine, getattr(engine, "_active_intent", None), checkpoint_id(engine, "BORROWED_LIFESPAN", reactor.entity_id, subject.entity_id), reactor,
                 CHOICE + "borrowed_lifespan", list(options), labels=options, preferred=["oath"], target_id=subject.entity_id,
                 prompt=f"Borrowed Lifespan Talisman kept {subject.display_name} at 1 HP: choose the repayment cost")
    choice = picked[0] if picked else "oath"
    note(engine, BORROWED, reactor, f"Borrowed Lifespan Talisman: {options[choice]}.")
    if choice == "necrotic":
        engine._commit_damage(reactor, 2 * cl, "NECROTIC", BORROWED, reactor.entity_id, None, reaction_depth=1)
    elif choice == "exhaustion":
        from .forged_exhaustion import add

        add(engine, subject, 1, BORROWED)
    elif choice == "notice":
        notice = pool_id(reactor, "heaven_s_notice")
        if notice is not None:
            engine._gain_resource(reactor, notice, 2, BORROWED)


# ------------------------------------------------------------------------------------------------ Marked by the Ledger
def _ledger_marks(engine: Any, actor: Any) -> list[tuple[str, Any]]:
    return [(mid, m) for mid, m in actor.modifiers.items() if m.target_field == "typed_on_hit" and _feature(engine, m.source_definition_id) == LEDGER]


def _dropped_before_this_turn(engine: Any, actor: Any, target_id: str) -> bool:
    target = engine.state.actors.get(target_id)
    if target is None or target.current_hp > 0:
        return False
    started = next((e.sequence for e in reversed(engine.events) if e.event_type == "TURN_STARTED" and actor.entity_id in ((e.actor_id,) + tuple(e.target_ids or ()))), 0)
    dropped = next((e.sequence for e in reversed(engine.events) if e.event_type == "DAMAGE_COMMITTED" and target_id in (e.target_ids or ())
                    and int((e.payload or {}).get("remaining_hp") or 0) == 0), None)
    return dropped is not None and dropped < started


@hook("compile_actions")
def ledger_action(info: dict[str, Any]) -> list[Any] | None:
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    if LEDGER not in (info.get("owned_ids") or []):
        return None
    typed = {"effects": [{"type": "fate_ledger_move", "evidence": "move the mark to a new target within 60 feet"}], "numbers": dict(info["numbers"]),
             "duration": {"kind": "instant"}, "riders": [], "source": LEDGER + ":move", "coverage": "FULL"}
    return [ActionDefinition(source_definition_id=f"action:typed.{info['short']}.fate.ledger_move", display_name="Move the Ledger Mark",
                             owner_id=info["actor_id"], economy=EconomyKind.BONUS_ACTION, resolution_kind="TYPED", target_kind="HOSTILE_ENTITY",
                             range_ft=60, costs=(), parameters={"typed": typed, "expected_damage": 0})]


@hook("candidate_allowed")
def ledger_move_ready(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is None or not str(action.source_definition_id).endswith(".fate.ledger_move"):
        return None
    ready = [m for _mid, m in _ledger_marks(engine, actor) if _dropped_before_this_turn(engine, actor, str(m.value).split("|")[0])]
    return bool(ready) and not any(str(m.value).split("|")[0] in (candidate.target_ids or ()) for _mid, m in _ledger_marks(engine, actor))


@effect("fate_ledger_move")
def ledger_move(ctx: Any, eff: dict[str, Any]) -> None:
    engine, actor = ctx.engine, ctx.actor
    new = next((t for t in ctx.targets or [] if t is not None), None)
    for mid, m in _ledger_marks(engine, actor):
        bound, _, evidence = str(m.value).partition("|")
        if new is None or not _dropped_before_this_turn(engine, actor, bound):
            continue
        del actor.modifiers[mid]
        engine._append_event("MODIFIER_REMOVED", m.source_definition_id, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                             payload={"modifier_id": mid, "reason": "MOVED"})
        engine._add_modifier(actor, m.source_definition_id, "typed_on_hit", "ADD", f"{new.entity_id}|{evidence}", "SELF", expires_on=m.expires_on)
        ctx.rider(f"Marked by the Ledger: the mark moves to {new.display_name}.")
        return


# ------------------------------------------------------------------------------------------------ Fate-Sovereign Incarnation's boon
@hook("turn_start")
def sovereign_boon(engine: Any, actor: Any) -> None:
    if not _held(actor, SOVEREIGN) or not actor.active:
        return
    allies = sorted((a for a in engine.state.actors.values() if a.active and a is not actor and a.team_id == actor.team_id
                     and engine._distance_actor_to_actor(a, actor) <= 30), key=lambda a: (a.current_hp / max(1, a.maximum_hp), a.entity_id))
    if not allies:
        return
    intent = getattr(engine, "_active_intent", None)
    chosen = ask(engine, intent, checkpoint_id(engine, "SOVEREIGN_ALLY", actor.entity_id), actor,
                 CHOICE + "sovereign_ally", [a.entity_id for a in allies],
                 labels={a.entity_id: a.display_name for a in allies}, preferred=[allies[0].entity_id],
                 prompt=f"Fate-Sovereign Incarnation: {actor.display_name}'s turn starts; choose the ally within 30 feet")
    if not chosen:
        return
    ally = engine.state.actors[chosen[0]]
    boons = {"ac": "+1 AC", "save": "+1 to saving throws", "advantage": "Advantage on its next attack roll",
             "check": "Advantage on its next ability check"}
    picked = ask(engine, intent, checkpoint_id(engine, "SOVEREIGN_BOON", actor.entity_id, ally.entity_id), actor, CHOICE + "sovereign_boon", list(boons),
                 labels=boons, preferred=["ac"], target_id=ally.entity_id, prompt=f"Fate-Sovereign Incarnation: {ally.display_name}'s boon")
    choice = picked[0] if picked else "ac"
    engine._apply_condition(ally, BOON, SOVEREIGN_ID, actor.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN",
                            data={"boon": choice, "label": f"Fate-Sovereign boon: {boons[choice]}",
                                  **({"rule": {"check_mode": {"ALL": "ADVANTAGE"}}} if choice == "check" else {})})


# ------------------------------------------------------------------------------------------------ events
@hook("event")
def fate_events(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    from .roll_context import check_receipts

    checks = check_receipts(kwargs) if event_type == 'CHECK_ROLLED' else []
    payload = kwargs.get('payload') or {}
    if event_type == 'ZONE_CREATED':
        _choose_designated(engine, payload)
        _choose_hallow_kind(engine, payload)
    success = payload.get('success')
    if type(success) is bool:
        for roller_id, roll in checks:
            # A resolved contest's success belongs to its acting participant;
            # its defending ability check has the opposite outcome. The shared
            # receipt parser excludes opposed saves, bonus dice and no-roll checks.
            won = success if roller_id == kwargs.get('actor_id') else not success
            subject = engine.state.actors.get(roller_id)
            if not won and subject is not None:
                _misstep(engine, subject, failed_check=True)
    for roller_id, roll in checks if event_type == "CHECK_ROLLED" else ():
        if not isinstance(roll, dict) or roll.get("natural_result") is None:
            continue
        roller = engine.state.actors.get(roller_id)
        if roller is not None:
            for held in list(_held(roller, BOON)):
                if held.data.get("boon") == "check":
                    roller.conditions.pop(held.instance_id)
                    engine._append_event("CONDITION_REMOVED", SOVEREIGN_ID, actor_id=held.source_actor_id,
                                         target_ids=(roller.entity_id,),
                                         payload={"condition_id": BOON, "instance_id": held.instance_id})
    if event_type == "TEMP_HP_GRANTED":
        payload = kwargs.get("payload") or {}
        if int(payload.get("after") or 0) > int(payload.get("before") or 0):
            for target_id in kwargs.get("target_ids") or ():
                target = engine.state.actors[target_id]
                for held in list(_held(target, C + "undo_hp")):
                    _forget_undo(engine, target, held)
    _undo_vanish(engine)
    source = str(engine.events[-1].source_definition_id) if engine.events else ""
    if event_type == "DAMAGE_COMMITTED" and source != CONSEQUENCE:
        _consequence(engine, kwargs.get("actor_id"), kwargs.get("target_ids"), kwargs.get("payload") or {})
    elif event_type == "HEALING_APPLIED":
        _purity(engine, kwargs.get("target_ids"), kwargs.get("payload") or {})
    elif event_type == "REACTION_RESOLVED" and source == BORROWED:
        _borrowed_cost(engine, kwargs.get("actor_id"), kwargs.get("target_ids"))
    elif event_type == "CONDITION_APPLIED" and str((kwargs.get("payload") or {}).get("condition_id") or "").endswith("prone"):
        for target_id in kwargs.get("target_ids") or ():
            subject = engine.state.actors.get(target_id)
            if subject is not None and _held(subject, CHAIN):
                _misstep(engine, subject, prone=True)

# Second pass: pre-draw Release and Lone Lantern's actual self-Help.
LANTERN_ID = T + "LONE_LANTERN_AUSPICE"
LANTERN = C + "lone_lantern"
LANTERN_RELEASED = C + "lone_lantern_released"
LANTERN_HELP = C + "lone_lantern_help"
LANTERN_HELP_ACTION = "system:fate.lone_lantern_help"


@effect("fate_lone_lantern")
def grant_lantern(ctx: Any, eff: dict[str, Any]) -> None:
    from ..typed_executor import effect_expiry
    for subject in _subjects(ctx, eff):
        ctx.engine._apply_condition(subject, LANTERN, ctx.source, ctx.actor.entity_id,
            expires_on=effect_expiry(ctx, eff, subject, condition=True) or "UNTIL_REMOVED",
            data={"label": "Lone Lantern Auspice: while alone, Help yourself as a Bonus Action; Release (Reaction): 1 minute of Advantage against creatures with no ally of yours beside them."})


def _lantern_alone(engine: Any, actor: Any) -> bool:
    return not any(a is not actor and a.active and engine._distance_actor_to_actor(actor, a) <= 5
                   for a in engine.state.actors.values())


def _lantern_skills(engine: Any, actor: Any) -> list[str]:
    bundle = next((b for b in engine.typed_bundle_documents if b.get("actor_id") == actor.entity_id), {})
    return sorted(s for s, rank in (bundle.get("skill_proficiency") or {}).items() if int(rank or 0) > 0)


@hook("match_start")
def lantern_action(engine: Any) -> None:
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    engine.action_catalog[LANTERN_HELP_ACTION] = ActionDefinition(
        source_definition_id=LANTERN_HELP_ACTION, display_name="Lone Lantern: Help yourself",
        owner_id="*", economy=EconomyKind.BONUS_ACTION, resolution_kind="TYPED", target_kind="SELF",
        parameters={"typed": {"effects": [{"type": "fate_lantern_help"}], "numbers": {},
                               "duration": {"kind": "instant"}, "riders": []}, "expected_damage": 0,
                    "description": "While no other creature is within 5 feet, spend a Bonus Action to Help yourself on your next check with a skill you know before your next turn. You cannot receive another creature's Help until that turn."})


@hook("additional_actions")
def lantern_help_offer(engine: Any, actor: Any) -> list[str]:
    return [LANTERN_HELP_ACTION] if _held(actor, LANTERN) and _lantern_alone(engine, actor) and _lantern_skills(engine, actor) else []


@hook("candidate_allowed")
def lantern_help_allowed(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is None or action.source_definition_id != LANTERN_HELP_ACTION:
        return None
    return bool(_held(actor, LANTERN) and _lantern_alone(engine, actor) and _lantern_skills(engine, actor))


@effect("fate_lantern_help")
def lantern_help(ctx: Any, eff: dict[str, Any]) -> None:
    from .condition_ownership import remove_instance
    skills = _lantern_skills(ctx.engine, ctx.actor)
    if not _held(ctx.actor, LANTERN) or not _lantern_alone(ctx.engine, ctx.actor) or not skills:
        return
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "LANTERN_HELP", ctx.actor.entity_id),
        ctx.actor, CHOICE + "lantern_help", skills, labels={s: s for s in skills},
        prompt=f"Lone Lantern Auspice: Help {ctx.actor.display_name}'s next check with which proficient skill? Bonus Action; Advantage before the start of your next turn.")
    if not picked:
        return
    for old in _held(ctx.actor, LANTERN_HELP):
        remove_instance(ctx.engine, ctx.actor, old.instance_id, ctx.source)
    ctx.engine._apply_condition(ctx.actor, LANTERN_HELP, ctx.source, ctx.actor.entity_id,
        expires_on=_token("start", ctx.actor), data={"skill": picked[0], "used": False, "rule": {"check_mode": {picked[0]: "ADVANTAGE"}},
        "label": f"Lone Lantern Help: Advantage on next {picked[0]} check; no other creature's Help before next turn."})


@hook("event")
def lantern_check_consumed(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type != "CHECK_ROLLED":
        return
    from .roll_context import check_skill_receipts
    # Keep the no-other-Help restriction after its one check has been used.
    for aid, roll, skill in check_skill_receipts(kwargs):
        actor = engine.state.actors.get(aid)
        if actor is None:
            continue
        for c in list(_held(actor, LANTERN_HELP)):
            if c.data.get("used") or str(skill or "").replace("_", " ").casefold() != c.data.get("skill", "").casefold():
                continue
            from .condition_ownership import remove_instance
            data = {**c.data, "used": True, "rule": {},
                    "label": f"Lone Lantern Help: {c.data['skill']} check benefit used; no other creature's Help until the start of your next turn."}
            remove_instance(engine, actor, c.instance_id, c.source_definition_id)
            engine._apply_condition(actor, LANTERN_HELP, c.source_definition_id, c.source_actor_id,
                                    expires_on=c.expires_on, data=data)


@hook("before_attack")
def lantern_release(engine: Any, actor: Any, target: Any, intent: Any, context: dict[str, Any]) -> None:
    from ..typed_reactions import can_react
    from .. import stealth
    from .d20_floor import end_auspice
    held = next(iter(_held(actor, LANTERN)), None)
    if held is None or not can_react(engine, actor):
        return
    useful = not any(a is not actor and a.active and a.team_id == actor.team_id
                     and stealth.sees(engine, actor, a) and engine._distance_actor_to_actor(a, target) <= 5
                     for a in engine.state.actors.values())
    action = engine.action_catalog.get(context.get("source_id"))
    name = action.display_name if action else "attack"
    picked = ask(engine, intent, checkpoint_id(engine, "LANTERN_RELEASE", actor.entity_id, target.entity_id, context.get("attack_index")),
        actor, CHOICE + "lantern_release", ["release"], labels={"release": "Release (Reaction): 1 minute of Advantage while your allies are away from your target"},
        allow_decline=True, automatic=useful, default="first" if useful else "decline", target_id=target.entity_id,
        prompt=f"Lone Lantern Auspice: before {actor.display_name}'s {name} against {target.display_name}, spend your Reaction and end the Auspice? For 1 minute, attacks have Advantage when none of your allies are within 5 feet of the target.")
    if picked:
        actor.reaction_available = False
        end_auspice(engine, actor, held, "RELEASED")
        engine._apply_condition(actor, LANTERN_RELEASED, held.source_definition_id, held.source_actor_id,
            expires_on=_token("start", actor, 10), data={"label": "Lone Lantern released: Advantage against creatures without your allies within 5 feet (1 minute)."})
        engine._append_event("REACTION_RESOLVED", LANTERN_ID, actor_id=actor.entity_id, target_ids=(target.entity_id,),
                             payload={"checkpoint": "BEFORE_ATTACK", "reaction_name": "Lone Lantern Release"})


@hook("attack_mode_contribution")
def lantern_attack_advantage(engine: Any, actor: Any, target: Any) -> str | None:
    if not _held(actor, LANTERN_RELEASED):
        return None
    if any(a is not actor and a.active and a.team_id == actor.team_id
           and engine._distance_actor_to_actor(a, target) <= 5 for a in engine.state.actors.values()):
        return None
    return {'mode': 'ADVANTAGE', 'effect': 'Lone Lantern released', 'owner': actor,
            'why': 'none of your allies is within 5 feet of the target'}


@hook("before_d20_bonus")
def wheel_before_roll(engine: Any, request: dict[str, Any], intent: Any) -> int | None:
    from ..typed_reactions import can_react
    from .d20_floor import end_auspice
    actor = engine.state.actors.get(request["actor_id"])
    if actor is None:
        return None
    kind = {"ATTACK": "attack", "CHECK": "check", "SAVE": "save", "QI_HAZARD_DEX_SAVE": "save",
            "REACTION_CONTEST": "check", "REACTION_COUNTER": "check"}.get(request["reason"].partition(":")[0])
    if kind is None:
        return None
    total = 0
    for held in list(_held(actor, WHEEL)):
        bonus = int(held.data.get("bonus") or 0)
        passive = bonus if held.data.get("kind") == kind else 0
        if not can_react(engine, actor):
            total += passive
            continue
        action = next((a for a in engine.action_catalog.values() if a.source_definition_id in request["reason"]), None)
        trigger = action.display_name if action else {"attack": "attack roll", "check": "ability check", "save": "saving throw"}[kind]
        picked = ask(engine, intent, checkpoint_id(engine, "WHEEL_RELEASE", actor.entity_id, request["reason"], engine.roller.counter), actor,
            CHOICE + "wheel_release", ["release"], labels={"release": f"Release (Reaction): +{2 * bonus} to this roll; Auspice ends"},
            allow_decline=True, default="decline", target_id=actor.entity_id,
            prompt=f"Turning Wheel Auspice: before {actor.display_name}'s {trigger} is rolled, spend your Reaction and end the Auspice for +{2 * bonus} on this roll?")
        if picked:
            actor.reaction_available = False
            end_auspice(engine, actor, held, "RELEASED")
            total += 2 * bonus
            engine._append_event("REACTION_RESOLVED", WHEEL_ID, actor_id=actor.entity_id,
                target_ids=(actor.entity_id,), payload={"checkpoint": "BEFORE_D20", "reaction_name": "Turning Wheel Release", "bonus": 2 * bonus})
        else:
            total += passive
    return total or None


@hook("confirmed_hit_roll_bonus")
def wheel_native_damage(engine: Any, attacker: Any, target: Any, spec: dict[str, Any], intent: Any, source: str) -> int | None:
    # Typed packets already use damage_roll_bonus (also covering non-attack
    # damage rolls); native primary weapon packets need the same flat bonus.
    if spec.get("fixed_damage") is not None:
        return None  # The printed bonus is to a damage roll, not a fixed packet.
    frame = getattr(engine, "_typed_critical_scope", None)
    if frame and frame[0].actor is attacker and frame[1] is target and frame[2] is spec:
        return None
    return _wheel(attacker, "attack") or None


@hook("help_benefit_allowed")
def lantern_other_help(engine: Any, helper: Any, recipient: Any) -> bool | None:
    if helper is not recipient and _held(recipient, LANTERN_HELP):
        return False
    return None
