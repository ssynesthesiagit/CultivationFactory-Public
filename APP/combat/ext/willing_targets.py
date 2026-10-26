"""Shared opt-in selection/consent for one willing creature within a printed range.

Used by Muffle Footfall, Press Seal, Harmonic Healing Tone, Sky Mantle and Second Silhouette.
``choose_willing`` runs its nested effects only on the
caster's chosen, consenting recipient. It uses the documented choice_options
transport, without spending a Reaction. Old rows and unowned abilities are inert.
An AI recipient accepts an allied caster and declines a hostile caster; a player
can choose otherwise. Engines without choice transport safely choose self only.
``target_only`` retains the action's already selected target and asks that target
for consent. ``optional_recipient`` asks whether to apply a nested benefit when
its condition_id is present, even with one option; decline runs no nested effect.
``allow_hostile_target`` on a targeted ``choose_willing`` row adds a non-ally
candidate variant at the same range/cost. Its effects still require recipient
consent. Rows without this flag retain their original menus and saved behavior.
``unwilling_save`` adds the printed refusal path of a save-gated benefit ("If the
target is unwilling, it makes a Wisdom saving throw. A willing target may choose
to fail."): a target that refuses makes that save against the caster's own Cultivation
Save DC and the row's effects land on a failure, while the willing branch of that row drops the
printed repeat saves ("At the end of each of its turns, an unwilling target repeats
the saving throw"), which a willing target never had to make. Rows without it keep
the consent-only behaviour, refusal ending the effect, and every field of their own
effects untouched -- including any ``repeat_save`` such an effect carries by itself.
``variant_suffix`` names the non-ally button this module adds (Soul-Stirring Refrain:
"(any creature)", because its unwilling target may fail the printed save); absent, the
shared "(willing creature)" wording is used. ``consent_text`` adds the printed sentence
that explains what accepting means, so the question a player reads is the printed one.
Wax's compile_actions hook also calls the public ``willing_non_allies`` helper
for its newly supplied Press Seal action: the hook info catalog contains only
the compiler's original actions, not other compile_actions hook results.
Shadow's match_start hook uses the same helper for supplemental saved willing
marks; both variants remain gated by ownership of the original legacy action.
``asks_consent`` is the same transport reduced to one accept-or-refuse question,
for a plug-in that has to read a recipient's answer outside a typed effect (see
``asks_consent``'s own docstring for its user).
"""

from dataclasses import replace

from . import effect, hook


@hook("compile_actions")
def willing_non_allies(info):
    """Opt-in any-willing-creature targeting, preserving the ally/self action."""
    actions = []
    for action in info["actions"]:
        typed = (action.parameters or {}).get("typed") or {}
        rows = [row for row in typed.get("effects") or []
                if row.get("type") == "choose_willing" and row.get("target_only") and row.get("allow_hostile_target")]
        if action.target_kind != "ALLY_OR_SELF" or not rows:
            continue
        suffix = next((str(row["variant_suffix"]) for row in rows if row.get("variant_suffix")), " (willing creature)")
        # Some printed "one willing creature" records also admit neutrals.
        # Opt in explicitly: old consumers retain their enemy-only variant.
        neutral = any(row.get('allow_neutral_target') for row in rows)
        actions.append(action.model_copy(update={
            "source_definition_id": action.source_definition_id + "#willing_non_ally",
            "display_name": action.display_name + suffix,
            "target_kind": "ANY_CREATURE" if neutral else "HOSTILE_ENTITY",
            "parameters": {**action.parameters, **({'willing_non_allies_only': True} if neutral else {})}}))
    return actions or None


@hook('candidate_allowed')
def nonally_willing_candidates(engine, actor, candidate, action):
    """Filter only the neutral-inclusive clone; preserve the original ally row."""
    if action is None or not action.parameters.get('willing_non_allies_only'):
        return None
    if not candidate.target_ids:
        return None  # native lazy target/menu roots keep their complete expansion
    from ..relations import relation, ALLY
    return all(
        relation(engine, actor, engine.state.actors[aid]) != ALLY for aid in candidate.target_ids)


@hook("choice_options")
def willing_options(engine, intent, checkpoint, reactor_id, choice_id, context):
    if choice_id not in ("choice:willing.targets", "choice:willing.consent", "choice:willing.optional") or not context.get("willing_options"):
        return None
    return {"option_ids": context["willing_options"], "minimum_selections": 1,
            "maximum_selections": 1, "allow_decline": True, "automatic_use": True,
            "preferred_option_ids": context["preferred"]}


def _pick(engine, intent, chooser, kind, options, labels, preferred, prompt, ability, actor_id):
    """Put one ``choice:willing.*`` question to ``chooser`` and read the answer. The single place this
    transport is called, so ``choose_willing`` and ``asks_consent`` cannot drift apart."""
    if intent is None or not hasattr(engine, "_gate4_reaction_cache"):
        return preferred[:1]
    prefix = "TYPED:" if chooser.entity_id in getattr(engine, "typed_ask_reactors", ()) else "CHOICE:"
    checkpoint = f"{prefix}{ability} {kind}@{engine.state.event_sequence}:{chooser.entity_id}"
    context = {"actor_id": actor_id, "target_id": chooser.entity_id,
               "ability": ability, "willing_options": options,
               "labels": labels, "preferred": preferred, "prompt": prompt}
    decision = engine._reaction_decision(intent, checkpoint, chooser.entity_id,
                                         f"choice:willing.{kind}", context=context)
    if decision is None:
        return preferred[:1]
    return [] if decision.selection == "DECLINE" else list(decision.option_ids)


