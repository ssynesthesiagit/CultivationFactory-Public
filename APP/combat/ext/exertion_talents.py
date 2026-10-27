"""The Berserker sphere's Exertion talents: one shared registry, chooser and applier.

Print (APP/authority/typed_mechanics/rules_text.json, TAL_BERSERKER_BATTER): "Exertion talents exploit the opening
created by Batter."  The sphere rule is ONE per Batter (owner ruling 2026-09-29), which combat/ext/gu_berserker.py
delivers as a free standing toggle ("Exertion: Bone-Breaker", kept until changed).  Three printed abilities need the
same machinery with a bigger number:

  Extended Exertion                      "Apply two Exertion talents to one Batter attack by: spending a Bonus
                                         Action; or expending Martial Focus."
  Heaven-Crushing Exertion               "Before rolling, choose three Exertion talents you know. Apply all three on a
                                         hit."  ("Heaven-Crushing Exertion cannot be combined with Extended Exertion.")
  The Blow Heaven Refused to Receive     "Before rolling: ... choose up to four Exertion talents you know".

So this module owns the three things all four abilities need, once:

  the registry   TALENTS: key -> (printed talent id, the plain name a player reads).  A talent's effect is not
                 re-written here; it is read from the fighter's own compiled "Batter: <talent>" variant, which is
                 where the typed pipeline already put it.
  the choice     ``ask`` opens one menu over the Exertion talents this fighter owns and returns up to ``cap`` of them,
                 no duplicates, through combat/ext/needle.py's own choice transport (``choice:needle.*``; the provider
                 is needle.py's, so a manual or Ask me player really is asked, on their own turn and on an AI turn).
                 A player is asked (checklist 9); an AI fighter answers from its ``preferred`` order; a fight nobody is
                 answering keeps the standing toggle's choice, so old saved fights and headless runs behave exactly as
                 before.  An explicit decline is an empty answer, never a silent fallback to another talent.
                 ``include_standing=False`` is for an ability whose set is complete on its own (Heaven-Crushing
                 Exertion, The Blow); Extended Exertion's extra slot leaves the standing talent out, because that
                 attack already applies it.
  the application ``apply`` runs each chosen talent on the target: rows the fighter's own variant carries for that
                 talent id, and for the three that need custom code (Bone-Breaker, Bell-Ringer, Cultivation Sunder)
                 combat/ext/gu_berserker.py's public ``apply_exertion``.

Consumers: combat/ext/gu_berserker.py (the standing toggle and its after_hit), combat/ext/berserker.py (Extended
Exertion's armed second talent, Heaven-Crushing Exertion, The Blow Heaven Refused to Receive).

Nothing here keys on an ability id to decide behaviour: an Exertion talent is applied because the fighter owns it and
chose it, so a talent added to the registry later needs no other change.  Characters without an Exertion talent own
no key and get nothing.

Two talents change the attack roll itself (Brutal Strike, Reaper's Momentum), so they cannot be applied on a hit and
are never in a menu this module builds.  The printed way to use them is their own "Batter + <talent>" attack variant:
combat/ext/docket_maneuvers.py composes the penalty and the talent's on-hit effect onto that attack, and
combat/ext/pre_roll_attack.py folds them into the row and the first roll so the table reads the same numbers the fight
rolls.  A set chosen before the roll still cannot add them to a different, already compiled attack -- this module does
not pretend otherwise and does not tell the player to resolve anything by hand.
"""

from __future__ import annotations

from typing import Any

from . import hook

