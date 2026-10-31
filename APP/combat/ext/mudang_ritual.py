"""Gut of Revealed Guests: sealed ritual preparation and combat petitions.

The player records completion of the printed ten-minute ritual and possession
of its focus before the fight. This is never a free combat activation. Its
anchor pays four starting Resonance, has the printed AC/HP/immunities and
persists only for this scene. Petition saves, pressure, repeat saves, attack
restrictions and broken hospitality use ordinary engine hooks. The separate
public-diagnosis action visits allies (including the owner), never enemies by
automatic choice. Unrepresented guests/concealment authority remain outside
this bounded creature implementation.

Hooks: prefight_setup_choices, match_start, compile_actions, candidate_allowed, effect_origins,
attack_allowed, effect_allowed, event, ability_check_mode. No core special cases.
"""
from __future__ import annotations

from typing import Any

from . import effect, hook, note
from . import spirit_traditions as st
from .creature_kinds import matches

GUT = "tianxia.tradition.spirit.mudang.feature.gut_of_revealed_guests"
RHYTHM = "resource:named.trance_rhythm"
RESONANCE = "resource:core.resonance"
ANCHOR = "object:typed.gut_circle:"
PACIFIED = "condition:typed.gut_pacified"
KINDS = ("spirit", "ghost", "hosted entity", "incorporeal undead")


def _owns(bundle: dict) -> bool:
    return any(p.get("feature_id") == GUT for p in bundle.get("typed_passives") or ())


@hook("compile_resources")
def ritual_rhythm(info: dict) -> list[Any] | None:
    if GUT not in info["owned_ids"]:
        return None
    from ..gate2_runtime_models import ResourceDefinition
    return [ResourceDefinition(resource_id=RHYTHM, initial=0, maximum=int(info["numbers"]["pb"]))]


def anchor(engine: Any, actor: Any) -> Any:
    return next((o for o in engine.state.objects.values() if o.object_id == ANCHOR + actor.entity_id
                 and not o.destroyed and int(o.current_hp or 0) > 0), None)


def inside(engine: Any, actor: Any, target: Any) -> bool:
    obj = anchor(engine, actor)
    return obj is not None and engine.grid.distance_ft(obj.position, target.position) <= 50


@hook("prefight_setup_choices")
def ritual_preparation(bundle: dict) -> list[dict] | None:
    if not _owns(bundle):
        return None
    return [{"id": "gut_ritual_completed", "label": "Gut ritual completed before this fight",
             "kind": "integer_range_list", "count": 1, "item_label": "Completed ritual",
             "minimum": 0, "maximum": 1, "default": [0],
             "help": "Choose 1 only after completing the ten-minute ritual with its required focus. "
                     "The focus starts at your starting space, costs 4 Resonance, and creates a 50-foot circle. "
                     "Choose 0 if you have not completed it."}]


@hook("match_start")
def prepare_circle(engine: Any) -> None:
    from ..gate2_runtime_models import RuntimeObjectState
    for bundle in getattr(engine, "typed_bundle_documents", ()) or ():
        actor = engine.state.actors.get(bundle.get("actor_id"))
        values = ((bundle.get("prefight") or {}).get("setup_choices") or {}).get("gut_ritual_completed")
        if actor is None or not _owns(bundle) or values != [1]:
            continue
        if actor.resources.get(RESONANCE, 0) < 4:
            note(engine, GUT, actor, "Gut Circle could not be prepared: you need 4 Resonance.")
            continue
        numbers = st.numbers(engine, actor)
        hp = 5 * int(actor.proficiency_bonus)
        obj = RuntimeObjectState(object_id=ANCHOR + actor.entity_id, object_kind="SPIRIT_ANCHOR",
            position=actor.position, owner_id=actor.entity_id, ac=int(numbers.get("save_dc") or 10),
            unattended=False, flammable=False,
            maximum_hp=hp, current_hp=hp, damage_immunities=("POISON", "PSYCHIC"),
            component={"label": "Gut Circle focus (50-foot radius)", "source_cl": numbers.get("cl", 1)})
        engine._spend_resource(actor, RESONANCE, 4, GUT)
        engine._update_object(obj, GUT, actor.entity_id)


