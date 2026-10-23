"""Damage taken in another creature's place (sys-resources-states 2026-09-29, system D): Take the Blow, Oath of Mutual Defense,
Painless Martyr's Divide the Blow, Shared Burden's Divide the Pain and Chain of Devotion.

Source (owner text, authority/typed_mechanics/rules_text.json; none of these has a Spheres 5e or D&D 5.5e counterpart):
  Take the Blow (Guardian talent, CL 10, Reaction, an ally within 30 feet takes damage): take half of the triggering damage, rounded
    down, instead of the ally, who takes the remainder. Your portion keeps the original damage types, may be reduced by your
    Resistance, Immunity or ordinary damage reductions, and cannot be transferred again. After taking it, gain Temporary HP equal to
    your Proficiency Bonus.
  Oath of Mutual Defense (Karma, ritual, 3 CP, 8 hours): binds up to Proficiency Bonus willing creatures. Once per round, when a bound
    creature within 60 feet of another bound creature takes damage, another bound creature may use its Reaction to take half the
    damage, rounded down; the original target takes the remainder; it cannot be transferred again. (The Grace Imprint it allows is
    system C.)
  Painless Martyr / Divide the Blow (Mercy Flayer CL 14, Reaction, 5 Resonance, an ally within 30 feet): half, rounded down; damage type
    and bypass properties kept; it "cannot be reduced below your Proficiency Bonus unless the triggering damage was already lower".
    If it would take you to 0 Hit Points it still resolves (the engine's own defeat follows).
  Shared Burden / Divide the Pain (Grief Eater CL 10, Reaction, 4 Resonance or 2 Sorrow Burdens, an ally within 30 feet takes Psychic,
    Necrotic or Force damage): half, rounded UP; "your share cannot be reduced, redirected, or converted into healing".
  Chain of Devotion (Heartbinder CL 14): once per round, when a linked creature within 60 feet takes damage, another willing linked
    creature may use its Reaction to take any portion of it, up to half, after Resistance and before Temporary Hit Points; it keeps
    its type and source and "cannot be reduced again by the receiving creature's Resistance". (The link is combat/ext/heartbinder.py.)

How it runs: typed_reactions.on_damage asks the ``damage_pending`` hook for the damage about to land on a creature (after the target's
own Resistance, before its Temporary HP). This plug-in splits the damage: the taker's portion is committed on the taker through the
engine's own _commit_damage (so its Resistance, Temporary HP, concentration check and defeat all happen as for any hit), and the rest
is returned for the target to take. The taker's portion is committed without a reaction intent, so it cannot be answered or
shared again. Three kinds have an owner-side row (feature block ``damage_sharing``: Take the Blow, Divide the Blow, Divide the
Pain); the two link kinds are carried by a condition on each linked creature (data["share"]), because a bound or linked creature
need not own the talent.
Readings the text does not settle (each a judgment; the report lists them):
  * Oath and Chain portions are taken after the taker's own Resistance like any damage; only Chain and Divide the Pain say
    "not reduced again", so those two are committed unreduced (typed_reactions.defend is skipped through engine._damage_unreduced).
  * One share per instance of damage; the taker is chosen in the order Take the Blow, Oath, Chain, Divide the Pain, Divide the Blow
    (the cheapest first), nearest ally first.
  * The built-in AI shares when the taker would stay standing and the share keeps the target up, or (a free share only) leaves
    the target with a smaller part of its Hit Points than the taker; a costly share only to keep the target up. A player's
    character set to Ask me is asked (checkpoint DAMAGE_SHARE); otherwise it is used automatically.
  * Chain takes exactly half (rounded down): "any portion, up to half" and the AI has no reason to take less.
  Shared Breath Guardian (Spirit Companions Insight, Reaction): "A spirit joined to you ... within 30 feet would take damage.
    Transfer half of the triggering damage to yourself ... Determine the damage ... before applying the spirit's Resistance,
    Immunity, or Vulnerability ... You receive the smaller half, rounded down; the spirit receives the remainder. Apply your own
    Resistance, Immunity, and Vulnerability to your share and the spirit's to its share". A row with ``subject: "own_summon"``
    only answers damage to a creature summoned by the taker, in the row's ``subject_groups`` (the bonded spirit family); its
    ``timing: "before_defenses"`` splits the packet through ``pre_defense_transfer`` (typed_reactions.defend) before the spirit's
    own defenses, Immunity included. A spirit Hosted inside its cultivator is not a separate creature on the map, so the printed
    Hosted reduction stays the GM's.
Plug-in surface: hooks damage_pending, pre_defense_transfer, decision_text, event (TURN_STARTED of the first turn binds the Oath),
compile_block ("damage_sharing").
Not automated: the Grace Imprint of Oath (system C), Carry the Failure / Carry the Echo / Catch the Wound / Hold the Door (their
delay and reroll halves are separate systems).
"""

