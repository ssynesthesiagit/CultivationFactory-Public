"""Spirit Awakening's own core mechanic (worker w4-spirit, 2026-09-28): "ordinary Spiritual Pressure effects" and
Resonance Marks, the two universal building blocks every Spirit Awakening feature's printed text assumes but nothing
in combat/ ever built. Their definitions are not in the compiled records (the Path chapter's own appendix and the
PHB's "Spiritual Pressure"/"Resonance Marks" sections carry them; found on the Tabik drive's
INS2_R2_SOURCE/tianxia_paths_handoff_r2/01_PHB/Tianxia_PHB_Manuscript_v0_7_Subpaths_Inserted.md, "Resonance Marks" and
"Spiritual Pressure" headings).

Resonance Mark: "becomes Resonance Marked by you" already compiles as an ordinary ``mark`` effect (Mind Spike, Domain
Pressure) -- no new code needed; ``typed_executor.mark_condition_id("Resonance", owner)`` is the mark other features
(Spiritual Sense, Soul Vessel, Domain Manifestation) read via ``bears_mark``.

Spiritual Pressure ("choose one option unless the feature provides its own"): a sticky, no-cost, player-set choice of
which of the six ordinary effects a Spirit Awakener imposes (the record itself never says which -- BRIEF_WAVE2's "a
choice the sheet doesn't record" pattern, Golden Core Form-style, except this one is changeable any time since the
printed rule offers it fresh on every use, not once at character build). One ordinary Spiritual Pressure effect from a
given Spirit Awakener is active on a target at a time (id embeds the owner, like a mark); reapplying refreshes/
replaces it. Duration is "until the start of your next turn" (``START_OF_SOURCE_NEXT_TURN``) unless the effect that
imposed it says otherwise.

  Heavy Soul             -10 feet Speed (block_speed's own modifier machinery: refreshes, does not stack)
  Stilled Intent         the existing "reaction_denied" typed condition (no Reactions)
  Shaken Purpose         Disadvantage on the pressured creature's own next attack roll (attack_mode hook, consumed)
  Opened Spirit          Disadvantage on its next INT/WIS/CHA save against this Spirit Awakener's own features (save
                         hook, consumed)
  Repelled Heart         a visible marker + an honest GM rider: "cannot willingly move closer to you" needs the same
                         movement-candidate filtering Frightened gets in gate2_engine.py (forbidden to edit here), so
                         the table cannot enforce it; the GM applies it narrationally.
  Revealed Disturbance   an immediate log line reporting the target's HP band and whether it bears the owner's
                         Resonance Mark; exact HP totals and afflictions are not reported by the table.

Domain Pressure (CL5): each creature that fails is Frightened of you *until the end of your next turn* -- the source's
turn, not the target's holder-turn default block_condition would otherwise use -- reusing the same source-anchored
mark-expiry machinery typed_executor.expire_marks() already runs for any condition (not just a "mark") carrying
expires_on "END_OF_MARKER_NEXT_TURN" with a stamped marker_turn; this keeps the fix out of the shared typed_executor.py
file entirely. If immune to Frightened, the text substitutes two different ordinary Spiritual Pressure effects instead
(an "exceptional package" the printed rule itself exempts from the one-at-a-time limit): the player's chosen option
plus a fixed complementary second (Heavy Soul, or Stilled Intent if Heavy Soul is the one already chosen) since the
sheet has no way to record a second choice.

Mind Spike (CL5 rider): "when a creature already Resonance Marked by you fails against Mind Spike, you may also
impose one ordinary Spiritual Pressure effect on it" -- an unconditional, no-cost, no-downside bonus, so it is simply
applied whenever CL and the pre-existing mark allow it (reviewed_final's own if_marked + min_cl gate the pre-condition;
this module only supplies the "spiritual_pressure" effect that fires once those pass).

Domain Manifestation (CL15) reuses the same "spiritual_pressure" effect for its own "once on each of your turns, when
a creature in the Domain fails a save against one of your Path or Subpath features, impose one ordinary Spiritual
Pressure effect on it" (wired through its own MODIFIER in reviewed_final.d/spirit.json).
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, note

PRESSURE_PREFIX = "condition:typed.spirit_awakening_pressure."
PRESSURE_CHOICE = "condition:typed.spirit_awakening_pressure_choice"
PRESSURE_SHAKEN = "condition:typed.spirit_awakening_pressure_shaken."
PRESSURE_OPENED = "condition:typed.spirit_awakening_pressure_opened."
FRIGHTENED = "condition:typed.frightened"
RESONANCE_MARK = "Resonance"
SOUL_GAZE = "tianxia.path.spirit_awakening.feature.soul_gaze"

PRESSURE_LABELS = {
    "heavy_soul": "Heavy Soul (-10 feet Speed)",
    "stilled_intent": "Stilled Intent (no Reactions)",
    "shaken_purpose": "Shaken Purpose (Disadvantage on its next attack roll)",
    "opened_spirit": "Opened Spirit (Disadvantage on its next Int/Wis/Cha save against your Spirit Awakening features)",
    "repelled_heart": "Repelled Heart (cannot willingly move closer to you)",
    "revealed_disturbance": "Revealed Disturbance (learn its state)",
}
IMMORTAL_SPIRIT = "tianxia.path.spirit_awakening.feature.immortal_spirit"
SOVEREIGN_MARKER = "sovereign_identity_marker"
DEFAULT_PRESSURE = "shaken_purpose"
PRESSURE = "spiritual_pressure"
# What each ordinary effect actually does to the creature it lands on, and how long it lasts, in
# words a player who knows only basic D&D can read. Wording for the free Domain Manifestation clause
# and for any other place that has to say out loud which effect was chosen.
PRESSURE_SENTENCES = {
    "heavy_soul": f"Heavy Soul: its Speed is 10 feet slower",
    "stilled_intent": "Stilled Intent: it cannot take Reactions",
    "shaken_purpose": "Shaken Purpose: its next attack roll is at Disadvantage",
    "opened_spirit": "Opened Spirit: its next Intelligence, Wisdom or Charisma saving throw against your Spirit Awakening "
                     "features is at Disadvantage",
    "repelled_heart": "Repelled Heart: it cannot willingly move closer to you, which the GM has to enforce",
    "revealed_disturbance": "Revealed Disturbance: you learn only its health band (0 Hit Points; Bloodied: half its "
                            "maximum Hit Points or less; or not Bloodied: more than half) and whether it bears your "
                            "Resonance Mark (your spiritual mark)",
}
PRESSURE_LASTS = "It lasts until the start of your next turn."


@hook("effect_choice")
def spiritual_pressure_options(effect_type: str, actor: Any) -> list[str] | None:
    """The six ordinary Spiritual Pressure options, the actor's standing choice first so it is the
    answer offered by default. Only for the ``spiritual_pressure`` effect; anything else is None, so
    a caller that has no answer asks nothing."""
    if str(effect_type or "") != PRESSURE:
        return None
    preferred = chosen_pressure(actor)
    return [preferred, *[key for key in PRESSURE_LABELS if key != preferred]]


@hook("effect_text")
def spiritual_pressure_words(effect_type: str, option: str, target_name: str) -> str | None:
    """One plain sentence naming the chosen effect, who it lands on and how long it lasts, for a log
    line or a menu option. ``target_name`` is the creature's display name."""
    if str(effect_type or "") != PRESSURE:
        return None
    what = PRESSURE_SENTENCES.get(str(option or ""), PRESSURE_LABELS.get(str(option or ""), str(option or "")))
    return f"{what} ({target_name}). {PRESSURE_LASTS}"


