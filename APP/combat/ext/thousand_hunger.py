"""Thousand-Hunger Adaptation: spend a stored Devoured Essence after one of ten printed damage types
lands on you and resist that type; at CL 17 the same payment adds your Proficiency Bonus of that type
to your next Daemonic damage roll.

"Prerequisite: CL 5+ -- When you take Acid, Cold, Fire, Lightning, Necrotic, Poison, Psychic, Radiant,
Thunder, or Force damage while Demon Seed is active, you may spend 1 Devoured Essence. Gain Resistance to
that damage type until the start of your next turn. At CL 11, the Resistance lasts until the end of your
next turn. At CL 17, when you gain this Resistance, your next damage roll with a Daemonic talent deals
additional damage of that type equal to Proficiency Bonus." (APP/authority/typed_mechanics/rules_text.json)

Ownership. A feature_blocks.d marker (combat/rules/feature_blocks.d/riders_c5.json, block
"thousand_hunger_adaptation") compiled through the compile_block hook, so only a character who owns
TAL_DAEMONIC_CULTIVATION_THOUSAND_HUNGER_ADAPTATION can adapt; anyone else returns at the ownership
gate and nothing of theirs changes. A bundle sealed before this marker, compiled from the same talent
through the retired "daemonic_thousand_hunger" block, is recognised by the same reader: its sealed row
carries no numbers, so the Cultivation Level comes from that character's own bundle. One provider serves
both markers; nothing reads the old block name anywhere else.

Seams. Documented in combat/ext/__init__.py.

* ``final_damage`` answers "when you take <type> damage". Every damage packet reaches it -- a typed
  ability, a native weapon attack, a zone or hazard -- and it hands the damage type, the incoming action
  and the attacking creature, which is what the printed question needs. It is also a strict
  transactional checkpoint, so the optional payment is asked before any Essence moves and a player's
  pause unwinds the packet and replays it with the answer. A typed-only seam (``damage_dealt``) cannot
  see native damage at all, which is why the older provider's event route is not used here.
* ``attack_packet_start`` covers the primary damage of a confirmed Daemonic attack, before defenses
  and HP commit, through its immutable attack provenance and the public typed attack scope. Native
  attacks and other components return immediately. ``deal_bonus`` covers the separate typed effects
  and riders; a sealed primary attack never reaches that hook. Both call the same gated delivery.
* ``deal_bonus`` answers "your next damage roll with a Daemonic talent" for separate typed effects. It is the documented
  per-recipient seam that runs after that talent's own damage ROLL and before its commit, so the CL 17
  clause is spent by the roll the printed text names -- "your next damage roll" -- whether or not that
  packet still costs the creature anything. A Resistance or Immunity that absorbs the roll to nothing,
  a roll the defenses reduce to nothing, and a roll that defeats the creature all still reach it; a
  notification that only arrived with positive damage committed would leave the clause waiting and hand
  it to a later, unrelated roll. The additional damage is OF THE ADAPTED TYPE -- its own packet,
  carrying that type -- rather than a larger number on a roll of whatever type the talent happened to
  use. "With a Daemonic talent" is resolved through the printed ability the damage is attributed to
  (ability_source.mechanic_at plus the authority's own sphere), which is also how a Daemonic talent's
  rider damage on someone else's weapon attack is recognised, while a matching-type roll from another
  sphere is not.
* ``choice_reactors`` answers "may this creature be asked?". A row sealed before this marker carries no
  ``choice_owner`` flag, so nothing else would enroll its owner and "you may spend 1 Devoured Essence"
  would be paid silently on a saved fight. This query enrolls exactly those owners; a row that already
  declares ``choice_owner`` needs nothing here.

Saved state. The unspent CL 17 clause is a single condition whose data is a damage-type string and an
integer Proficiency Bonus, and it is consumed through the engine's evented condition removal, so it
survives a table commit + reload and can only ever pay out once. Nothing else here is stored.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook

BLOCK = "thousand_hunger_adaptation"
LEGACY_BLOCK = "daemonic_thousand_hunger"  # bundles sealed before this marker; same provider, no numbers
FEATURE = "TAL_DAEMONIC_CULTIVATION_THOUSAND_HUNGER_ADAPTATION"
DEVOURED_ESSENCE = "resource:named.devoured_essence"
DEMON_SEED_STANCE = "condition:typed.stance.demon_seed"
PENDING = "condition:typed.thousand_hunger_adaptation"
DAEMONIC = "tianxia.sphere.daemonic_cultivation"
CHOICE = "choice:spend.thousand_hunger_adaptation"
# The ten types the printed text names, in its own order.
TYPES = ("acid", "cold", "fire", "lightning", "necrotic", "poison", "psychic", "radiant", "thunder", "force")


@hook("compile_block")
def compile_thousand_hunger(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]):
    if block == LEGACY_BLOCK:
        return [row]
    if block != BLOCK:
        return None
    # "you may spend" is the player's call, and it is asked on the creature that attacked them, so the
    # row marks choice_owner (combat/ext/__init__.py: a passive row with choice_owner exposes its
    # owner's decisions during AI turns too). A row sealed before this marker cannot carry the flag,
    # which is what the choice_reactors query below is for.
    return [{**row, "pb": int(numbers.get("pb") or 0), "cl": int(numbers.get("cl") or 1),
             "choice_owner": True}]


# A declarative marker, as in daemonic_riders.rider_seed_gate: it carries the printed clause into the
# compiled row so the ability is recognisable to readers of the compiled character, and keeps the
# plug-in opt-in for freshly compiled characters.
@effect("rider_thousand_hunger")
def marker(ctx: Any, spec: dict[str, Any]) -> None:
    pass


def _row(engine: Any, actor: Any) -> dict[str, Any] | None:
    """This creature's compiled Thousand-Hunger Adaptation row, under either marker, or None.

    The ownership gate for everything below: a character without the talent has no row.
    """
    if actor is None:
        return None
    for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, []):
        if row.get("block") in (BLOCK, LEGACY_BLOCK):
            return row
    return None


def _seeded(actor: Any) -> bool:
    return any(c.condition_id == DEMON_SEED_STANCE for c in actor.conditions.values())


def _cultivation_level(engine: Any, actor: Any, row: dict[str, Any]) -> int:
    """The owner's Cultivation Level, which the printed clause thresholds name.

    The compiled row carries it for a fresh bundle; a row sealed before this marker carries none, so it
    comes from the character's own sealed bundle. A creature this table tracks no level for owns the
    talent at the printed prerequisite, so the lowest printed threshold applies.
    """
    from .passive_rows import known_level

    return int(row.get("cl") or known_level(engine, actor) or 5)


def _incoming(engine: Any, source_id: str, source_actor_id: str | None, victim: Any) -> str:
    """Who and what dealt this damage, in words a player recognises ("the Ember Artisan's Fire Breath")."""
    action = engine.action_catalog.get(source_id)
    attacker = engine.state.actors.get(source_actor_id or "")
    name = getattr(action, "display_name", None)
    if attacker is not None and attacker.entity_id != victim.entity_id:
        return f"{attacker.display_name}'s {name}" if name else f"{attacker.display_name}'s attack"
    return name or "the incoming damage"


def _offer(engine: Any, victim: Any, row: dict[str, Any], dtype: str, cl: int, pb: int,
           source_id: str, source_actor_id: str | None) -> bool:
    """Ask the owner to spend one Essence; True once the printed cost has actually been paid."""
    from .spend_choice import choose_spend

    edge = "end" if cl >= 11 else "start"  # "At CL 11, the Resistance lasts until the end of your next turn."
    incoming = _incoming(engine, source_id, source_actor_id, victim)
    return bool(choose_spend(engine, {**row, "name": "Thousand-Hunger Adaptation",
                                      "resource_id": DEVOURED_ESSENCE, "ask": True},
                             victim, "THOUSAND_HUNGER_ADAPTATION", 1, 1,
                             {"actor_id": victim.entity_id, "source_id": row["feature_id"],
                              "action_name": incoming, "target_id": victim.entity_id,
                              "pool_name": "Devoured Essence", "choice_id": CHOICE,
                              "cost": "1 Devoured Essence; no Action or Reaction",
                              "payment_note": "Choosing Spend uses one stored Essence and makes you resistant to "
                                              f"{dtype} damage until the {edge} of your next turn; passing keeps your "
                                              "Essence.",
                              "labels": {"1": f"Spend 1 Devoured Essence: {victim.display_name} resists {dtype} damage"},
                              "prompt": f"Thousand-Hunger Adaptation: {incoming} dealt {dtype} damage to "
                                        f"{victim.display_name} while Demon Seed is active. Spend 1 Devoured Essence to "
                                        f"gain Resistance to {dtype} damage (further {dtype} damage against you is "
                                        f"halved) until the {edge} of your next turn, or pass and keep your Essence."}))


def _adaptation_action(owner: Any, numbers: dict[str, int]) -> Any:
    """The catalog row this plug-in delivers its own packets under.

    It gives the adaptation its own action id, so a packet it deals keeps its own attribution instead
    of being swept into whichever ability happened to roll it. Shared by the Resistance grant and the
    CL 17 bonus, so the ability has one delivery identity.
    """
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    return ActionDefinition(source_definition_id=f"action:typed.{FEATURE}.adaptation",
                            display_name="Thousand-Hunger Adaptation", owner_id=owner.entity_id,
                            economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF",
                            range_ft=None, parameters={"typed": {"numbers": numbers}})


def _grant(engine: Any, victim: Any, row: dict[str, Any], dtype: str, cl: int, pb: int) -> None:
    """The printed payment and its Resistance, then the CL 17 clause waiting for the next Daemonic roll."""
    from ..typed_executor import Context, run_effects

    numbers = {"pb": pb, "cl": cl}
    action = _adaptation_action(victim, numbers)
    # The printed expiry is the effect's own words (combat/typed_executor._turn_phrase reads them before
    # the duration name), so the CL 11 line has to be the one the sheet actually earns.
    edge = "end" if cl >= 11 else "start"  # "At CL 11, the Resistance lasts until the end of your next turn."
    run_effects(Context(engine, victim, action, None, {"numbers": numbers, "source": FEATURE}, [victim], victim), [
        {"type": "spend_resource", "applies_to": "self", "resource_id": DEVOURED_ESSENCE, "flat": 1,
         "formula": "none", "evidence": "you may spend 1 Devoured Essence"},
        {"type": "resistance", "applies_to": "self", "damage_types": [dtype], "flat": 0, "formula": "none",
         "duration": f"until_{edge}_of_your_next_turn",
         "evidence": f"Gain Resistance to that damage type until the {edge} of your next turn"},
    ])
    if cl >= 17:
        # "At CL 17, when you gain this Resistance, your next damage roll with a Daemonic talent deals
        # additional damage of that type equal to Proficiency Bonus." One clause at a time: gaining a
        # second Resistance replaces the one waiting. Integers and a type name only.
        engine._remove_condition(victim, PENDING, FEATURE)
        engine._apply_condition(victim, PENDING, FEATURE, victim.entity_id, expires_on="UNTIL_REMOVED",
                                data={"damage_type": dtype, "pb": pb})


@hook("final_damage")
def adaptation(engine: Any, target: Any, amount: int, damage_type: str, source_id: str,
               source_actor_id: str | None, intent: Any) -> dict[str, Any] | None:
    """"When you take <one of the ten types> damage while Demon Seed is active, you may spend 1 Devoured
    Essence." Asked here, before this packet's HP is committed; nothing returned leaves the damage alone."""
    if target is None or amount <= 0 or not target.active:
        return None
    row = _row(engine, target)
    if row is None:
        return None
    dtype = str(damage_type or "").lower()
    if dtype not in TYPES or not _seeded(target):
        return None  # "while Demon Seed is active", and only the ten printed damage types
    cl = _cultivation_level(engine, target, row)
    pb = int(row.get("pb") or target.proficiency_bonus or 0)
    if cl < 5 or target.resources.get(DEVOURED_ESSENCE, 0) < 1:
        return None  # "Prerequisite: CL 5+", and "you may spend 1 Devoured Essence"
    if not _offer(engine, target, row, dtype, cl, pb, source_id, source_actor_id):
        return None
    _grant(engine, target, row, dtype, cl, pb)
    return None