from __future__ import annotations

from ..paid_relocation import activation

import math
from typing import Any

from . import hook, note, run
from .damage_transfer_scope import nonrecursive_transfer, transfers_allowed

BASE = "damage_sharing:"
OATH = "condition:typed.oath_of_mutual_defense"
CHAIN = "condition:typed.devotion_chain"
_ORDER = ("take_the_blow", "mutual_defense", "chain_of_devotion", "divide_the_pain", "divide_the_blow")
_LINKS = ("mutual_defense", "chain_of_devotion")  # carried by a condition on each linked creature, never an owner-side offer
_LABEL = {"take_the_blow": "Take the Blow", "mutual_defense": "Oath of Mutual Defense", "chain_of_devotion": "Chain of Devotion",
          "divide_the_pain": "Shared Burden (Divide the Pain)", "divide_the_blow": "Painless Martyr (Divide the Blow)"}
_RESOURCES = {"resonance": "resource:core.resonance", "qi": "resource:core.qi", "stamina": "resource:core.stamina"}


def resource_id(name: str) -> str:
    slug = "".join(ch if ch.isalnum() else "_" for ch in str(name).lower()).strip("_")
    return _RESOURCES.get(slug) or "resource:named." + "_".join(part for part in slug.split("_") if part)


@hook("compile_block")
def compile_row(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Feature block ``damage_sharing``: {"kind", "label", "range_ft", "types", "rounding", "floor", "unreduced", "temp_hp", "cost": [{"resource",
    "amount"} (alternatives)], "oath": true for the rite that binds the Oath, "subject": "ally" (default) or "own_summon" with "subject_groups",
    "allow_self_source": false (default) or true when the printed trigger includes the taker's own damage,
    "timing": "after_defenses" (default: the packet the target's own defenses left, damage_pending) or "before_defenses" (the packet
    before any of the target's defenses, pre_defense_transfer)}.
    A row of the Oath is the rite only; its bound creatures carry the share."""
    if block != "damage_sharing":
        return None
    costs = [{"resource_id": resource_id(option["resource"]), "amount": int(option["amount"]), "name": option["resource"]} for option in spec.get("cost") or []]
    return [{**row, "kind": spec.get("kind"), "range_ft": int(spec.get("range_ft") or 30), "types": [str(kind).upper() for kind in spec.get("types") or []],
             "rounding": spec.get("rounding") or "down", "floor": spec.get("floor"), "unreduced": bool(spec.get("unreduced")),
             "temp_hp": spec.get("temp_hp"), "costs": costs, "oath_cp": int(spec.get("rite_cp") or 0), "pb": int(numbers.get("pb") or 2),
             "label": spec.get("label"), "subject": spec.get("subject") or "ally", "subject_groups": [str(g) for g in spec.get("subject_groups") or []],
             "timing": spec.get("timing") or "after_defenses", "allow_self_source": bool(spec.get("allow_self_source"))}]


# ------------------------------------------------------------------------------------------------------ who may take a share
def _rows(engine: Any, actor: Any) -> list[dict[str, Any]]:
    from .. import typed_reactions

    return typed_reactions._rows(engine, actor.entity_id, "damage_sharing")


def link(actor: Any, condition_id: str) -> Any | None:
    return next((c for c in actor.conditions.values() if c.condition_id == condition_id), None)


def _linked(a: Any, b: Any, condition_id: str) -> tuple[Any, Any] | None:
    left, right = link(a, condition_id), link(b, condition_id)
    if left is None or right is None:
        return None
    owner = ((left.data or {}).get("share") or {}).get("owner")
    return (left, right) if owner and owner == ((right.data or {}).get("share") or {}).get("owner") else None


def _offers(engine: Any, target: Any, dtype: str) -> list[tuple[Any, dict[str, Any]]]:
    """Every (taker, offer) that could take part of the damage the target is about to take, in the order they are tried."""
    found: list[tuple[Any, dict[str, Any]]] = []
    for taker in engine.state.actors.values():
        if not taker.active or taker.entity_id == target.entity_id or taker.team_id != target.team_id:
            continue
        distance = engine.grid.distance_ft(taker.position, target.position)
        for row in _rows(engine, taker):
            if row.get("kind") not in _LINKS and distance <= row["range_ft"] and _subject_ok(taker, target, row) \
                    and (not row["types"] or dtype in row["types"]):
                found.append((taker, row))
        for condition_id, kind, limit in ((OATH, "mutual_defense", 60), (CHAIN, "chain_of_devotion", 60)):
            pair = _linked(taker, target, condition_id)
            if pair is not None and distance <= limit:
                owner = ((pair[0].data or {}).get("share") or {}).get("owner")
                found.append((taker, {"feature_id": BASE + kind, "kind": kind, "range_ft": limit, "types": [], "rounding": "down", "floor": None,
                                      "unreduced": kind == "chain_of_devotion", "temp_hp": None, "costs": _chain_cost(condition_id), "owner": owner,
                                      "block": "damage_sharing", "pb": int(taker.proficiency_bonus)}))
    return sorted(found, key=lambda pair: (_rank(pair[1]), engine.grid.distance_ft(pair[0].position, target.position), pair[0].entity_id))


def _rank(row: dict[str, Any]) -> int:
    """The order offers are tried in (see the module note); a kind added by data alone comes after the printed five."""
    return _ORDER.index(row["kind"]) if row["kind"] in _ORDER else len(_ORDER)


def _subject_ok(taker: Any, target: Any, row: dict[str, Any]) -> bool:
    """Whose damage the row answers: any ally, or (``own_summon``) only a creature the taker summoned, of the named groups."""
    if row.get("subject", "ally") != "own_summon":
        return True
    record = getattr(target, "summon", None) or {}
    groups = row.get("subject_groups") or []
    return record.get("owner") == taker.entity_id and (not groups or record.get("group") in groups)


def _label(row: dict[str, Any]) -> str:
    return str(row.get("label") or _LABEL.get(row["kind"]) or row["kind"].replace("_", " ").title())


def _chain_cost(_condition_id: str) -> list[dict[str, Any]]:
    return []  # neither link costs anything but the Reaction


def _round_key(row: dict[str, Any]) -> str | None:
    owner = row.get("owner")
    return f"once_per_round:share:{row['kind']}:{owner}" if owner else None


def _used_this_round(engine: Any, row: dict[str, Any]) -> bool:
    key = _round_key(row)
    holder = engine.state.actors.get(row.get("owner") or "")
    return bool(key and holder is not None and holder.turn_flags.get(key) == engine.state.round_number)


def _affordable(taker: Any, row: dict[str, Any]) -> dict[str, Any] | None:
    """The first cost alternative the taker can pay (None if the share is free: an empty dict; unaffordable: None)."""
    if not row["costs"]:
        return {}
    return next((option for option in row["costs"] if taker.resources.get(option["resource_id"], 0) >= option["amount"]), None)


def _portion(row: dict[str, Any], pending: int) -> int:
    return math.ceil(pending / 2) if row["rounding"] == "up" else pending // 2


def _worth(taker: Any, target: Any, row: dict[str, Any], pending: int, portion: int) -> bool:
    """The built-in AI's rule (see the module note)."""
    if taker.current_hp + taker.temporary_hp <= portion:
        return False  # it would fall: not worth a Reaction (the text lets it, but nobody would)
    held = target.current_hp + target.temporary_hp
    keeps_up = pending >= held > pending - portion
    if row["costs"] or row["kind"] == "divide_the_blow":
        return keeps_up
    if keeps_up:
        return True
    target_left = (held - pending) / max(1, target.maximum_hp)
    taker_left = (taker.current_hp + taker.temporary_hp - portion) / max(1, taker.maximum_hp)
    return taker_left > target_left


def _attacker(engine: Any, source_actor_id: str | None) -> Any | None:
    return engine.state.actors.get(source_actor_id) if source_actor_id else None


@hook("damage_pending")
def share(engine: Any, target: Any, pending: int, source_definition_id: str, source_actor_id: str | None) -> int:
    """Let a creature that can take part of the damage do so (see the module note); returns what the target takes."""
    from .. import typed_reactions

    if pending < 1 or not target.active or not transfers_allowed(engine, target):
        return pending
    dtype = str(getattr(engine, "_typed_pending_damage_type", None) or "UNTYPED").upper()
    attacker = _attacker(engine, source_actor_id)
    for taker, row in _offers(engine, target, dtype):
        if row.get("timing") == "before_defenses":
            continue  # already offered before the target's defenses (before_defenses below)
        portion = _portion(row, pending)
        if portion < 1 or not typed_reactions._can_react(engine, taker) or _used_this_round(engine, row):
            continue
        if not typed_reactions._ally_row_ok(engine, taker, attacker, target, {
                "feature_id": row["feature_id"], "allow_self_source": row.get("allow_self_source", row.get("subject") == "own_summon")}):
            continue
        cost = _affordable(taker, row)
        if cost is None or not _worth(taker, target, row, pending, portion):
            continue
        if not typed_reactions._consent(engine, {"feature_id": row["feature_id"], "ask": True}, taker, "DAMAGE_SHARE"):
            continue
        return pending - _take(engine, taker, target, row, cost, portion, pending, dtype, source_definition_id, source_actor_id)
    return pending


@hook("pre_defense_transfer")
def before_defenses(engine: Any, target: Any, amount: int, dtype: str, source_definition_id: str | None,
                    source_actor_id: str | None) -> int | None:
    """A ``before_defenses`` row: split the packet before any of the target's own defenses (Shared Breath Guardian:
    "Determine the damage ... before applying the spirit's Resistance, Immunity, or Vulnerability ... Apply your own
    Resistance, Immunity, and Vulnerability to your share and the spirit's to its share"). Only inside an accepted
    action (a reaction needs its moment). A player's Ask-me owner is offered every legal share -- falling to take it is
    the player's call; the built-in AI's preference (``_worth``) applies only to an automatic owner. The prompt carries
    the real trigger: who dealt the damage, with what, to which creature, and how much."""
    from .. import typed_reactions

    if amount < 2 or not target.active or getattr(engine, "_active_intent", None) is None \
            or not transfers_allowed(engine, target):
        return None
    attacker = _attacker(engine, source_actor_id)
    for taker, row in _offers(engine, target, dtype):
        if row.get("timing") != "before_defenses":
            continue
        portion = _portion(row, amount)
        if portion < 1 or not typed_reactions._can_react(engine, taker) or _used_this_round(engine, row):
            continue
        if not typed_reactions._ally_row_ok(engine, taker, attacker, target, {
                # Old sealed own-summon rows lack this optional admission field.
                "feature_id": row["feature_id"], "allow_self_source": row.get("allow_self_source", row.get("subject") == "own_summon")}):
            continue
        cost = _affordable(taker, row)
        if cost is None:
            continue
        reaction = {"feature_id": row["feature_id"], "ask": True}
        if not typed_reactions._asking(engine, taker, reaction) and not _worth(taker, target, row, amount, portion):
            continue
        if not typed_reactions._consent(engine, reaction, taker, "DAMAGE_SHARE", trigger={
                "actor_id": source_actor_id, "target_id": target.entity_id, "source_id": source_definition_id,
                "damage_amount": amount}):
            continue
        return _take(engine, taker, target, row, cost, portion, amount, dtype, source_definition_id, source_actor_id)
    return None


@hook("decision_text")
def share_decision_text(engine: Any, context: dict[str, Any], printed_rules: dict[str, str]) -> dict[str, Any] | None:
    """Plain wording for a share prompt that carries its real trigger (the amount and the creature hit); presentation only."""
    feature = str(context.get("reaction_source_id") or "").removeprefix("reaction:typed.")
    reactor = engine.state.actors.get(context.get("reactor_id") or "")
    trigger = context.get("choice_trigger") or {}
    row = next((r for r in (_rows(engine, reactor) if reactor is not None else []) if r.get("feature_id") == feature), None)
    hurt = engine.state.actors.get(trigger.get("target_id") or "")
    if row is None or hurt is None or trigger.get("damage_amount") is None:
        return None
    amount = int(trigger["damage_amount"])
    portion = _portion(row, amount)
    before = row.get("timing") == "before_defenses"
    return {"feature_id": feature, "cost": "Your Reaction",
            "summary": (f"{hurt.display_name} is about to take {amount} damage. Take {portion} of it yourself "
                        f"({'half, rounded up' if row.get('rounding') == 'up' else 'half, rounded down'}); "
                        + ("your own Resistance, Immunity and Vulnerability apply to your part, and "
                           f"{hurt.display_name}'s own defenses apply to the other {amount - portion}."
                           if before else f"{hurt.display_name} takes the other {amount - portion}.")
                        + " Your part keeps its damage type and cannot be passed on again.")}


def _take(engine: Any, taker: Any, target: Any, row: dict[str, Any], cost: dict[str, Any], portion: int, pending: int, dtype: str,
          source_definition_id: str, source_actor_id: str | None) -> int:
    """Pay, then commit the taker's portion; returns the part of the damage that left the target."""
    from .. import pending_damage, typed_reactions

    attacker_ids = (source_actor_id,) if source_actor_id else ()
    # The share is the same delivery as the packet it was passed from: ongoing damage stays ongoing (it cannot
    # rebound as a fresh blow), and a fresh hit stays fresh. Only this transfer carries the origin on.
    origin = getattr(pending_damage.current(engine), "damage_origin", None)
    with activation(engine, taker, row["feature_id"]):
        typed_reactions._open(engine, {"feature_id": row["feature_id"], "block": "damage_sharing"}, taker, attacker_ids, "DAMAGE_APPLICATION",
                              {"pending_damage": pending, "protects": target.entity_id, "share": row["kind"]})
        if cost:
            engine._spend_resource(taker, cost["resource_id"], cost["amount"], row["feature_id"])
        taker.reaction_available = False
        key = _round_key(row)
        holder = engine.state.actors.get(row.get("owner") or "")
        if key and holder is not None:
            holder.turn_flags[key] = engine.state.round_number  # a key that survives the turn's reset ("once_per_round:")
        with nonrecursive_transfer(engine, taker) as transfer_flags:
            taken = portion
            if not row["unreduced"]:  # recipient defenses run once, without another transfer
                taken = typed_reactions.defend(engine, taker, portion, dtype, source_definition_id, source_actor_id)
                if row.get("floor") == "pb":
                    taken = max(taken, min(int(taker.proficiency_bonus), portion))
            previous_unreduced = getattr(engine, "_damage_unreduced", None)
            previous_bonus = getattr(engine, "_damage_bonus_already_applied", None)
            engine._damage_unreduced = taker.entity_id  # defend ran (or is barred); do not defend twice
            engine._damage_bonus_already_applied = taker.entity_id if not row["unreduced"] else None
            try:
                hp_lost = engine._commit_damage(taker, taken, dtype, source_definition_id, source_actor_id or taker.entity_id, None,
                                                reaction_depth=2, source_flags=transfer_flags, damage_origin=origin)
            finally:
                engine._damage_unreduced = previous_unreduced
                engine._damage_bonus_already_applied = previous_bonus
        paid = f" ({cost['amount']} {str(cost['name']).title()})" if cost else ""
        note(engine, row["feature_id"], taker,
             f"{taker.display_name} takes {taken} of the {pending} {dtype.lower()} damage in place of {target.display_name} "
             f"({_label(row)}{paid}); {target.display_name} takes " + (
                 f"the other {pending - portion}, less its own defenses." if row.get("timing") == "before_defenses" else f"{pending - portion}."),
             (target,), taken=taken, hp_lost=hp_lost)
        run("damage_shared", engine, taker, target, row, source_actor_id, taken)  # Heartbinder's Devotion (combat/ext/heartbinder.py)
        grant = row.get("temp_hp")
        if grant and taker.active:  # "After taking your portion, gain Temporary HP equal to your Proficiency Bonus"
            engine._grant_temp_hp(taker, int(taker.proficiency_bonus) if grant == "pb" else int(grant), row["feature_id"], taker.entity_id)
        return portion


# ------------------------------------------------------------------------------------------------------ Oath of Mutual Defense
@hook("event")
def oath_at_fight_start(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """The Oath is a 10-minute ritual, worked before the fight: its caster binds itself and up to PB - 1 of its allies (nearest first) at the
    first turn, paying 3 CP once. The fight has no other place for a ritual."""
    if event_type != "TURN_STARTED" or not (kwargs.get("payload") or {}).get("initial") or getattr(engine, "_ds_oath_done", False):
        return
    engine._ds_oath_done = True
    for caster in list(engine.state.actors.values()):
        rite = next((row for row in _rows(engine, caster) if row.get("kind") == "mutual_defense" and caster.active), None)
        if rite is not None:
            _bind(engine, caster, rite)


def _bind(engine: Any, caster: Any, rite: dict[str, Any]) -> None:
    from ..typed_executor import CP_POOLS

    pool = max((rid for rid in CP_POOLS if caster.resource_maximums.get(rid, 0) > 0), key=lambda rid: caster.resources.get(rid, 0), default=None)
    cost = int(rite.get("oath_cp") or 3)
    if pool is None or caster.resources.get(pool, 0) < cost:
        return
    allies = sorted((a for a in engine.state.actors.values() if a.active and a.team_id == caster.team_id and a.entity_id != caster.entity_id
                     and a.entity_id in getattr(engine, "typed_actor_ids", set())),
                    key=lambda a: (engine.grid.distance_ft(a.position, caster.position), a.entity_id))
    bound = [caster, *allies[:max(0, int(rite["pb"]) - 1)]]
    if len(bound) < 2:
        return  # an oath of mutual defense needs someone to defend
    engine._spend_resource(caster, pool, cost, rite["feature_id"])
    for creature in bound:
        engine._apply_condition(creature, OATH, rite["feature_id"], caster.entity_id, expires_on=None, data={
            "share": {"owner": caster.entity_id}, "label": "Oath of Mutual Defense",
            "reading": f"Bound by {caster.display_name}'s oath: once per round, when a bound creature within 60 feet takes damage, another bound creature may "
                       "use its Reaction to take half of it (rounded down). What it takes cannot be shared again."})
    note(engine, rite["feature_id"], caster,
         f"{caster.display_name} binds {', '.join(c.display_name for c in bound)} in the Oath of Mutual Defense ({cost} CP, a ritual worked before the fight).",
         tuple(bound))
