"""Exorcist (Spirit Awakening Tradition; rider lane C8, 2026-09-30: "i want everything we can automated").

Source: the owner's text (authority/typed_mechanics/rules_text.json; LocalSources/03_paths/Spirit/
Tianxia_Spirit_Awakening_Tradition_Compendium_R7.md, Exorcist: CL3 Ghost Sight and Name the Intruder, CL6 Banishment Strike, CL10
Purification Bell, CL14 Seal of Binding, CL18 Grand Exorcism). No Spheres 5e or D&D 5.5e counterpart.

Purification Bell and Seal of Binding use explicit persisted creature labels for their printed target categories.
The Bell still asks which eligible creatures to affect. Unlabelled creatures do not qualify.
Grand Exorcism's kind-specific results (forced out of a Host, banished, expelled) remain the GM's.

What runs:
  * Purification Bell (Action, 5 Resonance, 30-foot emanation): the hostile creatures you choose in it (asked; the AI chooses every
    hostile creature there) make a Wisdom save -- failed: 6d8 Radiant or Psychic (the better-landing one), Resonance Marked, Frightened
    of you until the end of your next turn; success: half and no Reactions until the start of its next turn. Resonant Exposure: an
    Invisible creature it damages cannot benefit from being Invisible, against anyone, until the end of your next turn. Each ally in
    the area may instead receive one purification benefit (asked): end one Frightened or Charmed, or remove one mark a hostile
    creature placed on it.
  * Seal of Binding (Action, 30 feet, 6 Resonance, the scene): the target makes a Charisma save. Failed: a Binding Seal Anchor object
    appears within 5 feet of it (AC your Cultivation Save DC, 5 x PB Hit Points, immune to Poison and Psychic; anyone can attack it
    with "Attack an object"); while it stands the target is Restrained, and it repeats the save at the end of each of its turns --
    three successes in all destroy the Anchor. Destroying the Anchor ends the binding. Success: Restrained until the start of your
    next turn and Resonance Marked.
    While the Anchor stands, the target cannot teleport, cannot become Invisible or Incorporeal, and cannot move more than 30 feet
    from it (a voluntary step is refused).
  * Grand Exorcism (Action, 10 Resonance, 60-foot emanation): the hostile creatures you choose make a Charisma save -- failed: 10d10
    Radiant or Psychic; success: half, Resonance Marked and your chosen Spiritual Pressure. Allied Purification: each ally in the area
    may end one Frightened or Charmed (asked).
  * Ghost Sight: 60-foot Spiritual Sense only against explicitly recorded spiritual creature kinds
    (spirits, ghosts, incorporeal undead, projected souls, possession entities, spirit parasites, and
    the printed curse/contamination/corpse-animation/funerary-disturbance labels); no empty-cell sight or
    general Blindsight. Name the Intruder diagnoses represented creature conditions and records one of
    the five printed Exorcist Designations; against a higher-Source-CL or concealed record,
    the diagnosis is rolled as a Cultivation Check and
    recorded as Contested on a failure, so a freely chosen label is never recorded as fact.
    Intruders, Curse Sources and Restless Dead receive a Resonance Mark immediately. A successful
    Charisma save conceals its perception row until your next turn.
  * Ward of Invitation: Advantage on an explicitly tagged Cultivation Check about whether a
    possession, hosting, spirit bond or haunting is willing, inherited, lawfully invited, coerced or
    parasitic. Pure mode query; it never invents a check or reads a topic out of prose.
    Name the Intruder's contested designation check supplies these explicit topics; other checks
    remain unaffected.
  * Native-dead Banishment Strike: after failed Mind Spike, optionally spend 2 Resonance for a Charisma save; failed: one minute of
    Frightened with end-turn repeat saves; success: ordinary Pressure and exposure to your sight. Host/Anchor approach restrictions,
    expulsion, possession links and planar removal remain unimplemented.

Plug-in surface: effects exorcist_rite, exorcist_seal, exorcist_name; hooks turn_start, turn_end, event, compile_action,
target_eligibility, sense_target_range, ability_check_hazard_mode, after_save_resolved, teleport_gate, condition_attempt,
masked_conditions, movement_attempt, presentation_hidden_conditions. Shared helpers used: spirit_traditions (context/numbers/
save/remove), ability_source.cultivation_check, condition_authority.source_cl, needle.ask, typed_executor (run_effects/block_condition/
MARK_PREFIX), exposed (the "exposed" effect row).
"""

from __future__ import annotations