def _daemonic(engine: Any, source: Any) -> bool:
    """"with a Daemonic talent": the printed ability this damage is attributed to belongs to the Daemonic
    sphere. ``ability_source.mechanic_at`` (the shared helper for exactly this question) resolves a
    compiled action id -- or the action id a named rider keeps, as combat/stances.py does -- to the
    printed ability it resolves, and the authority says which sphere that ability belongs to.
    """
    from ..typed_numbers import authority_mechanics
    from .ability_source import mechanic_at

    record = mechanic_at(engine, str(source or "")) or str(source or "")
    return str((authority_mechanics().get(record) or {}).get("sphere_id") or "") == DAEMONIC


def _pending(actor: Any) -> Any:
    return next((c for c in actor.conditions.values() if c.condition_id == PENDING), None)


@hook("choice_reactors")
def adaptation_owners(engine: Any) -> tuple[str, ...]:
    """The creatures whose adaptation row can ask them a question.

    "you may spend 1 Devoured Essence" is the player's call, so a manual owner has to be enrolled
    before the spend checkpoint will pause the fight. A freshly compiled row says so itself with
    ``choice_owner`` (see compile_thousand_hunger), which the service reads directly; a bundle sealed
    before this marker carries no flag at all, so without this query its owner would pay silently on
    an AI attack too. Purely a potential-choice query -- the service still only enrolls a manual or
    Ask-me control mode, and the actual checkpoint still decides whether to ask.
    """
    rows = getattr(engine, "typed_passive_rows", {}) or {}
    return tuple(sorted(actor_id for actor_id, owned in rows.items()
                        if any(row.get("block") in (BLOCK, LEGACY_BLOCK) and not row.get("choice_owner")
                               for row in owned)))