# key -> (printed mechanic id, the name the player reads).  ``CUSTOM`` marks the three whose effect is not a row on a
# compiled "Batter: <talent>" variant but gu_berserker.py's own after_hit code.  Bone-Breaker is first because it was
# first in the pre-registry EXERTION_TALENTS dict (base commit 3324732c) and a fighter who never pressed the toggle has
# always defaulted to the first talent it owns; the rest keep alphabetical order.
TALENTS: dict[str, tuple[str, str]] = {
    "bone_breaker": ("TAL_BERSERKER_BONE_BREAKER", "Bone-Breaker"),
    "bell_ringer": ("TAL_BERSERKER_BELL_RINGER", "Bell-Ringer"),
    "brutal_strike": ("TAL_BERSERKER_BRUTAL_STRIKE", "Brutal Strike"),
    "cultivation_sunder": ("TAL_BERSERKER_CULTIVATION_SUNDER", "Cultivation Sunder"),
    "heaven_shaking_batter": ("TAL_BERSERKER_HEAVEN_SHAKING_BATTER", "Heaven-Shaking Batter"),
    "heavy_swing": ("TAL_BERSERKER_HEAVY_SWING", "Heavy Swing"),
    "leg_smasher": ("TAL_BERSERKER_LEG_SMASHER", "Leg-Smasher"),
    "reapers_momentum": ("TAL_BERSERKER_REAPER_S_MOMENTUM", "Reaper's Momentum"),
}
CUSTOM = {"bell_ringer", "bone_breaker", "cultivation_sunder"}
# Two printed talents change the attack roll itself -- Brutal Strike ("take -5 to the attack roll") and Reaper's
# Momentum ("take -5 to the Batter attack roll") -- so they can only be applied BEFORE the roll.  They are chosen the
# way the printed sphere builds them: as their own "Batter: <talent>" attack variant (combat/ext/docket_maneuvers.py,
# folded for display and resolution by combat/ext/pre_roll_attack.py), never as something applied on a hit, which
# would hand out their bonus without their penalty.  POST_HIT is therefore the menu's universe.
PRE_ROLL = {"brutal_strike", "reapers_momentum"}
# Printed talents whose own text asks for a second, different effect when the target was already Battered
# (Heaven-Shaking Batter: "If the target was already Battered, choose two different effects instead of one").
TWO_IF_BATTERED = {"heaven_shaking_batter"}
POST_HIT = [key for key in TALENTS if key not in PRE_ROLL]
# The standing toggle's condition (combat/ext/gu_berserker.py) and this module's turn-keyed store for a choice made
# for one attack.  Both hold plain strings only, so a saved fight reloads them unchanged.
CHOICE = "condition:typed.gu_berserker_exertion_choice"
CHOICE_KEY = "berserker_exertion_choice"
# Needle's own choice transport (combat/ext/needle.py's choice_options provider owns every "choice:needle.*" id, so a
# manual or Ask me player is really asked these two menus).
CHOICE_SET = "choice:needle.berserker_exertion_set"
CHOICE_OPTION = "choice:needle.berserker_exertion_option"


def label(key: str) -> str:
    return TALENTS.get(key, (None, key.replace("_", " ").title()))[1]


def mechanic_id(key: str) -> str:
    return TALENTS.get(key, (None, ""))[0]


def is_talent(mid: str) -> bool:
    """Whether a printed talent id is one of the Exertion talents (an attack variant that already spent its one)."""
    return str(mid) in {value[0] for value in TALENTS.values()}


def key_for(mid: str) -> str:
    """The registry key of the printed Exertion talent id ``mid``, or "" when it names no talent.

    The reverse of :func:`mechanic_id`, and how a row that a talent contributed is traced back to that talent: the
    compiler stamps those rows with ``source_modifier`` naming the talent, so a consumer can ask which talent a row
    belongs to without keying on an ability id.
    """
    for key, (value, _label) in TALENTS.items():
        if value == str(mid):
            return key
    return ""


def owns(engine: Any, actor_id: str, key: str) -> bool:
    """Whether this fighter's own compiled bundle carries Exertion talent ``key``."""
    return key in TALENTS and mechanic_id(key) in _talent_features(engine, actor_id)