@hook("compile_actions")
def sovereign_identity_action(info: dict[str, Any]) -> list[Any] | None:
    """Seal ownership of Immortal Spirit into the actor bundle for source-aware condition checks."""
    if IMMORTAL_SPIRIT not in info["owned_ids"]:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    return [ActionDefinition(source_definition_id=f"action:typed.{info['short']}.immortal_spirit.sovereign_identity",
                             display_name="Sovereign Identity", owner_id=info["actor_id"],
                             economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF",
                             parameters={"typed": {"effects": [], "numbers": info["numbers"],
                                                    "duration": {"kind": "instant"}, "riders": []},
                                         "sovereign_identity_marker": True,
                                         "description": (
                                             "Automatic protection for you; no Action or resource cost. While you have Immortal Spirit, "
                                             "ordinary effects and effects from a lower cultivation level (Source CL) cannot Charm or "
                                             "Frighten you, possess you, permanently change your memories or identity, consume, destroy, "
                                             "imprison or redirect your whole soul, block its passage, or permanently break its anchoring "
                                             "bond against your will. Equal or higher authority follows its printed procedure; without "
                                             "one, make a Wisdom save against its DC, or contest its source with your cultivation ability "
                                             "check (Cultivation Check) if it has no DC.")})]


def _has_sovereign_identity(engine: Any, actor: Any) -> bool:
    return any(((engine.action_catalog.get(action_id).parameters or {}).get(SOVEREIGN_MARKER))
               for action_id in actor.action_ids if engine.action_catalog.get(action_id) is not None)