from .map_positions import offset_positions

import copy
from typing import Any

from . import effect, hook, note
from . import spirit_traditions as st

TRADITION = "tianxia.tradition.spirit.exorcist.feature."
BELL = TRADITION + "purification_bell"
SEAL = TRADITION + "seal_of_binding"
GRAND = TRADITION + "grand_exorcism"
SEAL_STATE = "condition:typed.binding_seal"
ANCHOR = "object:typed.binding_seal:"
INVISIBLE = "condition:typed.invisible"
CALM = ("frightened", "charmed")
NAME = TRADITION + "ghost_sight_and_name_the_intruder"
BANISH = TRADITION + "banishment_strike"
LATENT_MARK = "condition:typed.exorcist_concealed_mark"
GHOST_KINDS = ("spirit", "ghost", "incorporeal undead", "projected soul", "possession entity", "spirit parasite")
# Printed Ghost Sight perceives "ordinary curses, spiritual contamination, corpse animation, and
# funerary disturbance" as well as the spirit kinds above. Explicit printed labels only: an
# unlabelled creature never matches, so this stays inert for every other character.
GHOST_SIGHT_KINDS = GHOST_KINDS + ("cursed", "spiritually contaminated", "animated corpse", "funerary disturbance")
# The printed Exorcist Designation list has five entries; only three of them earn a Resonance Mark.
DESIGNATIONS = ("Intruder", "Curse Source", "Restless Dead")
CHOICE_DESIGNATIONS = ("Intruder", "Host", "Curse Source", "Restless Dead", "Lawful Guest")
# Printed plain-language descriptions of the five Exorcist Designations, shown as the player-facing
# option labels. The option values above stay the stable ids that features and saved fights record.
DESIGNATION_LABELS = {
    "Intruder": "Intruder - a possessing, parasitic, controlling, or unlawfully hosted entity",
    "Host": "Host - the body, object, site, corpse, or soul that is being occupied",
    "Curse Source": "Curse Source - the spirit, object, vow, wound, or route that keeps a curse or "
                    "contamination going",
    "Restless Dead": "Restless Dead - a ghost, undead soul, corpse-spirit, or funerary disturbance "
                     "that should have passed on to lawful rest",
    "Lawful Guest": "Lawful Guest - a willing, accepted, ancestral, bonded, or otherwise legitimate "
                    "spirit presence",
}
MARKED_DESIGNATIONS = DESIGNATIONS
# Ward of Invitation's printed determination questions: whether a possession, hosting, spirit bond or
# haunting is willing, inherited, lawfully invited, coerced or parasitic.
WARD_OF_INVITATION_TOPICS = ("possession", "hosting", "spirit bond", "spirit_bond", "haunting",
                             "willing", "willingness", "inheritance", "inherited",
                             "lawful invitation", "lawful_invitation", "coerced", "coercion", "parasitic")


@hook("compile_action")
def name_target_kind(action: Any, info: dict[str, Any]) -> Any:
    if st.feature_of(action) == NAME:
        return action.model_copy(update={"target_kind": "ANY_CREATURE"})
    return None


@hook("target_eligibility")
def name_target_allowed(engine: Any, actor: Any, target: Any, action: Any) -> bool | None:
    from .creature_kinds import matches
    if st.feature_of(action) != NAME:
        return None
    qualified = (matches(target, (*GHOST_KINDS, "possessed", "cursed", *DESIGNATIONS))
                 or _te().bears_mark(target, actor.entity_id, "Resonance"))
    return None if qualified else False


@hook("sense_target_range")
def ghost_sight_range(engine: Any, viewer: Any, sense: str, seen: Any) -> int | None:
    from .. import senses
    from .creature_kinds import matches

    if (sense != "spiritual_sense" or not senses.is_creature(seen)
            or st.row(engine, viewer, "ghost_sight") is None or not matches(seen, GHOST_SIGHT_KINDS)):
        return None
    # A recorded protected concealment must still use its own contest procedure.
    authority = int(st.numbers(engine, viewer).get("cl") or 1)
    from .condition_authority import source_cl
    if any((c.data or {}).get("total_spiritual_concealment") == 1
           or (str(c.condition_id).rsplit(".", 1)[-1] in ("hidden", "invisible")
               and ((level := source_cl(engine, c)) is None or level >= authority))
           for c in seen.conditions.values()):
        return None
    return 60