# What each talent does, in plain words for someone who knows only basic D&D: what it does, who it affects, and how long
# it lasts.  Shown beside the talent's name in every Exertion menu so a choice can be made without the printed sheet.
SUMMARIES: dict[str, str] = {
    "bone_breaker": "each attack the target makes from now until the start of your next turn rolls 1d4 lower",
    "bell_ringer": "the target has Disadvantage on Intelligence saving throws and Intelligence checks until the start of "
                   "your next turn",
    "brutal_strike": "your attack roll is 5 lower, and a hit deals 10 extra damage",
    "cultivation_sunder": "your damage may break one lasting supernatural effect on the target, on the ground you struck, "
                          "or on a Barrier you struck (the GM judges how strong that effect is)",
    "heaven_shaking_batter": "choose one: push the target 15 feet, knock it Prone, deal 2d8 extra Force damage, damage an "
                             "unattended object or Barrier beside the target, or leave a 10-foot patch of difficult ground "
                             "around it (choose two of these if the target was already Battered)",
    "heavy_swing": "the target makes a Constitution saving throw; if it fails it cannot take Bonus Actions or Reactions "
                   "until the start of your next turn (and it is Stunned until then if it was already Battered)",
    "leg_smasher": "the target's Speed is halved (never below 5 feet) until the start of your next turn; if the target was "
                   "already Battered it also makes a Strength saving throw and falls Prone if it fails",
    "reapers_momentum": "your attack roll is 5 lower, and a hit lets you keep making further attacks against other "
                        "creatures nearby until that chain stops",
}
BEAT_DOWN_NOTE = ("This fighter's Beat Down is on, so an effect that would last until the start of your next turn lasts "
                  "until the start of your second turn instead.")


def choice_label(engine: Any, actor: Any, key: str) -> str:
    """One menu option, in plain words: the talent, what it does, and how long it lasts."""
    text = f"Apply {label(key)} to this attack: {SUMMARIES.get(key, 'its printed effect applies to the target')}"
    from . import berserker

    return f"{text} {BEAT_DOWN_NOTE}" if berserker.row(engine, actor, "beat_down") is not None else text


def dealt_damage(ctx: Any, target: Any) -> bool:
    """"When Batter deals damage, ..." keys off damage, not merely a hit (Iron Fist's Open the Gate makes the same
    distinction in typed_executor.block_attack); the recent-events check mirrors that precedent."""
    return any(event.event_type == "DAMAGE_COMMITTED" and target.entity_id in (event.target_ids or ())
               and int((event.payload or {}).get("hp_damage") or 0) + int((event.payload or {}).get("temporary_hp_absorbed") or 0) > 0
               for event in ctx.engine.events[-12:])


# ------------------------------------------------------------------------------------------------ what this fighter owns
def _talent_features(engine: Any, actor_id: str) -> set[str]:
    """Every printed Exertion talent id this fighter's own compiled bundle carries: its standing-toggle row plus the
    modifier id of each attack variant it owns (the fold itself is read from the fight, never a process-wide cache: an
    older saved fight's rows are the authority for it, the same lesson combat/ext/bodya_berserker.py's Advancing
    Carnage records)."""
    from ..typed_reactions import _rows

    found = {str(row.get("feature_id")) for row in _rows(engine, actor_id, "gu_berserker_exertion")}
    for action in engine.action_catalog.values():
        if action.owner_id != actor_id:
            continue
        typed = (action.parameters or {}).get("typed") or {}
        modifier = str(((typed.get("modifier") or {}) or {}).get("id") or "")
        if modifier:
            found.add(modifier)
    return found


def owned(engine: Any, actor_id: str) -> list[str]:
    """The Exertion talents this fighter owns that can be applied on a hit, in printed order."""
    found = _talent_features(engine, actor_id)
    return [key for key in POST_HIT if mechanic_id(key) in found]


def owned_probe(info: dict[str, Any]) -> list[str]:
    """The same list at compile time, from the sheet's own owned ids (before any catalog row exists)."""
    owned_ids = set(info.get("owned_ids") or ())
    return [key for key in POST_HIT if mechanic_id(key) in owned_ids]