ORDINARY_SOURCE_CL = 0  # "an ordinary effect": no cultivation authority behind it at all


def _cl_value(value: Any) -> int | None:
    """A recorded CL (1+), or None. Missing, blank or placeholder 0 values are not a Source CL."""
    try:
        return int(value) if value not in (None, "") and int(value) >= 1 else None
    except (TypeError, ValueError):
        return None


def _bundle(engine: Any, actor_id: str) -> dict[str, Any] | None:
    return next((row for row in getattr(engine, "typed_bundle_documents", ()) or () if row.get("actor_id") == actor_id), None)


def _attempt_source_cl(ctx: Any) -> int | None:
    """Source CL of the attempted effect, action-first like end_effect.source_cl.

    1. the delivering action's compiled typed numbers (techniques, path riders and summon attacks carry their own CL);
    2. else the acting creature's compiled bundle CL;
    3. else, for a summoned creature, its summoner's bundle CL.
    A creature with no typed bundle and no summoner, using an action with no compiled CL, is an ordinary source
    (ORDINARY_SOURCE_CL). A typed source whose CL cannot be found returns None: unknown authority is never treated
    as lower, so the effect uses its printed procedure (its normal save).
    """
    cl = _cl_value((getattr(ctx, "numbers", None) or {}).get("cl"))
    if cl is not None:
        return cl
    actor = getattr(ctx, "actor", None)
    if actor is None:
        return None
    own = _bundle(ctx.engine, actor.entity_id)
    if own is not None and _cl_value(own.get("cl")) is not None:
        return _cl_value(own.get("cl"))
    summoner = (getattr(actor, "summon", None) or {}).get("owner")
    if summoner:
        return _cl_value((_bundle(ctx.engine, str(summoner)) or {}).get("cl"))
    return ORDINARY_SOURCE_CL if own is None else None


def _sovereign_cl(engine: Any, actor: Any) -> int | None:
    """The Immortal Spirit owner's own CL: the feature's compiled numbers, else the owner's bundle CL."""
    for action_id in actor.action_ids:
        action = engine.action_catalog.get(action_id)
        parameters = (getattr(action, "parameters", None) or {}) if action is not None else {}
        if parameters.get(SOVEREIGN_MARKER):
            cl = _cl_value(((parameters.get("typed") or {}).get("numbers") or {}).get("cl"))
            if cl is not None:
                return cl
    return _cl_value((_bundle(engine, actor.entity_id) or {}).get("cl"))


