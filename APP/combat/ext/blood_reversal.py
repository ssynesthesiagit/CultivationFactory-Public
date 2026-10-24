"""Blood Reversal's optional paid recovery after actual Blood talent damage.

Ownership and numbers are sealed in the passive row. Unstamped saves are inert.
Only the completed positive damage checkpoint opens a choice, never a preview.
"""
from typing import Any

from . import hook
from .passive_rows import row_of

FEATURE = "insight.legacy-blood-reversal"
BLOCK = "blood_reversal"
USED = "blood_reversal_turn"
CHOICE = "choice:needle.blood_reversal"


@hook("compile_block")
def compile_reversal(block, spec, row, numbers):
    if block != BLOCK:
        return None
    return [{**row, "kind": FEATURE, "pb": int(numbers["pb"]),
             "key_mod": int(numbers["key_mod"]), "choice_owner": True,
             "player_outcome": "Once per turn after you deal damage with a Blood talent, you may spend 2 cultivation points to heal one creature within 30 feet by your Proficiency Bonus + key ability modifier"}]


@hook("damage_dealt")
def reverse_damage(ctx: Any, target: Any, amount: int) -> None:
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    from ..recipients import allowed
    from ..relations import ALLY, relation
    from ..typed_executor import Context, block_healing
    from .blood_riders import CP_POOLS
    from .choice_costs import payable
    from .choice_prompt import action_context
    from .needle import answerable, ask, checkpoint_id

    engine, actor = ctx.engine, ctx.actor
    owned = row_of(engine, actor.entity_id, BLOCK, FEATURE)
    turn = int(engine.state.round_number) * 1000 + int(engine.state.current_slot_index)
    if (amount <= 0 or not actor.active or not owned
            or ctx.typed.get("sphere") != "tianxia.sphere.blood"
            or actor.turn_flags.get(USED) == turn):
        return
    pool = next((pool for pool in CP_POOLS if actor.resources.get(pool, 0) >= 2), None)
    if pool is None:
        return
    action = ActionDefinition(source_definition_id=FEATURE, owner_id=actor.entity_id,
                              display_name="Blood Reversal", economy=EconomyKind.NONE,
                              resolution_kind="TYPED", target_kind="ANY_CREATURE", range_ft=30)
    manual = answerable(engine, actor)
    candidates = [other for other in engine.state.actors.values()
                  if allowed(engine, actor, other, action)
                  and (manual or relation(engine, actor, other) == ALLY)]
    if not candidates:
        return
    # AI options themselves contain only perceived allies/self, never enemies
    # hidden behind a mere preference. A human retains the printed any-creature choice.
    candidates.sort(key=lambda other: (other.maximum_hp - other.current_hp, other.entity_id), reverse=True)
    ids = [other.entity_id for other in candidates]
    healing = max(0, int(owned["pb"]) + int(owned["key_mod"]))
    automatic = not manual and any(other.current_hp < other.maximum_hp for other in candidates)
    price = payable(actor, pool, 2)
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "BLOOD_REVERSAL", ctx.source, target.entity_id),
                 actor, CHOICE, ids,
                 labels={other.entity_id: f"Spend 2 cultivation points: {other.display_name} regains {healing} Hit Points" for other in candidates},
                 name="Blood Reversal", feature_id=FEATURE, allow_decline=True,
                 automatic=automatic,
                 default="first" if automatic else "decline",
                 prompt=f"Blood Reversal: {ctx.action.display_name} dealt damage to {target.display_name}. Choose one creature within 30 feet to heal (once per turn).",
                 prompt_context={**action_context(engine, actor, ctx.source, target), "affected_id": ""}, payment=price)
    if not picked or picked[0] not in ids:
        return
    recipient = engine.state.actors[picked[0]]
    actor.turn_flags[USED] = turn
    price.pay(engine, actor, FEATURE)
    # Native healing retains prevention, reduction, caps, receipts and downstream hooks.
    block_healing(Context(engine, actor, ctx.action, ctx.intent, ctx.typed, [recipient], recipient, {}),
                  {"type": "healing", "applies_to": "target", "flat": healing,
                   "evidence": "The creature regains Hit Points equal to Proficiency Bonus + key ability modifier."})
