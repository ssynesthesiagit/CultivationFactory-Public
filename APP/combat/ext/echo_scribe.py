"""Echo Scribe (Spirit Awakening Tradition; rider lane C8, 2026-09-30: "i want everything we can automated").

Source: the owner's text (authority/typed_mechanics/rules_text.json; LocalSources/03_paths/Spirit/
Tianxia_Spirit_Awakening_Tradition_Compendium_R7.md "23. Echo Scribe"). No Spheres 5e or D&D 5.5e counterpart. Ownership: the
``spirit_tradition`` rows of combat/rules/feature_blocks.d/riders_c8.json (Marginal Correction keeps its ``d20_rewrite`` row).

What runs:
  * Written Rebuke (Reaction, 3 Resonance): a creature Resonance Marked by you within 60 feet declares an attack with a named technique
    (not a plain Attack-action strike or an Opportunity Attack) on you or an ally -- before the roll it makes a Charisma save: failed,
    4d8 + Wisdom modifier Psychic and Strike the Phrase (the attack has Disadvantage); success, half. Asked; the AI rebukes attacks on
    its side. Break the Command and Record the Lie are the GM's.
  * Chronicle of the Living Soul (Action, 10 Resonance, the scene): up to Proficiency Bonus Recorded Souls (you and your nearest allies
    first -- the AI's pick; asked). A Living Entry is recorded (up to PB, the oldest erased) when a Recorded Soul drops to 0 Hit Points,
    becomes Charmed or Frightened, or loses Concentration. Rewrite the Margin (once on each of your turns, 5 Resonance: 4 + 1 for the
    Chronicle kept internal) consumes one Entry: a Recorded Soul still on the field at 0 HP regains 2 x your Spirit Awakening CL Hit
    Points ("reduce damage that reduced the creature to 0 Hit Points by 2 x Spirit Awakening CL"), or its Charmed / Frightened is
    suppressed until the end of its next turn (restored then if its own time has not run out).
    Failed death saving throws also produce Living Entries. A dedicated Rewrite consumes one Entry and erases exactly
    one accrued failure through life_state.erase_failed_death_save, without healing or erasing other failures/successes.

Plug-in surface: effects echo_chronicle, echo_rewrite; hooks before_attack, event, compile_actions, candidate_allowed.
Shared helpers used: spirit_traditions (row/can_react/context/pick_creature/numbers/feature_action/suppress), life_state.restore_hp,
needle.ask.
"""

from __future__ import annotations

from ..paid_relocation import activation

from typing import Any

from . import effect, hook, note
from . import spirit_traditions as st

TRADITION = "tianxia.tradition.spirit.echo_scribe.feature."
REBUKE = TRADITION + "written_rebuke"
CHRONICLE = TRADITION + "chronicle_of_the_living_soul"
RESONANCE = "resource:core.resonance"
RECORDED = "condition:typed.recorded_soul"
ENTRY = "condition:typed.living_entry"
_REBUKE = "_c8_written_rebuke"


def _te() -> Any:
    from .. import typed_executor

    return typed_executor


def _remove(engine: Any, holder: Any, condition: Any, reason: str) -> None:
    for iid, held in list(holder.conditions.items()):
        if held is condition:
            holder.conditions.pop(iid)
            engine._append_event("CONDITION_REMOVED", held.source_definition_id, actor_id=held.source_actor_id,
                                 target_ids=(holder.entity_id,), payload={"condition_id": held.condition_id, "instance_id": iid, "reason": reason})


# ------------------------------------------------------------------------------------------------------------ Written Rebuke
def _named_technique(engine: Any, source_id: str) -> bool:
    action = engine.action_catalog.get(source_id)
    if "opportunity" in source_id.lower():
        return False
    if action is None:
        return True
    typed = (action.parameters or {}).get("typed") or {}
    return not typed.get("attack_action")  # a Factory basic Attack-action strike is not a named technique


# The other three printed triggers -- knowingly speaking a direct lie, using a verbal or spiritual command, and targeting you
# or an ally with a mental / emotional / memory / dream / possession effect -- are not wired here, deliberately. A direct lie
# is a speaker-belief-plus-intent fact that no inspected owner source records (APP/combat, APP/services), so it can never be
# inferred from an identifier, an action name or a disagreement; and neither a command-dependency receipt nor a
# "first target of the effect" save exists on this attack-only checkpoint. No substring guess is used in their place: those
# triggers, with Break the Command and Record the Lie, stay with the GM until their owning producer and consumer exist.