@hook("candidate_allowed")
def hide_sovereign_marker(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if (getattr(action, "owner_id", None) == actor.entity_id and
            ((getattr(action, "parameters", None) or {}).get(SOVEREIGN_MARKER))):
        return False
    return None


@hook("condition_attempt")
def sovereign_identity_blocks_lower_conditions(ctx: Any, subject: Any, effect: Any) -> bool | None:
    """Sovereign Identity: "An ordinary effect and any effect with lower Source CL cannot, against your will: Charm or
    Frighten you". Equal- or higher-Source-CL effects keep their printed procedure (the normal save already rolled).

    Against your will: a Charm/Frighten the owner imposes on itself with its own action is its own choice and is not
    refused. The table has no consent prompt for another creature's effect, so those are always treated as unwilling.
    """
    name = str((effect or {}).get("condition") or "").lower()
    if (name not in ("charmed", "frightened") or subject is None or getattr(ctx.actor, "entity_id", None) == subject.entity_id or
            not _has_sovereign_identity(ctx.engine, subject)):
        return None
    source, mine = _attempt_source_cl(ctx), _sovereign_cl(ctx.engine, subject)
    if source is not None and mine is not None and source < mine:
        return False
    return None


def _pressure_condition_id(owner: str) -> str:
    return f"{PRESSURE_PREFIX}{owner}"


def chosen_pressure(actor: Any) -> str:
    """The player's (or the built-in AI's default) standing choice of which ordinary Spiritual Pressure effect a
    Spirit Awakener imposes; a free toggle (BRIEF_WAVE2), not a build choice, since the printed rule re-offers it on
    every use rather than fixing it once."""
    found = next((str((c.data or {}).get("choice")) for c in actor.conditions.values() if c.condition_id == PRESSURE_CHOICE), None)
    return found if found in PRESSURE_LABELS else DEFAULT_PRESSURE


@hook("compile_actions")
def pressure_choice_actions(info: dict[str, Any]) -> list[Any] | None:
    """Free player-only toggles, one per ordinary Spiritual Pressure option, offered whenever the character owns a
    Spirit Awakening feature that can impose one (so far: Domain Pressure, Mind Spike, Domain Manifestation)."""
    owned = info["owned_ids"]
    keeps = ("tianxia.path.spirit_awakening.feature.domain_pressure", "tianxia.path.spirit_awakening.feature.mind_spike",
             "tianxia.path.spirit_awakening.feature.domain_manifestation")
    if not any(feature_id in owned for feature_id in keeps):
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    return [ActionDefinition(
        source_definition_id=f"action:typed.{info['short']}.spirit_awakening_pressure.{key}", display_name=f"Spiritual Pressure: {label}",
        owner_id=info["actor_id"], economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF",
        parameters={"setting_only": True, "typed": {"effects": [{"type": "spiritual_pressure_choice", "choice": key}], "numbers": info["numbers"],
                              "duration": {"kind": "instant"}, "riders": []}, "expected_damage": 0, "player_only": True})
        for key, label in PRESSURE_LABELS.items()]


@effect("spiritual_pressure_choice")
def spiritual_pressure_choice(ctx: Any, eff: dict[str, Any]) -> None:
    ctx.engine._remove_condition(ctx.actor, PRESSURE_CHOICE, ctx.source)
    ctx.engine._apply_condition(ctx.actor, PRESSURE_CHOICE, ctx.source, ctx.actor.entity_id, expires_on="UNTIL_REMOVED",
                                data={"choice": eff.get("choice"), "label": f"Spiritual Pressure: {PRESSURE_LABELS.get(str(eff.get('choice')), '')}"})


def _apply_one_pressure(ctx: Any, subject: Any, owner: str, option: str, *, slot: str = "") -> None:
    """Impose exactly one named ordinary Spiritual Pressure effect on ``subject`` from ``owner``, clearing whichever
    mechanism (if any) an earlier one in the same ``slot`` used, so reapplying always refreshes rather than stacking
    (the printed "does not stack multiple ordinary options" rule). ``source_actor_id`` is always the real owner (so
    START_OF_SOURCE_NEXT_TURN expiry, which matches on the real acting actor, still fires); ``slot`` only varies the
    condition id, so Domain Pressure's two-effect "exceptional package" can hold both at once without either clearing
    the other."""
    from .. import typed_executor as te

    tag = f"{owner}{slot}"
    for iid, condition in list(subject.conditions.items()):
        if condition.condition_id in (PRESSURE_SHAKEN + tag, PRESSURE_OPENED + tag, _pressure_condition_id(tag)):
            ctx.engine._remove_condition(subject, condition.condition_id, ctx.source)
    from .condition_events import drop_condition
    for held in list(subject.conditions.values()):
        if held.condition_id == "condition:typed.no_approach" and (held.data or {}).get("pressure_slot") == tag:
            drop_condition(ctx.engine, subject, held.instance_id, ctx.source)
    # block_speed's own _modifier helper already refreshes (removes-then-adds with a MODIFIER_REMOVED event) a stale
    # speed_ft modifier from this same source, so heavy_soul needs no separate cleanup here.
    ctx.engine._apply_condition(subject, _pressure_condition_id(tag), ctx.source, owner, expires_on="START_OF_SOURCE_NEXT_TURN",
                                data={"option": option, "label": f"Spiritual Pressure: {PRESSURE_LABELS.get(option, option)}"})
    if option == "heavy_soul":
        te.block_speed(ctx, {"type": "speed", "applies_to": "target", "flat": -10, "expires_on": "START_OF_SOURCE_NEXT_TURN",
                             "evidence": "Heavy Soul: the target's Speed is reduced by 10 feet."})
    elif option == "stilled_intent":
        te.block_condition(ctx, {"type": "condition", "applies_to": "target", "condition": "reaction_denied",
                                 "expires_on": "START_OF_SOURCE_NEXT_TURN", "evidence": "Stilled Intent: the target cannot take Reactions."})
    elif option == "shaken_purpose":
        ctx.engine._apply_condition(subject, PRESSURE_SHAKEN + tag, ctx.source, owner, expires_on="START_OF_SOURCE_NEXT_TURN", data={})
    elif option == "opened_spirit":
        ctx.engine._apply_condition(subject, PRESSURE_OPENED + tag, ctx.source, owner, expires_on="START_OF_SOURCE_NEXT_TURN", data={})
    elif option == "repelled_heart":
        ctx.engine._apply_condition(subject, "condition:typed.no_approach", ctx.source, owner,
            expires_on="START_OF_SOURCE_NEXT_TURN", data={"pressure_slot": tag,
            "label": f"Repelled Heart from {ctx.actor.display_name}: cannot willingly move closer to them until the start of {ctx.actor.display_name}'s next turn"})
    elif option == "revealed_disturbance":
        marked = te.bears_mark(subject, owner, RESONANCE_MARK)
        band = "at 0 HP" if subject.current_hp <= 0 else "Bloodied" if subject.current_hp <= subject.maximum_hp // 2 else "not Bloodied"
        note(ctx.engine, ctx.source, ctx.actor,
             f"Revealed Disturbance: {subject.display_name} is {band}; "
             f"{'has' if marked else 'does not have'} your Resonance Mark.", (subject.entity_id,))


@effect("spiritual_pressure")
def spiritual_pressure(ctx: Any, eff: dict[str, Any]) -> None:
    subject = ctx.target
    if subject is None or not subject.active:
        return
    owner = ctx.actor.entity_id
    chosen = chosen_pressure(ctx.actor)
    if eff.get("different"):
        # The second effect of a printed "two different ordinary Spiritual Pressure effects" package (rider lane C8: Edict of
        # Perfect Witness): the same complement Domain Pressure's package uses, in its own slot so both stand together.
        _apply_one_pressure(ctx, subject, owner, "stilled_intent" if chosen == "heavy_soul" else "heavy_soul", slot=".package2")
        return
    _apply_one_pressure(ctx, subject, owner, str(eff.get("option") or chosen))


@effect("domain_pressure_fear")
def domain_pressure_fear(ctx: Any, eff: dict[str, Any]) -> None:
    """Domain Pressure's failed-save branch: Frightened until the end of the Spirit Awakener's own next turn (not the
    target's), plus a Resonance Mark; a target immune to Frightened instead suffers two different ordinary Spiritual
    Pressure effects (the printed "exceptional pressure package")."""
    from .. import typed_executor as te

    subject = ctx.target
    if subject is None or not subject.active:
        return
    owner = ctx.actor.entity_id
    if te.condition_immune(ctx.engine, subject, "frightened"):
        primary = chosen_pressure(ctx.actor)
        secondary = "stilled_intent" if primary == "heavy_soul" else "heavy_soul"
        _apply_one_pressure(ctx, subject, owner, primary)
        # The second of the exceptional package uses its own condition-id slot so it does not collide with (or get
        # cleared by) the first -- these two coexist as one package, unlike an ordinary single pressure effect.
        _apply_one_pressure(ctx, subject, owner, secondary, slot=".package2")
        ctx.rider(f"Domain Pressure: {subject.entity_id} is immune to Frightened -- two ordinary Spiritual Pressure "
                 f"effects imposed instead ({PRESSURE_LABELS[primary]}; {PRESSURE_LABELS[secondary]}).")
        return
    from .. import typed_reactions

    if typed_reactions.offer_condition_gained(ctx.engine, subject, ctx.actor, "frightened"):
        return
    ctx.engine._apply_condition(subject, FRIGHTENED, ctx.source, owner, expires_on="END_OF_MARKER_NEXT_TURN",
                                data={"marker_turn": int(ctx.actor.turns_started)})
    te.block_mark(ctx, {"type": "mark", "mark": RESONANCE_MARK, "applies_to": "target", "duration": {"kind": "until_end_of_your_next_turn"},
                        "evidence": "becomes Resonance Marked by you"})


@hook("attack_mode")
def shaken_purpose_attack(ctx: Any, target: Any) -> str | None:
    """Shaken Purpose: Disadvantage on the pressured creature's own next attack roll, consumed the first time it
    attacks (the same shape as tabik_unmaking.palm_con_save)."""
    held = [iid for iid, c in ctx.actor.conditions.items() if c.condition_id.startswith(PRESSURE_SHAKEN)]
    if not held:
        return None
    condition = ctx.actor.conditions.pop(held[0])
    ctx.engine._append_event("CONDITION_REMOVED", condition.source_definition_id, actor_id=condition.source_actor_id,
                             target_ids=(ctx.actor.entity_id,), payload={"condition_id": condition.condition_id, "instance_id": held[0], "reason": "CONSUMED"})
    return "DISADVANTAGE"


@hook("save")
def opened_spirit_save(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    """Opened Spirit: Disadvantage on the pressured creature's next Int/Wis/Cha save against the same Spirit
    Awakener's own features (only), consumed once."""
    if str(ability or "").upper()[:3] not in ("INT", "WIS", "CHA"):
        return None
    held = [(iid, c) for iid, c in subject.conditions.items() if c.condition_id.startswith(PRESSURE_OPENED) and c.source_actor_id == ctx.actor.entity_id]
    if not held:
        return None
    iid, condition = held[0]
    subject.conditions.pop(iid)
    ctx.engine._append_event("CONDITION_REMOVED", condition.source_definition_id, actor_id=condition.source_actor_id,
                             target_ids=(subject.entity_id,), payload={"condition_id": condition.condition_id, "instance_id": iid, "reason": "CONSUMED"})
    return {"bonus": 0, "modes": ["DISADVANTAGE"]}


@hook("compile_action")
def soul_gaze_target_kind(action: Any, info: dict[str, Any]) -> Any:
    """An owned diagnosis selects any creature, without making it a hostile attack."""
    typed = (action.parameters or {}).get("typed") or {}
    if SOUL_GAZE in info["owned_ids"] and str(typed.get("source") or "").split("#")[0] == SOUL_GAZE:
        return action.model_copy(update={"target_kind": "ANY_CREATURE"})
    return None


@hook("target_eligibility")
def soul_gaze_target_eligibility(engine: Any, actor: Any, target: Any, action: Any) -> bool | None:
    """FIX15's owned sight predicate, now before the core visibility filters.

    A source may explicitly record total spiritual concealment on a condition:
    data['total_spiritual_concealment'] = 1, with its source_definition_id.
    No existing producer is inferred from condition names, Hidden or Invisible.
    This contract only defeats the unseen own-mark exception; protected details
    remain subject to their source rules even for a visible creature.
    """
    typed = (action.parameters or {}).get("typed") or {}
    if action.owner_id != actor.entity_id or str(typed.get("source") or "").split("#")[0] != SOUL_GAZE:
        return None
    from ..target_knowledge import can_see
    from ..typed_executor import bears_mark

    if target.entity_id == actor.entity_id or can_see(engine, actor, target):
        return True
    if not bears_mark(target, actor.entity_id, RESONANCE_MARK):
        return False
    return not any(c.source_definition_id and (c.data or {}).get("total_spiritual_concealment") == 1
                   for c in target.conditions.values())


@effect("soul_gaze_reveal")
def soul_gaze_reveal(ctx: Any, eff: dict[str, Any]) -> None:
    """Soul Gaze: the recorded diagnosis surfaces as a plain notice
    naming what the printed text says it learns and the table can actually compute (HP band, resistances/immunities/
    vulnerabilities, Resonance Mark status); Soul Anchor, Bond and Nature detail stay GM-adjudicated."""
    from .. import typed_executor as te

    subject = ctx.target
    # FIX15: recover only the explicit self choice omitted by typed execution.
    if subject is None and ctx.intent is not None and ctx.actor.entity_id in ctx.intent.target_ids:
        subject = ctx.actor
    if subject is None:
        return
    owner = ctx.actor.entity_id
    resist = {*subject.damage_resistances, *(str(m.value) for m in subject.modifiers.values() if m.target_field == "damage_resistance")}
    immune = {str(m.value) for m in subject.modifiers.values() if m.target_field == "damage_immunity"}
    marked = te.bears_mark(subject, owner, RESONANCE_MARK)
    from . import run
    from .placed import notice

    # Other sources' own conditions on this creature answer for themselves (for example a Nightmare
    # Scar's Predatory Trace): each returns one readable sentence, and the notice is otherwise unchanged.
    extra = [str(line) for line in run("diagnosis_reveal", ctx, subject) if line]
    notice(ctx, f"Soul Gaze on {subject.display_name}: Hit Points {subject.current_hp}/{subject.maximum_hp}; "
             f"Resistances: {', '.join(sorted(resist)) or 'none'}; Immunities: {', '.join(sorted(immune)) or 'none'}; "
             f"{'Your Resonance Mark is present (a spiritual link you placed on this creature)' if marked else 'No Resonance Mark from you'}."
             + (f" {' '.join(extra)}" if extra else ""))
