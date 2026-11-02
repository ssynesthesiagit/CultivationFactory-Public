"""Printed Insights 3 riders, owned by hash-gated newly compiled rows.

The ordinary defense/standing rows remain their single existing providers.
No live-sheet parsing, source-name inference or core ability branch is used.
"""
from dataclasses import replace
from contextlib import contextmanager
from contextvars import ContextVar

from . import hook
from .passive_rows import row_of
from .d20_rewrite import Rule, register

BLOCK = "insights3"
_HEALING = ContextVar("insights3_healing", default=None)
FALL = "insight.fall-seven-ways"
FROZEN = "insight.frozen-golden-core"
FURNACE = "insight.furnace-core-survivor"
HEART = "insight.furnace-heart-discipline"
STOMACH = "insight.furnace-tyrant-s-stomach"
DEMON = "insight.heart-demon-vanquisher"
FLESH = "insight.flesh-reconstruction-insight"
EXISTING = {FALL, FROZEN, FURNACE, HEART, DEMON}
MENTAL = {"charmed", "frightened", "category:dream", "category:illusion",
          "category:emotional_manipulation", "category:forced_identity_alteration"}
HEAT = {"damage:fire", "category:heat", "category:smoke", "category:poison_gas", "category:volcanic_pressure"}
BODY = {"category:bodily_corruption", "category:mutation", "category:forced_transformation", "category:disease", "bodily_corruption", "mutation", "forced_transformation", "disease"}

OUTCOMES = {
    FALL: 'Standing costs 5 feet of movement; once per scene, you may prevent falling damage and choose a legal landing step up to 10 feet; no action or resource cost',
    FROZEN: 'Cold damage is halved; once per turn, a failed save against your Cold, Yin, Ice or Stillness feature also reduces Speed by 10 feet until your next turn starts; a feature that sets Speed to 0 also prevents Reactions until the affected creature’s next turn starts',
    FURNACE: 'Fire damage is halved; another Fire Resistance grants a Proficiency Bonus reduction on the first instance of Fire damage each round; once per round, dealing Fire, Magma or Ash damage after taking damage grants twice your Proficiency Bonus in Temporary HP',
    HEART: 'Advantage on saves against Burning and on Concentration checks caused by Fire, Cold, smoke or environmental heat; once per scene, you may reroll a failed Constitution save caused by heat, smoke, poison gas or volcanic pressure, with no action or resource cost',
    STOMACH: 'Poison damage is halved; Poison damage from your own Alchemy also falls by your Proficiency Bonus; another Poison Resistance grants Advantage on saves against Poisoned',
    DEMON: 'Advantage on saves against Charmed, Frightened, Dreams, Illusions, emotional manipulation and forced identity alteration; after a failure you may spend your Reaction and 2 Qi to reroll once and keep the new result',
    FLESH: 'Once per turn, add your Proficiency Bonus to healing from a Flesh talent; shared healing rolls receive the bonus once; Advantage on saves against bodily corruption, mutation, forced transformation and Disease',
}


def owns(engine, actor, feature):
    return row_of(engine, actor.entity_id, BLOCK, feature) if actor is not None else None


def clock(engine):
    return int(engine.state.round_number) * 1000 + int(engine.state.current_slot_index)


def profile(engine, source):
    action = engine.action_catalog.get(source)
    return (action.parameters.get("typed") or {}) if action else {}


def sphere(typed, *names):
    return typed.get("sphere") in {"tianxia.sphere." + name for name in names}


@hook("compile_block")
def compile_row(block, spec, row, numbers):
    if block == BLOCK:
        return [{**row, "kind": row["feature_id"], "player_outcome": OUTCOMES[row["feature_id"]], "pb": int(numbers["pb"]), "cl": int(numbers["cl"]), "choice_owner": 1}]
    return None


@hook("compile_passives")
def seal_existing(passives, info):
    numbers = info["numbers"]
    return [*passives, *({"block": BLOCK, "feature_id": fid, "kind": fid, "player_outcome": OUTCOMES[fid],
                         "pb": int(numbers["pb"]), "cl": int(numbers["cl"]), "choice_owner": 1}
                        for fid in sorted(EXISTING.intersection(info.get("owned_ids") or ())))]


def mental_hazard(engine, typed, named):
    return bool(set(named) & MENTAL) or sphere(typed, "dreams", "illusion")


@hook("save_roll_tags")
def save_tags(ctx, subject, ability, named):
    # The native rewrite sees precisely this save's established metadata.
    if any(owns(ctx.engine, subject, fid) for fid in (HEART, DEMON)):
        return sorted(named)
    return None