@hook("ability_check_hazard_mode")
def ward_of_invitation_mode(engine: Any, actor: Any, ability: Any, skill: Any, against: Any, hazards: Any) -> str | None:
    """Printed: "You have Advantage on Cultivation Checks made to determine whether a possession,
    hosting, spirit bond, or haunting is willing, inherited, lawfully invited, coerced, or parasitic."

    A pure mode query over the explicit hazard tags the check actually carries; it never invents a
    check or reads the topic out of prose. Inert for any actor who does not own this feature.
    Name the Intruder supplies explicit topics when resolving a designation.
    """
    if (str(skill or "").lower() != "cultivation" and str(ability or "").upper() != "CULTIVATION") \
            or st.row(engine, actor, "ghost_sight") is None:
        return None
    asked = {str(tag).strip().casefold() for tag in (hazards or ())}
    if not asked or not (asked & set(WARD_OF_INVITATION_TOPICS)):
        return None
    return "ADVANTAGE"


def _designation_source_cl(engine: Any, subject: Any) -> int | None:
    """The creature's own recorded Source CL, from its compiled bundle (printed source, never a guess)."""
    for bundle in getattr(engine, "typed_bundle_documents", ()) or ():
        if str(bundle.get("actor_id") or "") == str(subject.entity_id):
            try:
                value = int(bundle.get("cl"))
            except (TypeError, ValueError):
                return None
            return value if value >= 1 else None
    return None


def _designation_protection(engine: Any, actor: Any, target: Any) -> tuple[Any, int | None] | None:
    """The recorded protection that contests a freely chosen Designation: ``(effect, save DC)``.

    Printed (Exorcist Designations): "If the target's Source CL exceeds yours or the relevant
    presence, route, or Anchor is concealed, make a Cultivation Check against the opposing effect's
    save DC." Every recorded concealment is resolved and the diagnosis answers the most demanding
    one, so a weaker concealment never masks a stronger. When both apply, a creature whose own
    Source CL exceeds yours is still a candidate through its recorded authority, so a weaker
    concealment never drops that authority either; the higher DC answers. A concealment or a
    creature authority that cannot be resolved leaves the DC unknown: it could be the strongest,
    so the diagnosis stays contested.
    """
    from .condition_authority import source_cl

    cl = int(st.numbers(engine, actor).get("cl") or 1)
    own_dc: int | None = None
    if (_target := _designation_source_cl(engine, target)) is not None and _target > cl:
        own_dc = _designation_dc(engine, target)
        if own_dc is None:
            return target, None
    concealments = [held for held in target.conditions.values()
                    if _name(held) in ("hidden", "invisible")
                    or (held.data or {}).get("total_spiritual_concealment") == 1]
    if not concealments:
        return (target, own_dc) if own_dc is not None else None
    resolved: list[tuple[tuple[int, int, str], Any]] = []
    for held in concealments:
        dc = _designation_dc(engine, held)
        if dc is None:
            return held, None
        level = source_cl(engine, held)
        resolved.append(((dc, int(level or 0), str(getattr(held, "instance_id", ""))), held))
    rank, strongest = max(resolved, key=lambda item: item[0])
    if own_dc is not None and own_dc > rank[0]:
        return target, own_dc
    return strongest, rank[0]


def _designation_dc(engine: Any, opposing: Any) -> int | None:
    """Opposing effect DC, source's Cultivation DC, then Tradition Addendum Authority DC.

    The Addendum uses 10 + opposing Source CL's PB + source key modifier (+3 if absent).
    Missing source authority stays unknown; Spiritual Exorcism's realm table is separate.
    """
    from .ability_source import numbers_of
    from .condition_authority import source_cl

    data = getattr(opposing, "data", None) or {}
    if int(data.get("save_dc") or 0) > 0:
        return int(data["save_dc"])
    action = engine.action_catalog.get(str(getattr(opposing, "source_definition_id", "") or ""))
    effect_numbers = {}
    if action is not None:
        effect_numbers = ((action.parameters or {}).get("typed") or {}).get("numbers") or {}
        if int(effect_numbers.get("save_dc") or 0) > 0:
            return int(effect_numbers["save_dc"])
    source = engine.state.actors.get(str(getattr(opposing, "source_actor_id", "") or ""))
    # A creature opposes with its own authority; a condition uses its recorded source actor.
    if source is None and hasattr(opposing, "entity_id"):
        source = opposing
    source_numbers = numbers_of(engine, source) if source is not None else {}
    if source is not None:
        dc = int(source_numbers.get("save_dc") or 0)
        if dc > 0:
            return dc
    level = (_designation_source_cl(engine, opposing) if hasattr(opposing, "entity_id")
             else source_cl(engine, opposing))
    if level is None or level < 1:
        return None
    pb = 2 + (level - 1) // 4
    key_mod = effect_numbers.get("key_mod", source_numbers.get("key_mod"))
    return 10 + pb + (int(key_mod) if key_mod is not None else 3)


