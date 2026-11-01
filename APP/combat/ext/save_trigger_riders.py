"""Free "a creature in your area failed a save against one of your own features" riders.

Some printed riders hang off a feature the character *activates* (a Bonus Action, an Action, a
Reaction) but fire on saves made against *other* abilities the same character owns. The compiler
cannot express that shape, so it silently dropped the row:

* ``factory_compiler.apply_modifiers`` skips every owned mechanic whose ``activation.economy`` is
  ``action``/``bonus_action``/``reaction`` -- on such a record a ``modifier`` describes a rider, not
  an always-on change to that record's own ability. The same exclusion is repeated in the
  generic-reaction pass, so the row is skipped twice and nothing reports it (``diagnostics.skipped``
  stays empty).
* The row's ``scope`` could not have saved it either: ``any_sphere_technique`` resolves only to
  compiled *sphere* techniques (rows carrying a ``sphere_id``), while the print names the owner's
  own Path and Subpath features.

So Domain Manifestation (CL15) compiled with a "the free Spiritual Pressure is typed" status claim
and a rider that could never run. This module picks those rows up from the typed data and runs them
on the engine's ``after_save_resolved`` seam. No per-ability code lives here: a feature opts in
purely by carrying a ``modifier`` shaped like::

    "modifier": {"scope": "own_path_features", "when": "failed_save",
                 "limit": "once_per_turn", "effects": [...]}

``own_path_features`` means "one of this character's own Path or Subpath features". Those ids are
resolved at compile time into the rider, so the runtime trigger test is a plain membership check
and no authority is re-read during a fight. Classification is
``ability_source.is_path_or_subpath_feature``: a Path record is filed under ``tianxia.path.*`` and
a Subpath under ``tianxia.subpath.*``, but the Spirit Awakening subpaths the print names are filed
under ``tianxia.tradition.*`` (Dream Eater's Nightmare Touch and its siblings), so a check that
only knows two of the three namespaces qualifies nothing from a Subpath.

**Final save outcome.** The rider runs on ``after_save_resolved``, not ``after_save``: a save that
fails the roll and is then converted to a success (Omen Witness, Unbroken Brace, War Leader) never
reaches a creature, and a success converted to a failure does.

**Owner turn.** The print says "Once on each of your *turns*", so the clause only fires while the
Domain owner is the acting creature. A reaction the owner takes on somebody else's turn -- Echo
Counter driving Mind Spike on the attacker's turn -- is therefore not a trigger.

**Area gate.** A rider whose feature leaves an area (a Domain aura, say) only fires for a creature
standing inside that live area -- which is what "a creature in the Domain" means. It rides the
zone the feature created rather than recomputing a distance, so it follows the owner's movement,
and it goes inert by itself when the area ends. A feature that leaves no area has no live trigger.

**Choice.** The imposed effect is free but not automatic: which ordinary effect it is is the
player's call, so the trigger asks (AI actors answer automatically) and the answer is written into
the rider's effect row as its ``option`` -- the same per-use option an ordinary Spiritual Pressure
row already carries. The character's standing toggle is offered as the default, not applied behind
the player's back.

**Player text.** The log line says what happened and asks the ``effect_text`` hook what the chosen
effect does to that creature, so the owning plug-in -- not this general module -- words it.

**Inertness.** Every step returns early for a character that does not own the feature, so no other
character and no saved fight is affected.

**Limit.** ``once_per_turn``/``once_per_round`` are spent on the *owner's* turn (an integer/string
flag in ``turn_flags``, so they survive a table commit and reload), matching "This can occur only
once during the turn, regardless of the number of failed saves, targets, echoes, or origins".

Authority: the rules live in ``authority/typed_mechanics/reviewed_final.d/*.json``; this module
owns none of its own. Domain Manifestation is the first user.
"""

from __future__ import annotations

from typing import Any

from . import hook

# The modifier scopes this module implements. A row the compiler attaches itself is never seen here.
SAVE_SCOPES = {"own_path_features"}
WHEN = "failed_save"
# Economies factory_compiler.apply_modifiers deliberately skips; a rider on one of these is ours.
ACTIVATED = ("action", "bonus_action", "reaction")
RIDER = "save_trigger_rider"          # payload marker on a PASSIVE_TRIGGERED line, and the
                                     # parameters key on the feature's own compiled action