def _choose(ctx, chooser, kind, options, labels, preferred, prompt):
    return _pick(ctx.engine, ctx.intent, chooser, kind, options, labels, preferred, prompt,
                 ctx.action.display_name, ctx.actor.entity_id)


def asks_consent(engine, intent, subject, ability, prompt, *, prefer_accept, asker=None):
    """Whether ``subject`` consents to a beneficial offer named by ``ability``. True only on an explicit accept.

    The shared consent transport of this module, for a plug-in that has to read a recipient's answer outside a
    typed effect row. "Willing" and "unwilling" in a printed rule are the affected creature's answer, so it is
    asked of that creature rather than guessed from which side it stands on: an AI-controlled subject decides
    for itself (an allied asker is accepted and a hostile one refused -- the default ``choose_willing`` already
    uses), and a player controlling it is asked, on its own turn and on somebody else's. With no choice
    transport at all (a headless probe) ``prefer_accept`` stands.

    ``asker`` is the creature making the offer; it rides the question as its subject so the table names who is
    asking, and defaults to ``subject`` itself.

    Used by combat/ext/thread_correction.py for Puppet-Line Correction ("If the creature is willing, it adds your
    Proficiency Bonus to the roll. If the creature is unwilling, it makes a Wisdom saving throw.") and for Borrow
    the Ally's Arm ("A willing ally connected to one of your Thread Lines...").
    """
    return _pick(engine, intent, subject, "consent", ["accept", "refuse"],
                 {"accept": "Accept", "refuse": "Refuse"},
                 ["accept" if prefer_accept else "refuse"], prompt, ability,
                 asker.entity_id if asker is not None else subject.entity_id) == ["accept"]


@effect("choose_willing")
def choose_willing(ctx, row):
    """Select one active creature, ask its consent, then run target-scoped effects."""
    from ..typed_executor import run_effects

    available = sorted((a for a in ctx.engine.state.actors.values() if a.active and
                        ctx.engine._distance_actor_to_actor(ctx.actor, a) <= int(row["range_ft"])),
                       key=lambda a: (a is not ctx.actor, a.entity_id))
    selected = [(ctx.target or ctx.actor).entity_id] if row.get("target_only") else _choose(ctx, ctx.actor, "targets", [a.entity_id for a in available],
                       {a.entity_id: a.display_name for a in available}, [ctx.actor.entity_id],
                       f"{ctx.actor.display_name} uses {ctx.action.display_name}: choose yourself or one willing creature.")
    if not selected:
        return
    subject = next(a for a in available if a.entity_id == selected[0])
    scoped = replace(ctx, targets=[subject], target=subject)
    if subject is not ctx.actor:
        accepted = _choose(ctx, subject, "consent", ["accept", "refuse"],
                           {"accept": f"Accept: {ctx.actor.display_name} uses {ctx.action.display_name} on {subject.display_name}",
                            "refuse": f"Refuse: {subject.display_name} is not affected by {ctx.action.display_name}"},
                           ["accept" if subject.team_id == ctx.actor.team_id else "refuse"],
                           f"{ctx.actor.display_name} uses {ctx.action.display_name} on {subject.display_name}: accept or refuse?"
                           + (f" {row['consent_text']}" if row.get("consent_text") else ""))
        if accepted != ["accept"]:
            save = row.get("unwilling_save")
            if save:
                run_effects(scoped, [{"type": "save", "ability": str(save.get("ability") or "CON").upper(), "applies_to": "target",
                                      "evidence": str(save.get("evidence") or ""), "on_fail": list(row.get("effects") or []),
                                      "on_success": list(save.get("on_success") or [])}])
            return
    run_effects(scoped, _willing_rows(row))


def _willing_rows(row):
    """The rows the willing branch runs: the printed repeat save belongs to the refusal branch.

    Only a row carrying ``unwilling_save`` made anyone save at all -- its own printed refusal path --
    so only such a row drops ``repeat_save`` here: "a target that was never made to save has no save
    to repeat", while a refusing target keeps it ("an unwilling target repeats the saving throw"). A
    row without that key is the plain consent case, where every field of its effects is left exactly
    as authored: a consented effect may legitimately carry a condition with its own recurring save,
    and that escape mechanism is none of this module's business to delete.
    """
    rows = row.get("effects") or []
    if not row.get("unwilling_save"):
        return list(rows)
    return [{key: value for key, value in effect.items() if key != "repeat_save"}
            if isinstance(effect, dict) and effect.get("repeat_save") else effect for effect in rows]


@effect("optional_recipient")
def optional_recipient(ctx, row):
    """Ask the affected recipient whether to apply a beneficial optional effect.

    Used by Harmonic Healing Tone; no prompt when its relevant condition is absent.
    """
    from ..typed_executor import run_effects

    subject = ctx.target
    if subject is None or not any(c.condition_id == row["condition_id"] for c in subject.conditions.values()):
        return
    chosen = _choose(ctx, subject, "optional", ["accept"], {"accept": row["label"]}, ["accept"],
                     f"{ctx.actor.display_name} uses {ctx.action.display_name} on {subject.display_name}: {row['label']}?")
    if chosen:
        run_effects(ctx, row.get("effects") or [])