def _designation_status(ctx: Any, target: Any, designation: str) -> tuple[str, str]:
    """``(status, why)`` for one assigned Designation: "confirmed" or "contested".

    Printed: "A Designation records your diagnosis; it does not make the diagnosis true by fiat."
    Higher authority and concealment require a check even for a matching creature label.
    Missing inline DCs resolve through the recorded source and printed Authority formula.
    """
    from . import ability_source

    resolved = _designation_protection(ctx.engine, ctx.actor, target)
    if resolved is None:
        return "confirmed", ""
    _opposing, dc = resolved
    if dc is None:
        return "contested", "the opposing source's authority is not recorded"
    numbers = ctx.numbers or st.numbers(ctx.engine, ctx.actor)
    # Keep scoped modes unresolved so independent actor-wide penalties can cancel them.
    modes = _te().check_modes(ctx.actor, "CULTIVATION", "Cultivation",
                             engine=ctx.engine, against_creature=target)
    ward = (ward_of_invitation_mode(ctx.engine, ctx.actor, "CULTIVATION", "Cultivation", target,
                                    WARD_OF_INVITATION_TOPICS)
            if designation in ("Intruder", "Host", "Lawful Guest") else None)
    if ward == "ADVANTAGE":
        # Add a source, rather than resolving early: any Disadvantage still cancels it.
        modes = set(modes or ()) | {"ADVANTAGE"}
    if ability_source.cultivation_check(ctx.engine, ctx.actor, numbers, dc, NAME,
                                        "Cultivation Check (Exorcist Designation)", modes=modes):
        return "confirmed", ""
    return "contested", f"failed against DC {dc}"


@effect("exorcist_name")
def name_intruder(ctx: Any, row: dict[str, Any]) -> None:
    from . import needle
    from .creature_kinds import matches, labels
    from .spirit_awakening import soul_gaze_reveal

    target = ctx.target
    if target is None:
        return
    soul_gaze_reveal(ctx, row)
    note(ctx.engine, NAME, ctx.actor,
         f"Name the Intruder: {target.display_name}'s recorded spiritual nature: {', '.join(sorted(labels(target))) or 'none recorded'}.", (target,))
    picked = needle.ask(ctx.engine, ctx.intent, needle.checkpoint_id(ctx.engine, "EXORCIST_DESIGNATION", target.entity_id),
                        ctx.actor, "choice:needle.exorcist.designation", list(CHOICE_DESIGNATIONS),
                        labels={d: DESIGNATION_LABELS[d] for d in CHOICE_DESIGNATIONS},
                        prompt=f"Name the Intruder: which designation do you assign to {target.display_name}?",
                        name="Name the Intruder", feature_id=NAME, allow_decline=True, default="decline")
    if picked:
        status, why = _designation_status(ctx, target, picked[0])
        # Plain wording: a contested designation is recorded as your diagnosis, not as fact.
        label = (f"Exorcist Designation: {picked[0]}" if status == "confirmed"
                 else f"Exorcist Designation: Contested ({picked[0]}) - you know the category is uncertain")
        ctx.engine._apply_condition(target, "condition:typed.exorcist_designation", NAME, ctx.actor.entity_id,
                                    expires_on="UNTIL_REMOVED",
                                    data={"designation": picked[0], "status": status, "label": label})
        if status == "confirmed":
            note(ctx.engine, NAME, ctx.actor, f"Name the Intruder: {target.display_name} is designated {picked[0]}.", (target,))
        else:
            note(ctx.engine, NAME, ctx.actor,
                 f"Name the Intruder: your designation of {target.display_name} as {picked[0]} is Contested ({why}); "
                 "the category is uncertain, so it is not yet a confirmed diagnosis.", (target,))
    # A designation does not change the target's actual creature kind.
    if not matches(target, MARKED_DESIGNATIONS):
        return
    if st.save(ctx, target, "cha"):
        _te().run_effects(ctx, [{"type": "mark", "applies_to": "target", "mark": "Resonance", "duration": {"kind": "until_removed"}}])
    else:
        # The mark exists for mechanics immediately; only its public visibility
        # is delayed until the exorcist's next turn.
        _te().run_effects(ctx, [{"type": "mark", "applies_to": "target", "mark": "Resonance", "duration": {"kind": "until_removed"}}])
        ctx.engine._apply_condition(target, LATENT_MARK, NAME, ctx.actor.entity_id, expires_on="UNTIL_REMOVED",
                                    data={"reveal_on_turn": ctx.actor.turns_started + 1,
                                          "label": "Resonance Mark concealed until the exorcist's next turn"})