def talent_effects(engine: Any, actor_id: str, key: str) -> list[dict[str, Any]]:
    """The effect rows this fighter's own compiled "Batter: <talent>" variant carries for ``key``.

    The typed pipeline puts an Exertion talent's rows on that attack's hit with ``source_modifier`` naming the
    talent, so they are read back from the character's own catalog rather than re-typed.  A talent whose printed text
    is a "choose one" menu (Heaven-Shaking Batter's five effects) has one variant per option; those are returned in
    printed order and :func:`apply` asks which one, exactly as choosing the attack variant would.
    """
    mid = mechanic_id(key)
    if not mid:
        return []
    out: list[dict[str, Any]] = []
    for action in sorted(engine.action_catalog.values(), key=lambda row: row.source_definition_id):
        typed = (action.parameters or {}).get("typed") or {}
        if action.owner_id != actor_id or not typed.get("variant_of"):
            continue
        if str(((typed.get("modifier") or {}) or {}).get("id") or "") != mid:
            continue
        attack = next((row for row in typed.get("effects") or []
                       if isinstance(row, dict) and row.get("type") == "attack"), None)
        rows = [{name: value for name, value in row.items() if name != "first_hit_only"}
                for row in (attack or {}).get("on_hit") or []
                if isinstance(row, dict) and row.get("source_modifier") == mid]
        if rows:
            # "Batter + Heavy Swing" or "Batter + Heaven-Shaking Batter: Push 15 Feet" -> what the player picks between.
            label = str(action.display_name).split(": ", 1)[-1]
            label = label.split(" + ", 1)[-1] if " + " in label else label
            out.append({"label": label, "rows": rows})
    return out


# ------------------------------------------------------------------------------------------------ the standing choice
def standing(actor: Any) -> list[str]:
    """The standing toggle's choice(s).  An older saved fight stored one string under "choice"; both are read."""
    for condition in actor.conditions.values():
        if condition.condition_id != CHOICE:
            continue
        data = condition.data or {}
        keys = [str(item) for item in data.get("choices") or []]
        if not keys and data.get("choice"):
            keys = [str(data["choice"])]
        return [key for key in keys if key in TALENTS]
    return []


def write_standing(engine: Any, actor: Any, key: str, source: str) -> None:
    """Store the standing Exertion talent, one at a time, under the same data keys as before (so an old saved fight and
    the player-facing status text combat/ext/generated_status_text.py both read it unchanged).  A talent that applies
    MORE than one (Extended Exertion) holds its extra slot separately, in a turn flag."""
    engine._remove_condition(actor, CHOICE, source)
    if key not in TALENTS:
        return
    engine._apply_condition(actor, CHOICE, source, actor.entity_id, expires_on="UNTIL_REMOVED",
                            data={"choice": key, "label": f"Exertion: {label(key)}"})


def turn_key(engine: Any, purpose: str, actor: Any) -> str:
    """Where one attack's choice is held: a plain ``turn_flags`` string, cleared by the engine at this fighter's next
    turn (combat/gate2_engine.py's turn-start filter keeps only ``_round_``/``once_per_round:`` keys)."""
    return f"{CHOICE_KEY}:{purpose}"


def pick_up(engine: Any, actor: Any, purpose: str) -> list[str]:
    raw = actor.turn_flags.get(turn_key(engine, purpose, actor))
    return [key for key in str(raw or "").split(",") if key in TALENTS]


def pick_down(engine: Any, actor: Any, purpose: str) -> None:
    actor.turn_flags.pop(turn_key(engine, purpose, actor), None)