@hook("before_attack")
def written_rebuke(engine: Any, attacker: Any, defender: Any, intent: Any, context: dict[str, Any]) -> dict[str, Any] | None:
    source_id = str(context.get("source_id") or "")
    if attacker is None or defender is None or not _named_technique(engine, source_id):
        return None
    for scribe in engine.state.actors.values():
        if (not scribe.active or scribe.team_id == attacker.team_id or defender.team_id != scribe.team_id
                or st.row(engine, scribe, "written_rebuke") is None or not st.can_react(scribe) or scribe.resources.get(RESONANCE, 0) < 3
                or engine.grid.distance_ft(scribe.position, attacker.position) > 60
                or not _te().bears_mark(attacker, scribe.entity_id, "Resonance")):
            continue
        from . import needle

        chosen = needle.ask(engine, intent, needle.checkpoint_id(engine, "WRITTEN_REBUKE", attacker.entity_id, context.get("attack_index", 1)), scribe,
                            "choice:needle.echo_scribe.written_rebuke",
                            ["strike"],
                            labels={"strike": f"Strike the Phrase (3 Resonance, your Reaction): {attacker.display_name} makes a Charisma "
                                              f"save; on a failure its attack roll is made with Disadvantage"},
                            prompt=f"{attacker.display_name}, Resonance Marked by you, activates a technique against {defender.display_name}. "
                                   "Write against it? On a failed Charisma save it takes 4d8 + your Wisdom modifier Psychic damage, and Strike "
                                   "the Phrase makes its attack roll with Disadvantage (3 Resonance, your Reaction).",
                            preferred=["strike"], allow_decline=True, name="Written Rebuke", feature_id=REBUKE, target_id=attacker.entity_id)
        if not chosen:
            continue
        with activation(engine, scribe, REBUKE):
            engine._spend_resource(scribe, RESONANCE, 3, REBUKE)
            scribe.reaction_available = False
            engine._append_event("REACTION_RESOLVED", REBUKE, actor_id=scribe.entity_id, target_ids=(attacker.entity_id,),
                                 payload={"checkpoint": "ATTACK_DECLARED", "reaction_name": "Written Rebuke"})
            ctx = st.context(engine, scribe, st.feature_action(engine, scribe, REBUKE), [attacker], st.numbers(engine, scribe), intent)
            before = len(engine.events)
            # Resolve the Charisma save
            save_ctx = {"type": "save", "applies_to": "target", "ability": "cha",
                        "on_fail": [{"type": "damage", "applies_to": "target", "dice": {"count": 4, "sides": 8}, "formula": "key_ability_modifier",
                                     "damage_types": ["psychic"],
                                     "evidence": "It takes 4d8 + Wisdom modifier Psychic damage"}],
                        "on_success": [{"type": "half_damage", "applies_to": "target", "damage_types": ["psychic"]}]}
            _te().block_save(ctx, save_ctx)
            rolled = [e for e in engine.events[before:] if e.event_type == "SAVE_ROLLED" and e.actor_id == attacker.entity_id]
            pick = chosen[0] if chosen else None  # needle.ask answers with the list of chosen option ids
            if pick == "strike" and rolled and (rolled[-1].payload or {}).get("success") is False and attacker.active:
                return {"mode": "DISADVANTAGE"}  # Strike the Phrase: the triggering attack roll is made with Disadvantage
            return {}  # successful save: half damage already delivered; failed save without a live attacker: full damage delivered
    return None


# ----------------------------------------------------------------------------------------------------- Chronicle of the Living Soul
def _chronicler(engine: Any, soul: Any) -> Any:
    held = next((c for c in soul.conditions.values() if c.condition_id == RECORDED), None)
    return engine.state.actors.get(held.source_actor_id) if held is not None else None


@effect("echo_chronicle")
def chronicle(ctx: Any, row: dict[str, Any]) -> None:
    engine, actor = ctx.engine, ctx.actor
    for creature in engine.state.actors.values():
        for held in [c for c in creature.conditions.values() if c.condition_id == RECORDED and c.source_actor_id == actor.entity_id]:
            _remove(engine, creature, held, "REPLACED")
    count = int(ctx.numbers.get("pb") or 2)
    candidates = sorted((c for c in engine.state.actors.values() if c.active and c.team_id == actor.team_id),
                        key=lambda c: (c is not actor, engine.grid.distance_ft(actor.position, c.position), c.entity_id))
    from . import needle

    ids = [c.entity_id for c in candidates]
    chosen = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "CHRONICLE_SOULS", actor.entity_id), actor, "choice:needle.echo_scribe.souls",
                        ids, labels={c.entity_id: c.display_name for c in candidates}, preferred=ids[:count], minimum=1,
                        maximum=min(count, len(ids)), default="all", default_count=min(count, len(ids)), name="Chronicle of the Living Soul",
                        feature_id=CHRONICLE, prompt=f"Chronicle of the Living Soul: choose up to {count} creatures to become Recorded Souls.")
    for creature_id in chosen or ids[:count]:
        creature = engine.state.actors.get(creature_id)
        if creature is not None:
            engine._apply_condition(creature, RECORDED, ctx.source, actor.entity_id, expires_on="UNTIL_REMOVED",
                                    data={"label": f"Recorded Soul in {actor.display_name}'s Living Chronicle"})