@hook("deal_bonus")
def next_daemonic_damage(ctx: Any, subject: Any, amount: int) -> None:
    """The CL 17 clause: the next damage roll with a Daemonic talent adds the adapted type.

    ``deal_bonus`` hands the hook the creature the roll is aimed at and the Context of the ability
    that rolled it, and it runs after that roll and before the commit, for separate typed effects whatever
    the defenses or the creature's remaining Hit Points do to it afterwards. That is the moment the
    printed clause names -- "your next damage roll" -- so an immune type, a roll reduced to nothing and
    a roll that defeats the creature all spend it here and all still deliver the additional damage.
    The primary attack seam calls this same delivery helper. Nothing is spent unless the printed
    clause is waiting and that roll really is a Daemonic talent's.
    """
    actor = ctx.actor
    state = _pending(actor) if actor.active else None
    if state is None or subject is None or not subject.active:
        return
    # A Daemonic talent's own damage carries its sphere; a rider's damage keeps the action id of the
    # talent it is printed on, which mechanic_at resolves. A non-Daemonic roll of a matching type is
    # not this clause's roll, whatever type it rolls.
    if not (_daemonic(ctx.engine, ctx.source) or _daemonic(ctx.engine, (ctx.typed or {}).get("source"))):
        return
    data = state.data or {}
    dtype = str(data.get("damage_type") or "").lower()
    pb = int(data.get("pb") or 0)
    if dtype not in TYPES or pb <= 0:
        return
    engine = ctx.engine
    # Spent by this roll alone, through the engine's evented removal (conditions are keyed by
    # instance_id), so the clause pays out once even though the bonus damage is its own packet and
    # comes back through this same seam.
    engine._remove_condition(actor, PENDING, FEATURE)
    from ..typed_executor import run_effects

    # The bonus is its own packet under this ability's own catalog row and attribution, so the roll
    # that carried it cannot claim it. Everything else about the moment -- the shared damage chain,
    # the defenses -- is inherited from the roll that spent the clause.
    bonus = ctx.on_hit_context(subject, action=_adaptation_action(actor, {"pb": pb})).with_source(FEATURE)
    run_effects(bonus, [
        {"type": "extra_damage", "applies_to": "target", "flat": pb, "formula": "none",
         "damage_types": [dtype],
         "evidence": "your next damage roll with a Daemonic talent deals additional damage of that type "
                     "equal to Proficiency Bonus"}])


@hook("attack_packet_start")
def primary_daemonic_damage(engine: Any, subject: Any, amount: int, attack_context: Any) -> None:
    """Cover the sealed primary roll without duplicating the separate-effect delivery."""
    from .attack_scope import current

    frame = current(engine)
    if frame is None or attack_context.component != "primary":
        return
    if ((frame["actor_id"], frame["source"]) != (
            attack_context.attacker_id, attack_context.source_id)
            or attack_context.target_id != subject.entity_id):
        return  # another packet nested inside this attack is not its primary roll
    next_daemonic_damage(frame["context"], subject, amount)