TURN_FLAG = "save_trigger_rider_turn"  # owner turn_flags key: "<prefix>:<feature_id>"
CHOICE_ID = "choice:needle.save_trigger_rider"


def _own_path_features(owned: Any) -> list[str]:
    """The Path/Subpath feature ids this character owns -- the "one of your Path or Subpath features"
    the print names, resolved once at compile time.

    The three record namespaces count (Path, Subpath, and the Spirit Awakening subpaths filed
    under ``tianxia.tradition``); a Sphere talent or a Foundation base ability is neither.
    """
    from .ability_source import is_path_or_subpath_feature

    return sorted({str(fid) for fid in owned or [] if is_path_or_subpath_feature(fid)})


def _rider(action: Any, info: dict[str, Any]) -> dict[str, Any] | None:
    """The dropped modifier this feature's own action should carry, or None (the common case)."""
    typed = (action.parameters or {}).get("typed") or {}
    feature_id = str(typed.get("source") or "").split("#")[0]
    if not feature_id:
        return None
    mechanic = (info.get("mechanics") or {}).get(feature_id) or {}
    modifier = mechanic.get("modifier")
    if not modifier or str(modifier.get("when") or "") != WHEN:
        return None
    if str(modifier.get("scope") or "named") not in SAVE_SCOPES:
        return None
    if str((mechanic.get("activation") or {}).get("economy") or "") not in ACTIVATED:
        return None  # the compiler attaches this one itself; never a second implementation
    features = _own_path_features(info.get("owned_ids") or [])
    return {"feature": feature_id, "name": str(mechanic.get("name") or feature_id),
            "effects": list(modifier.get("effects") or []), "limit": str(modifier.get("limit") or "none"),
            "features": features}


@hook("compile_action")
def carry_save_trigger_rider(action: Any, info: dict[str, Any]) -> Any:
    """Hang the dropped modifier on the feature's own compiled action, so it is inert (no new
    button, no AI candidate) and lives exactly where the printed rider belongs."""
    rider = _rider(action, info)
    if not rider:
        return None
    return action.model_copy(update={"parameters": {**(action.parameters or {}), RIDER: rider}})


def _triggered_by(rider: dict[str, Any], source: str) -> bool:
    """The save must have been made against one of the owner's own Path/Subpath features."""
    text = str(source or "")
    return any(text == fid or text.endswith("." + fid) for fid in rider.get("features") or [])


def _in_live_area(engine: Any, action: Any, actor: Any, subject: Any) -> bool:
    """True while ``subject`` stands inside a live area the feature itself created."""
    from .. import zones

    return any(zones._inside(engine, subject, zone) for zone in zones.typed_zones(engine)
               if zone.source_definition_id == action.source_definition_id and zone.owner_id == actor.entity_id)


def _spent(engine: Any, actor: Any, rider: dict[str, Any]) -> bool:
    limit = str(rider.get("limit") or "none")
    if limit not in ("once_per_turn", "once_per_round"):
        return False
    stamp = f"{engine.state.round_number}:{actor.turns_started}"
    return actor.turn_flags.get(f"{TURN_FLAG}:{rider['feature']}") == stamp


def _options(effect_type: str, actor: Any) -> list[str]:
    """The options the owner of ``effect_type`` offers a player for it, asked through the
    ``effect_choice`` hook, in the order to offer them: the character's own standing preference
    first, then the rest. An empty answer means nothing is chosen between, and nothing is asked."""
    from .. import ext

    for found in ext.run("effect_choice", effect_type, actor):
        return [str(option) for option in found or []]
    return []


def _words(effect_type: str, option: str | None, target_name: str) -> str:
    """How one effect reads to a player, asked of the plug-in that owns that effect type through the
    ``effect_text`` hook. A type nobody describes has no words of its own here."""
    from .. import ext

    for text in ext.run("effect_text", effect_type, option=option, target_name=target_name):
        if str(text or "").strip():
            return str(text)
    return ""