# ------------------------------------------------------------------------------------------------ ask and apply
def ask(engine: Any, actor: Any, intent: Any, *, cap: int, purpose: str, feature_id: str, name: str, prompt: str,
        target: Any = None, include_standing: bool = True) -> list[str]:
    """Ask which Exertion talents to apply to one attack, at most ``cap`` of them, and remember the answer for that hit.

    Falls back to the standing toggle's choice (then to the first talent the fighter owns) only when nobody answered,
    so a headless run and an old saved fight behave exactly as they did before.  A player who answered and declined gets
    nothing applied, which is a different event and is never replaced by a fallback.

    ``include_standing=False``: the standing talent is one of the options, for an ability that applies a complete set of
    its own (Heaven-Crushing Exertion, The Blow Heaven Refused to Receive).  Extended Exertion's second slot leaves it out,
    because that attack already applies the standing choice.
    """
    keys = owned(engine, actor.entity_id)
    if not keys or cap < 1:
        # A fighter whose only Exertion talents are the two pre-roll ones owns nothing this module can apply on a hit;
        # those are used as their own "Batter + <talent>" attack, so there is no menu and nothing left to say by hand.
        return []
    already = pick_up(engine, actor, purpose)
    if already:
        return already[:cap]
    from . import needle
    from .choice_prompt import action_context

    options = [key for key in keys if not (include_standing and key in standing(actor))] or keys
    fallback = [key for key in standing(actor) if key in options][:cap] or options[:1]
    if target is not None:
        prompt = f"{prompt} Each one applies to {target.display_name}."
    checkpoint = needle.checkpoint_id(engine, "EXERTION_SET", feature_id, actor.entity_id)
    chosen = needle.ask(engine, intent or getattr(engine, "_active_intent", None), checkpoint,
                        actor, CHOICE_SET, options,
                        labels={key: choice_label(engine, actor, key) for key in options},
                        minimum=0, maximum=min(cap, len(options)), allow_decline=True,
                        preferred=[key for key in fallback if key in options], default="all",
                        default_count=len([key for key in fallback if key in options]),
                        name=name, feature_id=feature_id,
                        target_id=(target.entity_id if target is not None else None),
                        prompt_context=action_context(engine, actor, feature_id, target) if target is not None else None,
                        prompt=prompt)
    if not chosen and needle.answered(engine, checkpoint, actor, CHOICE_SET):
        return []  # answered and declined: nothing is applied and nothing is remembered
    picked = [key for key in chosen if key in options][:cap] or fallback
    actor.turn_flags[turn_key(engine, purpose, actor)] = ",".join(picked)
    return picked


def armed(engine: Any, actor: Any, purpose: str = "", *, variant_spent: bool = False) -> list[str]:
    """The talents this hit applies: the standing toggle's choice, plus any second slot armed for this attack.

    With nothing chosen the first talent the fighter owns is used, the default this toggle has always had (the built-in
    AI needs a choice nobody makes for it).  Empty when the fighter owns no Exertion talent at all.

    ``variant_spent``: this attack IS a "Batter: <talent>" variant, which already spent the printed one Exertion talent
    of that attack on itself, so the standing toggle does not run again on it.
    """
    keys = owned(engine, actor.entity_id)
    chosen = standing(actor)
    picked: list[str] = [] if variant_spent else (chosen[:1] if chosen and chosen[0] in keys else keys[:1])
    for key in extra_slot(engine, actor, purpose) if purpose else []:
        if key in keys and key not in picked:
            picked.append(key)
    return picked


def extra_slot(engine: Any, actor: Any, purpose: str) -> list[str]:
    """The second talent armed for one attack (Extended Exertion's paid slot), while it is still armed."""
    return pick_up(engine, actor, f"extended:{purpose}") if purpose else []


def spend_extra_slot(engine: Any, actor: Any, purpose: str) -> list[str]:
    """Take the armed second talent off the turn: whatever applied it paid for it once, so the next plain Batter this
    turn gets the standing choice only (checklist 8: one payment, one use)."""
    armed_here = extra_slot(engine, actor, purpose)
    pick_down(engine, actor, f"extended:{purpose}")
    return armed_here


