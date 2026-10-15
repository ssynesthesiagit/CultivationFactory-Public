"""Qi Devourer: an owned, optional fresh-zero-HP essence recovery.

Uses existing compile_block, choice_options, choice_reactors and fresh_zero_hp
contracts. Positive committed damage in this scene establishes eligibility;
the final hit need not be the owner's. No Reaction/action or moral tag is added.
Receipts are per owner/victim, survive revival and reload, and clear only through
essence_state's explicit fully rebuilt source effect. A round integer survives
turn changes. AI chooses its own legal recovery without reading hidden tactics.
"""
from . import hook, note
from .needle import ask, checkpoint_id, option_spec
from .passive_rows import row_of, known_level
from .essence_state import DEPLETED, profile

FEATURE = "insight.qi-devourer"
BLOCK = "qi_devourer"
CHOICE = "choice:insights7e.qi_devourer"
USED = "_round_ins7e_qi_devourer"
QI = "resource:core.qi"


@hook("compile_block")
def compile_rows(block, spec, row, numbers):
    if block != BLOCK:
        return None
    return [{**row, "kind": BLOCK, "pb": int(numbers["pb"]), "choice_owner": 1,
        "player_outcome": "Once per round, consume escaping essence from a creature within 60 feet reduced to 0 Hit Points after you damaged it this scene; regain Qi up to your Proficiency Bonus, limited by its cultivation level. Each creature yields once until its essence is fully rebuilt."}]


@hook("choice_options")
def choices(engine, intent, checkpoint, reactor_id, choice_id, context):
    return option_spec(choice_id, context, CHOICE)


@hook("choice_reactors")
def reactors(engine):
    return tuple(a.entity_id for a in engine.state.actors.values()
                 if row_of(engine, a.entity_id, BLOCK, BLOCK))


def damaged_this_scene(engine, owner, target):
    return any(e.event_type == "DAMAGE_COMMITTED" and e.actor_id == owner.entity_id
               and target.entity_id in e.target_ids and int(e.payload.get("reduced_to", 0)) > 0
               for e in engine.events)


@hook("fresh_zero_hp")
def escaping_essence(engine, target, attacker_id, source_id):
    if not profile(target)["genuine"]:
        return
    for owner in sorted(engine.state.actors.values(), key=lambda a: a.entity_id):
        row = row_of(engine, owner.entity_id, BLOCK, BLOCK)
        receipt = DEPLETED + owner.entity_id
        if (not row or owner.entity_id == target.entity_id or not owner.active or owner.current_hp <= 0
                or owner.turn_flags.get(USED) == engine.state.round_number
                or engine._distance_actor_to_actor(owner, target) > 60
                or any(c.condition_id == receipt for c in target.conditions.values())
                or not damaged_this_scene(engine, owner, target)):
            continue
        action = engine.action_catalog.get(source_id)
        trigger = action.display_name if action else "the damaging effect"
        picked = ask(engine, getattr(engine, "_active_intent", None),
            checkpoint_id(engine, "QI_DEVOURER", owner.entity_id, target.entity_id), owner, CHOICE,
            ["consume"], labels={"consume": "Consume escaping essence and regain Qi"},
            preferred=["consume"], allow_decline=True, name="Qi Devourer", feature_id=FEATURE,
            target_id=target.entity_id,
            prompt=f"Qi Devourer: {trigger} reduced {target.display_name} to 0 Hit Points within 60 feet after you damaged it this scene. Consume its escaping essence to regain Qi up to your Proficiency Bonus (limited by its cultivation level, minimum 1)? No action or Reaction; once per round, and this creature cannot yield to you again until its essence is fully rebuilt.")
        if not picked:
            continue
        owner.turn_flags[USED] = int(engine.state.round_number)
        engine._apply_condition(target, receipt, FEATURE, owner.entity_id, expires_on="UNTIL_REMOVED",
            data={"label": "Essence consumed: cannot yield again to this cultivator until fully restored"})
        amount = min(int(row["pb"]), max(1, known_level(engine, target) or 1))
        engine._gain_resource(owner, QI, amount, FEATURE)
        note(engine, FEATURE, owner, f"Qi Devourer: {owner.display_name} consumes escaping essence from {target.display_name} and regains up to {amount} Qi, limited by its maximum.", targets=(target,), qi_offered=amount)