@hook("turn_start")
def reveal_concealed_marks(engine: Any, actor: Any) -> None:
    for subject in engine.state.actors.values():
        for held in list(subject.conditions.values()):
            if (held.condition_id == LATENT_MARK and held.source_actor_id == actor.entity_id
                    and actor.turns_started >= int((held.data or {}).get("reveal_on_turn") or 0)):
                st.remove(engine, subject, held, "REVEALED")


@hook("presentation_hidden_conditions")
def conceal_mark_in_presentation(engine: Any, target: Any) -> set[str] | None:
    """Return condition instance IDs hidden by active presentation-only concealment.

    This viewer-neutral display seam never changes condition state or rules queries.
    """
    from .. import typed_executor as te
    hidden: set[str] = set()
    for latent in target.conditions.values():
        if latent.condition_id != LATENT_MARK:
            continue
        mark_id = te.mark_condition_id("Resonance", str(latent.source_actor_id or ""))
        hidden.add(latent.instance_id)
        hidden.update(row.instance_id for row in target.conditions.values() if row.condition_id == mark_id)
    return hidden or None


@hook("after_save_resolved")
def banish_native_dead(ctx: Any, subject: Any, ability: str, named: Any, failed: bool) -> None:
    from . import needle
    from .creature_kinds import matches
    from ..paid_relocation import activation

    if (not failed or subject is None or not subject.active
            or st.feature_of(ctx.action) != "tianxia.path.spirit_awakening.feature.mind_spike"
            or st.row(ctx.engine, ctx.actor, "banishment_strike") is None
            or ctx.actor.resources.get("resource:core.resonance", 0) < 2
            or not matches(subject, ("ghost", "undead soul", "restless dead"))
            or matches(subject, ("extraplanar spirit", "possession entity", "intruder"))):
        return
    picked = needle.ask(ctx.engine, ctx.intent, needle.checkpoint_id(ctx.engine, "BANISHMENT_STRIKE", subject.entity_id),
                        ctx.actor, "choice:needle.exorcist.banishment", ["use"], labels={"use": "Spend 2 Resonance: Banishment Strike"},
                        prompt=(f"Banishment Strike: after {subject.display_name} failed its save against your Mind Spike, spend 2 Resonance "
                                f"to make it attempt a Charisma saving throw against your Cultivation Save DC? "
                                "On a failed save, it is Frightened of you for 1 minute and repeats the save at the end of each turn; "
                                "on a success, it takes your ordinary Spiritual Pressure and becomes exposed to your sight. "
                                "Your Reaction is not used."),
                        name="Banishment Strike", feature_id=BANISH, allow_decline=True)
    if not picked:
        return
    with activation(ctx.engine, ctx.actor, BANISH, continuation=True):
        ctx.engine._spend_resource(ctx.actor, "resource:core.resonance", 2, BANISH)
        sub = st.context(ctx.engine, ctx.actor, st.feature_action(ctx.engine, ctx.actor, BANISH), [subject], ctx.numbers, ctx.intent)
        st.save(sub, subject, "cha", on_fail=[
            {"type": "condition", "applies_to": "target", "condition": "frightened", "duration": {"kind": "minutes", "amount": 1},
             "repeat_save": {"ability": "cha", "when": "end"}}], on_success=[
            {"type": "spiritual_pressure", "applies_to": "target"},
            {"type": "exposed", "applies_to": "target", "benefits": "hidden", "against": "you",
             "duration": {"kind": "until_start_of_your_next_turn"}}])


def _live_seals(engine: Any, actor: Any) -> list[Any]:
    """Binding Seal states whose Anchor still stands."""
    return [held for held in _seals(actor)
            if (anchor := engine.state.objects.get(str((held.data or {}).get("anchor") or ""))) is not None and not anchor.destroyed]


@hook("teleport_gate")
def seal_teleport(ctx: Any, start: Any, destination: Any) -> bool | None:
    """Printed: the Anchor means the target cannot teleport while it stands (it is Restrained)."""
    if _live_seals(ctx.engine, ctx.actor):
        note(ctx.engine, SEAL, ctx.actor, "Binding Seal prevents teleportation.")
        return False
    return None