def _entries(owner: Any) -> list[Any]:
    return sorted((c for c in owner.conditions.values() if c.condition_id == ENTRY and c.source_actor_id == owner.entity_id),
                  key=lambda c: c.applied_sequence)


def _record(engine: Any, owner: Any, soul: Any, kind: str, detail: str = "") -> None:
    held = _entries(owner)
    limit = int(getattr(owner, "proficiency_bonus", 2) or 2)
    while len(held) >= limit:
        _remove(engine, owner, held.pop(0), "ERASED")  # "Recording beyond the maximum erases the oldest Living Entry"
    engine._apply_condition(owner, ENTRY, CHRONICLE, owner.entity_id, expires_on="UNTIL_REMOVED",
                            data={"soul": soul.entity_id, "kind": kind, "detail": detail,
                                  "label": f"Living Entry: {soul.display_name} -- {kind.replace('_', ' ')}{(' (' + detail + ')') if detail else ''}"})


@hook("event")
def living_entries(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type not in ("DAMAGE_COMMITTED", "CONDITION_APPLIED", "CONCENTRATION_ENDED", "CHECK_ROLLED"):
        return
    payload = kwargs.get("payload") or {}
    targets = kwargs.get("target_ids") or ((kwargs.get("actor_id"),) if event_type == "CONCENTRATION_ENDED" else ())
    for target_id in targets:
        soul = engine.state.actors.get(str(target_id or ""))
        owner = _chronicler(engine, soul) if soul is not None else None
        if owner is None or not owner.active:
            continue
        if event_type == "DAMAGE_COMMITTED" and soul.current_hp <= 0 and int(payload.get("hp_damage") or 0) > 0:
            _record(engine, owner, soul, "reduced_to_0")
        elif event_type == "CONDITION_APPLIED" and payload.get("condition_id") in ("condition:typed.charmed", "condition:typed.frightened"):
            _record(engine, owner, soul, str(payload["condition_id"]).rsplit(".", 1)[-1], str(payload.get("instance_id") or ""))
        elif event_type == "CONCENTRATION_ENDED":
            _record(engine, owner, soul, "lost_concentration")
        elif event_type == "CHECK_ROLLED" and payload.get("skill") == "Death Saving Throw" and payload.get("success") is False:
            _record(engine, owner, soul, "failed_death_save")


@hook("compile_actions")
def rewrite_actions(info: dict[str, Any]) -> list[Any] | None:
    if CHRONICLE not in info["owned_ids"]:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    from ..action_variants import choice, with_variant
    out = []
    for kind, label, text in (("failed_death_save", "erase a failed death save", "erase one recorded failed death saving throw; this does not restore Hit Points or stabilize the creature"),
                              ("reduced_to_0", "restore from 0 Hit Points",
                               "a Recorded Soul still on the field at 0 Hit Points regains Hit Points equal to 2 x your Spirit Awakening CL"),
                              ("fear_or_charm", "suppress Charmed or Frightened",
                               "a Recorded Soul's recorded Charmed or Frightened is suppressed until the end of its next turn")):
        out.append(with_variant(ActionDefinition(
            source_definition_id=f"action:typed.{info['short']}.echo_rewrite.{kind}", display_name=f"Rewrite the Margin: {label}",
            owner_id=info["actor_id"], economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="ALLY_OR_SELF", range_ft=300,
            costs=(("resource:core.resonance", 5),),
            parameters={"typed": {"effects": [{"type": "echo_rewrite", "kind": kind, "applies_to": "target"}], "numbers": info["numbers"],
                                  "duration": {"kind": "instant"}, "riders": [], "source": CHRONICLE},
                        "expected_damage": 0, "echo_rewrite": kind,
                        "description": f"Chronicle of the Living Soul, once on each of your turns (5 Resonance: 4, +1 with the Chronicle kept "
                                       f"internal): consume one Living Entry -- {text}."}), f"action:typed.{info['short']}.echo_rewrite", "Rewrite the Margin", [choice("margin", kind, label)]))
    return out


def _matching_entry(owner: Any, soul: Any, kind: str) -> Any:
    kinds = ("charmed", "frightened") if kind == "fear_or_charm" else (kind,)
    return next((c for c in reversed(_entries(owner)) if (c.data or {}).get("soul") == soul.entity_id and (c.data or {}).get("kind") in kinds), None)


@hook("candidate_allowed")
def rewrite_gate(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    kind = ((action.parameters or {}) if action is not None else {}).get("echo_rewrite")
    if not kind:
        return None
    if actor.turn_flags.get("echo_rewrite"):
        return False
    target = engine.state.actors.get(next(iter(getattr(candidate, "target_ids", None) or ()), ""))
    if target is None:
        return None
    entry = _matching_entry(actor, target, kind)
    if entry is None:
        return False
    if kind == "failed_death_save":
        from .life_state import failed_death_saves
        if failed_death_saves(target) <= 0:
            return False
    if kind == "reduced_to_0" and target.current_hp > 0:
        return False
    if kind == "fear_or_charm" and not any(c.condition_id in ("condition:typed.charmed", "condition:typed.frightened") for c in target.conditions.values()):
        return False
    return None


@effect("echo_rewrite")
def rewrite(ctx: Any, row: dict[str, Any]) -> None:
    engine, actor, soul = ctx.engine, ctx.actor, ctx.target
    kind = str(row.get("kind") or "")
    if soul is None:
        return
    entry = _matching_entry(actor, soul, kind)
    if entry is None:
        return
    if kind == "failed_death_save":
        from .life_state import erase_failed_death_save
        if not erase_failed_death_save(engine, soul, ctx.source, actor.entity_id):
            return
        actor.turn_flags["echo_rewrite"] = True
        _remove(engine, actor, entry, "CONSUMED")
        note(engine, ctx.source, actor, f"Rewrite the Margin: one failed death save is erased from {soul.display_name}.", (soul,))
        return
    actor.turn_flags["echo_rewrite"] = True
    _remove(engine, actor, entry, "CONSUMED")
    if kind == "reduced_to_0":
        from . import life_state

        amount = 2 * int(ctx.numbers.get("cl") or 1)
        life_state.restore_hp(engine, soul, amount, ctx.source, actor.entity_id)
        note(engine, ctx.source, actor, f"Rewrite the Margin: the blow that dropped {soul.display_name} is written {amount} Hit Points lighter.", (soul,))
        return
    condition = next((c for _, c in sorted(soul.conditions.items()) if c.condition_id in ("condition:typed.charmed", "condition:typed.frightened")), None)
    if condition is not None:  # "suppress one Charmed, Frightened ... expression"
        st.suppress(engine, soul, condition, ctx.source, actor.entity_id, "Rewrite the Margin")

INK = TRADITION + "ink_remembers"
ECHO_ENTRY = "condition:typed.echo_entry"

@hook("event", nested=True)
def record_disturbance(engine, event_type, kwargs):
    if event_type != "CONDITION_APPLIED":
        return
    payload = kwargs.get("payload") or {}
    from ..target_knowledge import can_see
    from . import needle
    for owner in engine.state.actors.values():
        if st.row(engine, owner, "ink_remembers") is None or payload.get("condition_id") != _te().mark_condition_id("Resonance", owner.entity_id):
            continue
        for tid in kwargs.get("target_ids") or ():
            target = engine.state.actors.get(tid)
            if target is None or not can_see(engine, owner, target):
                continue
            categories = [name for name in ("charmed", "frightened", "possessed", "transformed", "disguised")
                          if any(c.condition_id == "condition:typed." + name for c in target.conditions.values())]
            if target.current_hp == 0 and target.active:
                categories.append("dying")
            if not categories:
                continue
            picked = needle.ask(engine, engine._active_intent, needle.checkpoint_id(engine, "RECORD_DISTURBANCE", target.entity_id), owner,
                                "choice:needle.echo_scribe.record_disturbance", categories,
                                labels={k: k.title() for k in categories}, preferred=categories[:1], allow_decline=True,
                                prompt=f"Record the Disturbance: record which visible spiritual category on {target.display_name}?",
                                name="Ink Remembers", feature_id=INK)
            if picked:
                engine._apply_condition(owner, ECHO_ENTRY, INK, owner.entity_id, expires_on="UNTIL_REMOVED",
                    data={"soul": target.entity_id, "category": picked[0],
                          "label": f"Echo Entry: {target.display_name} — {picked[0].title()}"})


@hook("event", nested=True)
def failed_death_entry(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    payload = kwargs.get("payload") or {}
    if event_type != "CHECK_ROLLED" or payload.get("skill") != "Death Saving Throw" or payload.get("success") is not False:
        return
    soul = engine.state.actors.get(kwargs.get("actor_id") or "")
    owner = _chronicler(engine, soul) if soul is not None else None
    if owner is not None and owner.active:
        _record(engine, owner, soul, "failed_death_save")