@hook("save_mode")
def defenses(engine, subject, ability, dc, source, roll_context):
    named = set((roll_context or {}).get("named") or ())
    typed = profile(engine, source)
    if owns(engine, subject, DEMON) and mental_hazard(engine, typed, named):
        return "ADVANTAGE"
    if owns(engine, subject, FLESH) and (named & BODY or sphere(typed, "disease")):
        return "ADVANTAGE"
    if owns(engine, subject, HEART) and source == "system:combat.concentration":
        damage_source = (roll_context or {}).get("damage_source_id")
        # The real triggering packet supplies its type, including native attacks.
        from ..pending_damage import current
        packet = current(engine)
        if packet and packet.damage_type.upper() in {"FIRE", "COLD"}:
            return "ADVANTAGE"
        if set(profile(engine, damage_source).get("save_categories") or ()) & {"smoke", "environmental_heat"}:
            return "ADVANTAGE"
    return None


@hook("save")
def typed_defenses(ctx, subject, ability, named):
    if owns(ctx.engine, subject, FLESH) and (set(named) & BODY or sphere(ctx.typed, "disease")):
        return {"modes": ["ADVANTAGE"]}
    if owns(ctx.engine, subject, DEMON) and mental_hazard(ctx.engine, ctx.typed, named):
        return {"modes": ["ADVANTAGE"]}
    return None


def rewrite_guard(feature, tags):
    def guard(engine, holder, rc):
        if not owns(engine, holder.actor, feature):
            return False
        return mental_hazard(engine, profile(engine, rc.source_id), rc.named) if feature == DEMON else bool(set(rc.named) & tags)
    return guard


register(Rule("insights3_heart_demon", "Heart-Demon Vanquisher", feature=DEMON,
              rolls=("save",), costs=((("qi", 2),),), reaction=True,
              guard=rewrite_guard(DEMON, MENTAL)))
register(Rule("insights3_furnace_heart", "Furnace-Heart Discipline", feature=HEART,
              rolls=("save",), abilities=("CON",), limit="fight",
              guard=rewrite_guard(HEART, HEAT)))


def other_resistance(engine, subject, kind, excluding, typed, source_actor_id=None):
    """Pure overlap query, excluding this Insight's own Resistance provider."""
    from ..typed_reactions import _defense_applies
    from ..typed_reactions import _rows
    from . import run
    rows = [*_rows(engine, subject.entity_id, "defense"), *_rows(engine, subject.entity_id, "resistance"),
            *(r for group in run("damage_defenses", engine, subject, kind, typed, source_actor_id) for r in group)]
    if any(row.get("kind") == "resistance" and row.get("feature_id") != excluding
           and _defense_applies(engine, subject, row, kind, typed, source_actor_id) for row in rows):
        return True
    if any(m.target_field in {"damage_resistance", "damage_resistance_next"} and str(m.value).upper() == kind
           for m in subject.modifiers.values()):
        return True
    if kind in {str(k).upper() for k in subject.damage_resistances}:
        return True
    return any({kind, "ALL"} & {str(k).upper() for k in (c.data or {}).get("rule", {}).get("damage_resistances", [])}
               for c in subject.conditions.values() if c.condition_id.startswith("condition:typed.")
               and not c.condition_id.startswith("condition:typed.suppressed."))


@hook("damage_reduction")
def reduction(engine, subject, kind, typed, source_actor_id, applied=False):
    kind = kind.upper()
    row = owns(engine, subject, FURNACE)
    if (row and kind == "FIRE" and other_resistance(engine, subject, kind, FURNACE, typed, source_actor_id)
            and subject.turn_flags.get("_round_insights3_fire_reduced") != engine.state.round_number):
        if applied:
            subject.turn_flags["_round_insights3_fire_reduced"] = engine.state.round_number
        return row["pb"]
    return None