@hook("compile_actions")
def ritual_actions(info: dict) -> list[Any] | None:
    if GUT not in info["owned_ids"]:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    out = []
    for key, label, economy, costs, target in (
        ("petition", "Pacification Petition", EconomyKind.ACTION, ((RHYTHM, 1),), "ANY_CREATURE"),
        ("diagnosis", "Gut: Public Diagnosis", EconomyKind.ACTION, (), "SELF"),
        ("dismiss", "Dismiss Gut Circle", EconomyKind.NONE, (), "SELF"),
        ("hospitality", "End Gut Hospitality", EconomyKind.NONE, (), "SELF"),
    ):
        out.append(ActionDefinition(source_definition_id=f"action:typed.{info['short']}.gut.{key}", owner_id=info["actor_id"],
            display_name=label, economy=economy, costs=costs, target_kind=target, range_ft=50 if key == "petition" else None,
            resolution_kind="TYPED", parameters={"gut": key, "description": {
                "petition": "Action; spend 1 Trance Rhythm (maximum equal to your Proficiency Bonus; starts at 0). Once per turn, regain 1 when you move at least 10 feet during Spirit Dance, a hostile fails a save against your Spirit Awakening feature, or your Resonance action heals, shields or frees another creature. Ask a spirit in your prepared circle to stop attacking, possessing and contaminating others. If it refuses or is hostile, it makes a Charisma save. On a failure, it cannot attack, possess or contaminate until the start of your next turn; at the end of its turns it repeats the save. It can still defend, move and try to escape. An attack or ended hospitality releases it.",
                "diagnosis": "Once per ritual: ask each ally in the circle whether it accepts a public diagnosis. Accepted allies are checked using Soul Gaze's normal limits; protected details require their usual contest.",
                "dismiss": "End this circle and its petitions.",
                "hospitality": "Declare that hospitality or negotiations have ended; release every restrained guest.",
            }[key], "typed": {"source": GUT, "numbers": info["numbers"], "duration": {"kind": "instant"},
                "effects": [{"type": "gut_expression", "mode": key}], "riders": []}}))
    return out


@hook("effect_origins")
def circle_petition_origin(engine: Any, actor: Any, action: Any) -> list[dict] | None:
    if (action.parameters or {}).get("gut") != "petition":
        return None
    obj = anchor(engine, actor)
    if obj is None:
        return None
    return [{"id": obj.object_id, "label": "Gut Circle focus", "position": obj.position.model_dump(mode="json")}]