def _choice(ctx: Any, subject: Any, rider: dict[str, Any], trigger: str) -> str | None:
    """The player's choice of which effect the free clause imposes on ``subject``, or None when the
    rider's own effect names its effect.

    Free cost does not make the choice automatic: the player's standing preference is the option
    offered first rather than applied without asking, and an AI actor answers for itself
    (``needle.ask`` falls back to that first option when nobody is listening). The answer rides the
    choice checkpoint, so it is transported, retried and replayed like any other table choice.
    """
    from . import needle

    types = [str(row.get("type") or "") for row in rider["effects"]]
    options: list[str] = []
    for effect_type in types:
        for option in _options(effect_type, ctx.actor):
            if option not in options:
                options.append(option)
    if len(options) < 2:
        return None
    labels: dict[str, str] = {}
    for effect_type in types:
        for option in options:
            labels.setdefault(option, _words(effect_type, option, subject.display_name) or option)
    chosen = needle.ask(ctx.engine, ctx.intent,
                        needle.checkpoint_id(ctx.engine, "SAVE_TRIGGER_RIDER", rider["feature"], subject.entity_id),
                        ctx.actor, CHOICE_ID, options, labels=labels, preferred=options[:1],
                        prompt=f"{rider['name']}: {subject.display_name} failed the saving throw against "
                               f"{trigger} while standing in the area {rider['name']} created. Choose the effect "
                               f"it suffers. This costs you nothing.",
                        name=rider["name"], feature_id=rider["feature"], target_id=subject.entity_id)
    return chosen[0] if chosen else None


def _fire(ctx: Any, subject: Any, action: Any, rider: dict[str, Any]) -> None:
    """Impose the rider's own effects, attributed to the feature, keeping the save that triggered it
    as the context (so an effect that reads the failed save still sees the right one)."""
    from ..typed_executor import Context, run_effects

    engine, actor = ctx.engine, ctx.actor
    trigger = str(getattr(ctx.action, "display_name", "") or rider["name"])
    option = _choice(ctx, subject, rider, trigger)
    rows = [{**row, **({"option": option} if option else {})} for row in rider["effects"]]
    said = "; ".join(text for text in (_words(str(row.get("type") or ""), option, subject.display_name)
                                       for row in rows) if text) or "one effect of your choosing"
    # PASSIVE_TRIGGERED is the engine's own "something resolved on its own" line (combat/ext/placed.note), so a
    # saved fight reloads through the ordinary reducer instead of meeting a new event type it cannot rebuild.
    engine._append_event("PASSIVE_TRIGGERED", action.source_definition_id, actor_id=actor.entity_id,
                         target_ids=(subject.entity_id,),
                         payload={"text": f"{rider['name']}: {subject.display_name} failed the saving throw against "
                                          f"{trigger} while standing in the area {rider['name']} created, so at no "
                                          f"cost it suffers {said}.",
                                  RIDER: rider["feature"], "feature": rider["feature"]})
    run_effects(Context(engine, actor, action, ctx.intent, {**ctx.typed, "effects": rows},
                        [subject], subject, ctx.damage_cache, True, origin_save=ctx.origin_save,
                        save_geometry=ctx.save_geometry, effect_source=action.source_definition_id),
                rows)
    limit = str(rider.get("limit") or "none")
    if limit in ("once_per_turn", "once_per_round"):
        actor.turn_flags[f"{TURN_FLAG}:{rider['feature']}"] = f"{engine.state.round_number}:{actor.turns_started}"


@hook("after_save_resolved")
def free_pressure_on_a_failed_save(ctx: Any, subject: Any, ability: str, named: Any, failed: bool) -> None:
    """The once-per-turn free ordinary Spiritual Pressure: on your own turn, a creature inside your
    live area finally fails a saving throw against one of your own Path or Subpath features."""
    engine = getattr(ctx, "engine", None)
    actor = getattr(ctx, "actor", None)
    if not failed or subject is None or actor is None or engine is None:
        return
    if not getattr(subject, "active", False):
        return
    if engine.state.current_actor_id != actor.entity_id:
        return  # "Once on each of your turns": a reaction you take on someone else's turn is not a trigger
    catalog = getattr(engine, "action_catalog", None) or {}
    for action in catalog.values():
        rider = (action.parameters or {}).get(RIDER)
        if not rider or action.owner_id != actor.entity_id:
            continue
        if not _triggered_by(rider, ctx.source):
            continue
        if not _in_live_area(engine, action, actor, subject) or _spent(engine, actor, rider):
            continue
        _fire(ctx, subject, action, rider)
        return  # "only once during the turn" is the row's limit, not per target