@hook("event", nested=True)
def damage_history(engine, event_type, kwargs):
    if event_type != "DAMAGE_COMMITTED":
        return
    payload = kwargs.get("payload") or {}
    if int(payload.get("reduced_to") or 0) <= 0:
        return
    actor = engine.state.actors.get(kwargs.get("actor_id"))
    row = owns(engine, actor, FURNACE)
    previously_hurt = bool(row and actor.turn_flags.get("_round_insights3_hurt") == engine.state.round_number)
    for aid in kwargs.get("target_ids") or ():
        subject = engine.state.actors.get(aid)
        if owns(engine, subject, FURNACE):
            subject.turn_flags["_round_insights3_hurt"] = engine.state.round_number
    if (not row or not previously_hurt
            or actor.turn_flags.get("_round_insights3_furnace_reward") == engine.state.round_number):
        return
    typed = profile(engine, kwargs.get("source_definition_id"))
    if str(payload.get("damage_type")).upper() != "FIRE" and not sphere(typed, "magma", "ash"):
        return
    actor.turn_flags["_round_insights3_furnace_reward"] = engine.state.round_number
    engine._grant_temp_hp(actor, 2 * row["pb"], FURNACE, actor.entity_id)


def frozen_key(ctx, subject):
    return (ctx.source, subject.entity_id)


def speed_without_frozen(engine, subject):
    projection = subject.model_copy(update={"modifiers": {k: v for k, v in subject.modifiers.items()
        if v.source_definition_id != FROZEN}})
    return engine._effective_speed(projection)


@hook("save_effects")
def frozen_pending(ctx, subject, ability, fail, success, categories):
    if not owns(ctx.engine, ctx.actor, FROZEN):
        return None
    key = frozen_key(ctx, subject)
    ctx.damage_cache.setdefault("insights3_frozen_snapshots", {})[key] = {
        "conditions": set(subject.conditions), "modifiers": set(subject.modifiers),
        "speed": speed_without_frozen(ctx.engine, subject)}
    return None


@hook("save_final")
def frozen_select(ctx, subject, ability, named, failed):
    row = owns(ctx.engine, ctx.actor, FROZEN)
    if not row or not failed or ctx.actor.turn_flags.get("insights3_frozen_turn") == clock(ctx.engine):
        return
    if not sphere(ctx.typed, "ice", "yin") and not (set(named) & {"damage:cold", "category:stillness", "category:ice", "category:yin", "category:cold"}):
        return
    snapshot = ctx.damage_cache.get("insights3_frozen_snapshots", {}).get(frozen_key(ctx, subject))
    if snapshot is None:
        return
    ctx.actor.turn_flags["insights3_frozen_turn"] = clock(ctx.engine)
    ctx.damage_cache["insights3_frozen_selected"] = {"source": ctx.source, "target": subject.entity_id,
                                                  "snapshot": snapshot, "literal_zero": False}


def frozen_flush(ctx):
    selected = ctx.damage_cache.get("insights3_frozen_selected")
    if not selected or selected["source"] != ctx.source:
        return
    ctx.damage_cache.pop("insights3_frozen_selected", None)
    subject = ctx.engine.state.actors.get(selected["target"])
    if subject is None or not subject.active:
        return
    from ..typed_executor import run_effects, rules
    snapshot = selected["snapshot"]
    conditions = [c for iid, c in subject.conditions.items() if iid not in snapshot["conditions"]
                  and c.source_definition_id == ctx.source]
    modifiers = [m for mid, m in subject.modifiers.items() if mid not in snapshot["modifiers"]
                 and m.source_definition_id == ctx.source and m.target_field in {"speed_ft", "speed_halved"}]
    zero_condition = any((c.data or {}).get("rule", {}).get("speed_zero")
        or rules()["conditions"].get(c.condition_id.removeprefix("condition:typed."), {}).get("speed_zero")
        for c in conditions)
    zero = selected["literal_zero"] or zero_condition or bool(modifiers and snapshot["speed"] > 0
        and speed_without_frozen(ctx.engine, subject) == 0)
    rows = [{"type": "speed", "amount": -10, "applies_to": "target", "source_owned": True,
             "duration": {"kind": "until_start_of_next_turn"}}]
    if zero:
        rows.append({"type": "reaction_denied", "applies_to": "target",
                     "duration": {"kind": "until_start_of_next_turn"}})
    run_effects(replace(ctx, targets=[subject], target=subject).with_source(FROZEN), rows)


@hook("effect_resolution_scope")
def frozen_outcome_scope(ctx, effect):
    if not owns(ctx.engine, ctx.actor, FROZEN):
        return None
    if effect.get("type") == "save":
        @contextmanager
        def saving():
            yield
            frozen_flush(ctx)
        return saving()
    if effect.get("type") == "speed" and effect.get("becomes") == 0:
        @contextmanager
        def zero_speed():
            from ..typed_executor import _default_subject
            subjects = _default_subject(ctx, effect, harmful=True)
            before = {subject.entity_id: set(subject.modifiers) for subject in subjects}
            yield
            selected = ctx.damage_cache.get("insights3_frozen_selected")
            if not selected or selected["source"] != ctx.source:
                return
            target = next((subject for subject in subjects if subject.entity_id == selected["target"]), None)
            if target and any(mid not in before[target.entity_id] and m.source_definition_id == ctx.source
                              and m.target_field == "speed_ft" for mid, m in target.modifiers.items()):
                selected["literal_zero"] = True
        return zero_speed()
    return None