def apply(ctx: Any, target: Any, keys: list[str], *, once_per_attack: bool = True, more_if_battered: bool = False) -> None:
    """Run each chosen Exertion talent's own effect on ``target``.

    ``once_per_attack`` drops the ``damage_bonus_*`` bookkeeping the maneuver pipeline adds, so a talent applied out of
    a standing choice is worked out once on this hit like any other Exertion talent.

    ``more_if_battered`` honours Heaven-Shaking Batter's printed "If the target was already Battered, choose two
    different effects instead of one": that talent's second option is asked for and applied, with the first excluded.
    """
    from .. import typed_executor as te

    for key in dict.fromkeys(keys):
        if key in CUSTOM:
            from . import gu_berserker

            gu_berserker.apply_exertion(ctx, key, target)
            continue
        options = talent_effects(ctx.engine, ctx.actor.entity_id, key)
        if not options:
            continue
        picks = _choose_option(ctx, target, key, options)
        if not picks:
            continue
        cleaned = []
        for row in options[picks[0]]["rows"]:
            row = _stamped(row, key)
            if once_per_attack:
                row.pop("damage_bonus_group", None)
                row.pop("damage_bonus_stage", None)
            cleaned.append(row)
        te.run_effects(te.Context(ctx.engine, ctx.actor, ctx.action, ctx.intent, ctx.typed, [target], target,
                                  dict(ctx.damage_cache)), cleaned)
        if more_if_battered and key in TWO_IF_BATTERED:
            rest = [option for index, option in enumerate(options) if index != picks[0]]
            second = _choose_option(ctx, target, key, rest, again=True) if len(rest) > 1 else []
            if not second:
                continue
            again = []
            for row in rest[second[0]]["rows"]:
                row = _stamped(row, key)
                if once_per_attack:
                    row.pop("damage_bonus_group", None)
                    row.pop("damage_bonus_stage", None)
                again.append(row)
            te.run_effects(te.Context(ctx.engine, ctx.actor, ctx.action, ctx.intent, ctx.typed, [target], target,
                                      dict(ctx.damage_cache)), again)


_NESTED_KEYS = ("effects", "on_hit", "on_fail", "on_success", "on_miss")


def _stamped(row: dict[str, Any], key: str) -> dict[str, Any]:
    """A copy of one talent row that names the talent on the row AND on every row nested inside it.

    The compiler stamps ``source_modifier`` on the rows a talent contributes, but a talent's effect is often a whole tree:
    Heavy Swing's printed "cannot take Reactions until the start of your next turn" and its Stun live inside the
    ``on_fail`` of the saving throw, and those inner rows carry no stamp of their own.  Beat Down reads the stamp to
    decide whether a lasting effect belongs to an Exertion talent (combat/ext/berserker.py), so the stamp is carried
    down over the copies this applier runs.  Only copies are touched -- the fighter's compiled catalog is left alone.
    """
    import copy

    out = copy.deepcopy(row)
    out.setdefault("source_modifier", mechanic_id(key))
    for name in _NESTED_KEYS:
        children = out.get(name)
        if not isinstance(children, list):
            continue
        out[name] = [_stamped(child, key) if isinstance(child, dict) and child.get("type") != "attack" else child
                     for child in children]
    return out


def _choose_option(ctx: Any, target: Any, key: str, options: list[dict[str, Any]], *, again: bool = False) -> list[int]:
    """The printed "choose one" of a talent's own menu, as the attack variant would: ask, never more than one."""
    if len(options) == 1:
        return [0]
    from . import needle

    picked = needle.ask(ctx.engine, ctx.intent or getattr(ctx.engine, "_active_intent", None),
                        needle.checkpoint_id(ctx.engine, "EXERTION_OPTION", key, target.entity_id, "2" if again else "1"),
                        ctx.actor, CHOICE_OPTION, [str(index) for index in range(len(options))],
                        labels={str(index): option["label"] for index, option in enumerate(options)},
                        minimum=1, maximum=1, allow_decline=True, default="first",
                        name=f"Exertion talent: {label(key)}", feature_id=mechanic_id(key), target_id=target.entity_id,
                        prompt=f"{label(key)}: {ctx.actor.display_name}'s {ctx.action.display_name} does exactly one of these to "
                               f"{target.display_name}. Which one?"
                               + (" Choose a different one from the effect you already chose." if again else ""))
    return [int(picked[0])] if picked else []