@hook("condition_attempt")
def seal_states(ctx: Any, subject: Any, row: dict[str, Any]) -> bool | None:
    """Printed: a sealed creature cannot become invisible, incorporeal, or enter a Host."""
    if subject is not None and _live_seals(ctx.engine, subject) and str(row.get("condition") or "").lower() in ("invisible", "incorporeal", "possessing"):
        return False
    return None


@hook("masked_conditions")
def seal_visibility(engine: Any, attacker: Any, target: Any) -> dict[str, set[str]] | None:
    """Printed: an existing temporary Invisible on a sealed creature does not count while the Anchor stands."""
    out: dict[str, set[str]] = {}
    for subject in (attacker, target):
        if _live_seals(engine, subject):
            ids = {iid for iid, c in subject.conditions.items()
                   if c.condition_id == INVISIBLE and c.expires_on not in (None, "", "UNTIL_REMOVED")}
            if ids:
                out[subject.entity_id] = ids
    return out or None


@hook("movement_attempt")
def seal_distance(engine: Any, mover: Any, previous: Any, destination: Any, intent: Any) -> dict[str, Any] | None:
    """Printed: the sealed creature cannot move more than 30 feet from the Anchor."""
    for held in _live_seals(engine, mover):
        anchor = engine.state.objects[held.data["anchor"]]
        if engine.grid.distance_ft(anchor.position, destination) > 30:
            return {"stop": True, "source_id": SEAL, "label": "Binding Seal: remain within 30 feet of the Anchor"}
    return None


def _te() -> Any:
    from .. import typed_executor

    return typed_executor


def _name(condition: Any) -> str:
    return str(condition.condition_id or "").rsplit(".", 1)[-1].lower()


# ------------------------------------------------------------------------------------------------ Purification Bell, Grand Exorcism
@effect("exorcist_rite")
def rite(ctx: Any, row: dict[str, Any]) -> None:
    from . import needle

    engine, actor = ctx.engine, ctx.actor
    radius = int(row.get("radius_ft") or 30)
    name = str(row.get("name") or "Exorcism")
    from ..targeting import line_of_effect
    from ..target_knowledge import can_see
    near = [c for c in engine.state.actors.values() if c.active and engine._distance_actor_to_actor(actor, c) <= radius
            and line_of_effect(engine, actor, target=c)
            and (c is actor or can_see(engine, actor, c))]
    from .creature_kinds import matches
    hostiles = [c for c in near if c.team_id != actor.team_id
                and (not row.get("target_kinds") or matches(c, row["target_kinds"]))]
    # Printed: "6d8 Radiant or Psychic damage, chosen for each activation".
    kinds = ["radiant", "psychic"]
    picked = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "EXORCISM_DAMAGE", actor.entity_id), actor,
                        "choice:needle.exorcist.damage_type", kinds, labels={k: k.title() for k in kinds},
                        preferred=["radiant"], prompt=f"{name}: choose one damage type for this activation.",
                        name=name, feature_id=ctx.source)
    chosen_kind = picked[0] if picked else "radiant"
    save_row = copy.deepcopy(row["save"])
    for branch in ("on_fail", "on_success"):
        for child in save_row.get(branch) or []:
            if child.get("type") in ("damage", "half_damage"):
                child["damage_types"] = [chosen_kind]
    if hostiles:
        ids = [c.entity_id for c in hostiles]
        chosen = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, f"{name.upper().replace(' ', '_')}_TARGETS", actor.entity_id), actor,
                            f"choice:needle.exorcist.{row.get('topic') or 'rite'}_targets", ids, labels={c.entity_id: c.display_name for c in hostiles},
                            preferred=ids, minimum=0, maximum=len(ids), default="all", allow_decline=True, name=name, feature_id=ctx.source,
                            automatic_options=[c.entity_id for c in hostiles if can_see(engine, actor, c)],
                            prompt=(f"{name}: choose hostile creatures in the area to make the saving throw."
                                    if row.get("target_kinds") else f"{name}: which hostile creatures in the area does it answer? "
                                    "The GM confirms their spiritual kind."))
        for subject in [c for c in hostiles if c.entity_id in chosen]:
            if not subject.active:
                continue
            before = len(engine.events)
            sub = st.context(engine, actor, ctx.action, [subject], ctx.numbers, ctx.intent)
            _te().run_effects(sub, [copy.deepcopy(save_row)])
            if row.get("exposure") and subject.active and any(c.condition_id == INVISIBLE for c in subject.conditions.values()) and any(
                    e.event_type == "DAMAGE_COMMITTED" and subject.entity_id in e.target_ids for e in engine.events[before:]):
                _te().run_effects(sub, [{"type": "exposed", "applies_to": "target", "duration": {"kind": "until_end_of_your_next_turn"},
                                         "benefits": "invisible", "against": "anyone",
                                         "evidence": "Resonant Exposure: it becomes visible as a spiritual outline until the end of your next turn"}])
    for ally in [c for c in near if c.team_id == actor.team_id]:
        _purify(engine, actor, ally, ctx.intent, name, marks=bool(row.get("remove_marks")))