@hook("technique_used")
def frozen_after_contest(ctx):
    # A plug-in's defending save can settle inside a contest, whose real outcome
    # is applied after the contest returns. Finish only after that technique.
    frozen_flush(ctx)


@hook("healing_roll_resolved")
def reconstruction(ctx, effect, amount):
    row = owns(ctx.engine, ctx.actor, FLESH)
    if not row or not sphere(ctx.typed, "flesh") or amount <= 0:
        return None
    if ctx.actor.turn_flags.get("insights3_flesh_turn") == clock(ctx.engine) and not ctx.damage_cache.get("insights3_flesh_activation"):
        return None
    from ..typed_executor import _default_subject, stored_healing_reductions
    from .life_state import is_dead
    if not any(not is_dead(subject) and subject.current_hp < subject.maximum_hp
               and stored_healing_reductions(ctx.engine, subject, amount + row["pb"], consume=False) > 0
               for subject in _default_subject(ctx, effect, harmful=False)):
        return None
    ctx.damage_cache["insights3_flesh_offer"] = 1
    return row["pb"]


@hook("effect_resolution_scope")
def healing_scope(ctx, effect):
    if effect.get("type") != "healing" or not owns(ctx.engine, ctx.actor, FLESH) or not sphere(ctx.typed, "flesh"):
        return None

    @contextmanager
    def scope():
        ctx.damage_cache.pop("insights3_flesh_offer", None)
        token = _HEALING.set(ctx)
        try:
            yield
        finally:
            ctx.damage_cache.pop("insights3_flesh_offer", None)
            _HEALING.reset(token)
    return scope()


@hook("event", nested=True)
def healing_committed(engine, kind, kwargs):
    ctx = _HEALING.get()
    data = kwargs.get("payload") or {}
    if (kind != "HEALING_APPLIED" or ctx is None or ctx.engine is not engine
            or kwargs.get("actor_id") != ctx.actor.entity_id or kwargs.get("source_definition_id") != ctx.source
            or not ctx.damage_cache.get("insights3_flesh_offer") or int(data.get("after", 0)) <= int(data.get("before", 0))):
        return
    ctx.actor.turn_flags["insights3_flesh_turn"] = clock(engine)
    ctx.damage_cache["insights3_flesh_activation"] = 1


@hook("falling_damage")
def fall_protection(engine, subject, defended, fall, intent):
    if not owns(engine, subject, FALL) or defended <= 0 or subject.turn_flags.get("_round_insights3_fall_used"):
        return None
    from .needle import ask, checkpoint_id
    if not ask(engine, intent, checkpoint_id(engine, FALL, subject.entity_id), subject,
               "choice:needle.fall_seven_ways", ["protect"], allow_decline=True,
               name="Fall Seven Ways", feature_id=FALL, target_id=subject.entity_id,
               labels={"protect": "Reduce this falling damage to 0; then choose a legal landing step up to 10 feet"},
               prompt=f"Fall Seven Ways: {subject.display_name} would take {defended} falling damage. Reduce it to 0? Once per scene; no resource or action cost."):
        return None
    subject.turn_flags["_round_insights3_fall_used"] = 1
    subject.turn_flags["insights3_fall_step"] = 1
    return {"amount": 0}


@hook("fall_landed")
def landing_step(engine, subject, fall, intent):
    if not owns(engine, subject, FALL) or not subject.turn_flags.pop("insights3_fall_step", None):
        return
    from ..gate2_runtime_models import ActionDefinition
    from ..typed_executor import Context, run_effects
    action = ActionDefinition(source_definition_id=FALL, display_name="Fall Seven Ways", owner_id=subject.entity_id,
                              economy="NONE", resolution_kind="TYPED", target_kind="SELF")
    ctx = Context(engine, subject, action, intent, {"numbers": owns(engine, subject, FALL)}, [subject], subject)
    # The printed landing movement does not grant an opportunity exemption.
    run_effects(ctx, [{"type": "rider_step", "distance_ft": 10, "label": "Fall Seven Ways"}])