@hook("candidate_allowed")
def ritual_gates(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    key = (action.parameters or {}).get("gut") if action is not None else None
    if key:
        obj = anchor(engine, actor)
        if obj is None or (key == "diagnosis" and (obj.component or {}).get("diagnosed")):
            return False
        if key == "petition":
            target = engine.state.actors.get(next(iter(candidate.target_ids or ()), ""))
            if target is None or not matches(target, KINDS) or not inside(engine, actor, target):
                return False
    if any(c.condition_id == PACIFIED for c in actor.conditions.values()):
        # Free movement/defense remain available. Harmful creature activations,
        # including native weapon attacks, are withheld while hospitality lasts.
        if action is not None and (action.target_kind == "HOSTILE_ENTITY" or (action.parameters or {}).get("is_attack")):
            return False
    return None


@hook("masked_conditions")
def revealed_guests(engine: Any, viewer: Any, target: Any) -> dict | None:
    from .. import senses
    if (not senses.is_creature(viewer) or not senses.is_creature(target)
            or not matches(target, (*KINDS, "possession entity", "projected soul", "possessed"))):
        return None
    masks = set()
    for owner in engine.state.actors.values():
        obj = anchor(engine, owner)
        if obj is None or owner.team_id != viewer.team_id or not inside(engine, owner, target):
            continue
        authority = int((obj.component or {}).get("source_cl") or 1)
        from .condition_authority import source_cl
        for iid, held in target.conditions.items():
            if str(held.condition_id).rsplit(".", 1)[-1] not in ("invisible", "hidden"):
                continue
            level = source_cl(engine, held)
            if level is not None and level < authority:
                masks.add(iid)
    return {target.entity_id: masks} if masks else None


def _release(engine: Any, owner: str, reason: str) -> None:
    for actor in engine.state.actors.values():
        for held in list(actor.conditions.values()):
            if held.condition_id == PACIFIED and held.source_actor_id == owner:
                st.remove(engine, actor, held, reason)


@effect("gut_expression")
def ritual_expression(ctx: Any, row: dict) -> None:
    engine, actor = ctx.engine, ctx.actor
    obj = anchor(engine, actor)
    if obj is None:
        return
    mode = row["mode"]
    if mode in ("dismiss", "hospitality"):
        _release(engine, actor.entity_id, "HOSPITALITY_ENDED")
        if mode == "dismiss":
            engine._update_object(obj.model_copy(update={"destroyed": True}), GUT, actor.entity_id)
        return
    from .. import typed_executor as te
    if mode == "diagnosis":
        targets = [c for c in engine.state.actors.values() if c.active and c.team_id == actor.team_id and inside(engine, actor, c)]
        engine._update_object(obj.model_copy(update={"component": {**(obj.component or {}), "diagnosed": True}}), GUT, actor.entity_id)
        # Public Diagnosis prints a narrower contract than full Soul Gaze. Do
        # not expose exact HP, affinities or unrelated creature statistics.
        categories = {"possession": ("possess",), "contamination": ("contaminat",),
                      "curse": ("curse", "cursed"), "spiritual wound": ("spiritual_wound", "soul_wound"),
                      "concealed guest": ("hosted_guest", "concealed_guest", "guest_seat")}
        for target in targets:
            from . import willing_targets
            accepted = target is actor or willing_targets.asks_consent(
                    engine, ctx.intent, target, ctx.action.display_name,
                    f"{actor.display_name} asks {target.display_name} to accept a public Gut diagnosis that may reveal possession, contamination, curses, spiritual wounds or concealed guests to everyone. Accept or refuse?",
                    prefer_accept=True, asker=actor)
            if not accepted:
                note(engine, GUT, actor, f"Public Diagnosis of {target.display_name}: no diagnosis shared.", (target,))
                continue
            names = [str(c.condition_id).rsplit(".", 1)[-1].lower() for c in target.conditions.values()]
            from .condition_authority import source_cl
            diagnosis_cl = int(st.numbers(engine, actor).get("cl") or 1)
            present, protected = [], []
            for label, tokens in categories.items():
                matches_for_label = [name for name in names if any(token in name for token in tokens)]
                levels = [source_cl(engine, condition) for condition in target.conditions.values()
                          if str(condition.condition_id).rsplit(".", 1)[-1].lower() in matches_for_label]
                if matches_for_label and any(level is None or level >= diagnosis_cl for level in levels):
                    protected.append(label)
                elif matches_for_label or matches(target, ("possessed",) if label == "possession" else ("cursed",) if label == "curse" else ()):
                    present.append(label)
            note(engine, GUT, actor, f"Public Diagnosis of {target.display_name}: "
                 + ((", ".join(present) + " detected. ") if present else "No eligible public condition detected. ")
                 + ("Some protected details remain contested." if protected else ""),
                 (target,))
        return
    target = next(iter(ctx.targets), None)
    if target is None or not matches(target, KINDS) or not inside(engine, actor, target):
        return
    accepted = False
    from . import willing_targets
    accepted = willing_targets.asks_consent(engine, ctx.intent, target, ctx.action.display_name,
            f"{actor.display_name} asks {target.display_name} to accept Gut hospitality: stop attacking, possessing and contaminating others until released. Accept or refuse?",
            prefer_accept=target.team_id == actor.team_id, asker=actor)
    failed = accepted or st.save(ctx, target, "cha")
    if failed:
        engine._apply_condition(target, PACIFIED, GUT, actor.entity_id,
            expires_on="UNTIL_REMOVED" if accepted else "START_OF_SOURCE_NEXT_TURN",
            data={"label": ("Accepted Gut hospitality: no attacks, possession or contamination until released" if accepted else
                             "Until the start of the caster's next turn: no attacks, possession or contamination; repeat the Charisma save at the end of your turn; an attack or ended hospitality releases you"),
                  "accepted_willingness": bool(accepted),
                  **({} if accepted else {"repeat_save": {"ability": "cha", "dc": int(ctx.numbers["save_dc"]), "when": "end"}})})
    else:
        te.run_effects(ctx, [{"type": "spiritual_pressure", "applies_to": "target"}])


@hook("attack_allowed")
def no_petitioned_attacks(ctx: Any, target: Any, effect: dict) -> bool | None:
    if any(c.condition_id == PACIFIED for c in ctx.actor.conditions.values()):
        return False
    return None


@hook("effect_allowed")
def no_petitioned_intrusions(ctx: Any, effect: dict) -> bool | None:
    if not any(c.condition_id == PACIFIED for c in ctx.actor.conditions.values()):
        return None
    kind = str(effect.get("type") or "").lower()
    if "possess" in kind or "contaminat" in kind:
        return False
    return None


@hook("event")
def broken_hospitality(engine: Any, event_type: str, kwargs: dict) -> None:
    if event_type == "ATTACK_ROLLED":
        for aid in kwargs.get("target_ids") or ():
            target = engine.state.actors.get(aid)
            if target is not None:
                for held in list(target.conditions.values()):
                    if held.condition_id == PACIFIED:
                        st.remove(engine, target, held, "ATTACKED")
    elif event_type == "OBJECT_UPDATED":
        obj = (kwargs.get("payload") or {}).get("object") or {}
        if str(obj.get("object_id") or "").startswith(ANCHOR) and (obj.get("destroyed") or int(obj.get("current_hp") or 0) <= 0):
            _release(engine, str(obj.get("owner_id") or ""), "ANCHOR_DESTROYED")


@hook("ability_check_mode")
def ritual_diagnosis(engine: Any, actor: Any, ability: str, skill: str, against: Any) -> str | None:
    if (against is not None and inside(engine, actor, actor) and inside(engine, actor, against)
            and str(skill).casefold() in ("insight", "medicine", "persuasion", "religion")
            and matches(against, (*KINDS, "possessed", "cursed", "possession entity"))):
        return "ADVANTAGE"
    return None