def _bell_mark_below(engine: Any, actor: Any, condition: Any) -> bool:
    """Purification Bell's purification benefit removes a hostile mark "with Source CL lower than yours".

    The printed limit is a real comparison, so the table enforces it whenever the mark's source
    authority is actually recorded (``condition_authority.source_cl`` reads the mark's own
    ``data["source_cl"]``, its source's compiled CL, or the source action's typed CL). A mark with
    no recorded authority keeps the rider behaviour -- the table offers it and the GM confirms the
    cause and the authority -- so an unrecorded mark is never silently stripped on a guess.
    """
    from .condition_authority import source_cl

    theirs = source_cl(engine, condition)
    if theirs is None:
        return True  # nothing recorded to compare: the GM's call, as the rider says
    return theirs < int(st.numbers(engine, actor).get("cl") or 1)


def _purify(engine: Any, actor: Any, ally: Any, intent: Any, name: str, *, marks: bool) -> None:
    """One purification benefit for a willing ally in the area: end one Frightened or Charmed, or (the Bell) remove one mark a hostile
    creature placed on it."""
    from . import needle

    options: dict[str, tuple[str, Any]] = {}
    for iid, condition in sorted(ally.conditions.items()):
        if _name(condition) in CALM:
            options[f"end:{iid}"] = (f"End {_name(condition).title()} on {ally.display_name}", condition)
        elif marks and condition.condition_id.startswith(_te().MARK_PREFIX):
            source = engine.state.actors.get(condition.source_actor_id or "")
            if source is not None and source.team_id != ally.team_id and _bell_mark_below(engine, actor, condition):
                label = condition.condition_id[len(_te().MARK_PREFIX):].rsplit(".", 1)[0].split(".")[0].replace("_", " ").title()
                options[f"mark:{iid}"] = (f"Remove {source.display_name}'s {label} Mark from {ally.display_name}", condition)
    if not options:
        return
    chosen = needle.ask(engine, intent, needle.checkpoint_id(engine, "PURIFY", ally.entity_id), actor, "choice:needle.exorcist.purify", list(options),
                        labels={k: v[0] for k, v in options.items()}, preferred=list(options)[:1], allow_decline=True, name=name,
                        feature_id=BELL if marks else GRAND, target_id=ally.entity_id,
                        prompt=f"{name}: one purification benefit for {ally.display_name}?")
    if chosen and chosen[0] in options:
        st.remove(engine, ally, options[chosen[0]][1], "PURIFIED")
        note(engine, BELL if marks else GRAND, actor, f"{name}: {options[chosen[0]][0]}.", (ally,))


# ---------------------------------------------------------------------------------------------------------- Seal of Binding
def _anchor_square(engine: Any, target: Any) -> Any:
    from ..gate2_runtime_models import Position

    occupied = set(engine._occupied_cells_except(target.entity_id)) | set(engine._actor_cells(target))
    taken = {(o.position.x, o.position.y) for o in engine.state.objects.values() if not o.destroyed}
    squares = list(offset_positions(engine, target.position, ((dx, dy) for dy in (-1, 0, 1) for dx in (-1, 0, 1) if dx or dy)))
    free = [p for p in squares if engine.grid.in_bounds((p.x, p.y)) and (p.x, p.y) not in engine.grid.blocked and (p.x, p.y) not in occupied
            and (p.x, p.y) not in taken]
    return free[0] if free else target.position  # "or attach it visibly to the Host"


@effect("exorcist_seal")
def seal(ctx: Any, row: dict[str, Any]) -> None:
    from ..gate2_runtime_models import RuntimeObjectState

    engine, actor, target = ctx.engine, ctx.actor, ctx.target
    if target is None or not target.active:
        return
    failed = st.save(ctx, target, "cha", on_success=[
        {"type": "condition", "applies_to": "target", "condition": "restrained", "duration": {"kind": "until_start_of_your_next_turn"},
         "evidence": "The target is Restrained until the start of your next turn"},
        {"type": "mark", "mark": "Resonance", "applies_to": "target", "duration": {"kind": "until_end_of_your_next_turn"},
         "evidence": "becomes Resonance Marked by you"}])
    if not failed or not target.active:
        return
    numbers = ctx.numbers or st.numbers(engine, actor)
    hp = 5 * int(numbers.get("pb") or 2)
    obj = RuntimeObjectState(object_id=f"{ANCHOR}{actor.entity_id}:{target.entity_id}:{engine.state.event_sequence}", object_kind="BINDING_SEAL_ANCHOR",
                             position=_anchor_square(engine, target), unattended=True, flammable=False, owner_id=actor.entity_id,
                             ac=int(numbers.get("save_dc") or 10), current_hp=hp, maximum_hp=hp, damage_immunities=("POISON", "PSYCHIC"),
                             component={"seal_target": target.entity_id, "label": "Binding Seal Anchor"})
    engine._update_object(obj, ctx.source, actor.entity_id)
    before = set(target.conditions)
    _te().block_condition(st.context(engine, actor, ctx.action, [target], ctx.numbers, ctx.intent),
                          {"type": "condition", "applies_to": "target", "condition": "restrained", "expires_on": "UNTIL_REMOVED",
                           "evidence": "While the Anchor remains: the target is Restrained"})
    restrained = [iid for iid in target.conditions if iid not in before]
    engine._apply_condition(target, SEAL_STATE, ctx.source, actor.entity_id, expires_on="UNTIL_REMOVED",
                            data={"anchor": obj.object_id, "restrained": restrained, "successes": 0,
                                  "label": "Binding Seal: Restrained while the Anchor stands; three successful repeat Charisma saves destroy it"})
    note(engine, SEAL, actor, f"A Binding Seal Anchor binds {target.display_name} (AC {obj.ac}, {hp} Hit Points).", (target,))


def _release(engine: Any, holder: Any, state: Any, reason: str, *, destroy: bool) -> None:
    anchor = engine.state.objects.get(str((state.data or {}).get("anchor") or ""))
    for iid in (state.data or {}).get("restrained") or []:
        condition = holder.conditions.get(iid)
        if condition is not None:
            st.remove(engine, holder, condition, reason)
    st.remove(engine, holder, state, reason)
    if destroy and anchor is not None and not anchor.destroyed:
        engine._update_object(anchor.model_copy(update={"destroyed": True, "current_hp": 0}), SEAL, state.source_actor_id)


def _seals(actor: Any) -> list[Any]:
    return [c for c in actor.conditions.values() if c.condition_id == SEAL_STATE]


@hook("turn_end")
def repeat_save(engine: Any, actor: Any) -> None:
    """Printed: "The target repeats the Charisma saving throw at the end of each of its turns. Three total successful repeat saves
    destroy the Anchor and end the effect."."""
    for state in _seals(actor):
        owner = engine.state.actors.get(state.source_actor_id or "")
        if owner is None or not actor.active:
            continue
        ctx = st.context(engine, owner, st.feature_action(engine, owner, SEAL), [actor], st.numbers(engine, owner))
        if st.save(ctx, actor, "cha"):
            continue
        successes = int(st.data_of(actor, state).get("successes") or 0) + 1
        st.set_data(actor, state, successes=successes)
        if successes >= 3:
            _release(engine, actor, state, "THREE_SUCCESSES", destroy=True)
            note(engine, SEAL, owner, f"{actor.display_name} breaks the Binding Seal (third successful save).")


@hook("event")
def anchor_destroyed(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """Printed: "Destroying it ends the binding but does not harm the target."."""
    if event_type != "OBJECT_UPDATED":
        return
    obj = (kwargs.get("payload") or {}).get("object") or {}
    if not str(obj.get("object_id") or "").startswith(ANCHOR) or not (obj.get("destroyed") or int(obj.get("current_hp") or 0) <= 0):
        return
    holder = engine.state.actors.get(str((obj.get("component") or {}).get("seal_target") or ""))
    if holder is None:
        return
    for state in _seals(holder):
        if (state.data or {}).get("anchor") == obj.get("object_id"):
            _release(engine, holder, state, "ANCHOR_DESTROYED", destroy=False)
