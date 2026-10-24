"""Printed Afterimage attack d2; map/nonattack use the shared public helper.

No image is constructed here. Native, typed and portable attack boundaries
share one causal declaration receipt; nonattack effects never call this hook.
"""
from combat.gate2_runtime_models import DiceSpec
from . import hook
from .afterimage_targeting import perceived_image, destroy_image


@hook("attack_target_interception")
def intercept_attack(engine, attacker, target, source, intent, index):
    image = perceived_image(engine, attacker, target)
    if image is None:
        return None
    condition = target.conditions[image.component["condition_instance_id"]]
    roll = engine.roller.roll(DiceSpec(count=1, sides=2, modifier=0),
        actor_id=attacker.entity_id, reason=f"TARGET_INTERCEPT:{source}:{index}")
    engine._record_roll(roll)
    label = condition.data.get("label") or "Afterimage"
    action = engine.action_catalog.get(source)
    ability = (getattr(action, "display_name", None) or (action.get("display_name") if isinstance(action, dict) else None)
        or "attack")
    attacker_name = attacker.display_name
    intent_id = str(getattr(intent, "intent_id", "") or "")
    if roll.total == 1:
        # The receipt below carries this sentence onto the one attack_target_intercepted row. The decision
        # row itself is hidden, so the attack is narrated exactly once.
        text = (f"{label}: rolled 1 on a d2 \u2014 {attacker_name}'s {ability} hit "
                f"{target.display_name}'s afterimage instead (the image is gone).")
    else:
        text = f"{label}: rolled {roll.total} \u2014 {attacker_name} targets {target.display_name} normally."
    engine._append_event("PASSIVE_TRIGGERED", condition.source_definition_id,
        actor_id=attacker.entity_id, target_ids=(target.entity_id,), payload={
            "kind": "afterimage_targeting", "text": text, "history_hidden": roll.total == 1,
            "attack_source_id": source, "intent_id": intent_id, "attack_index": index,
            "condition_instance_id": condition.instance_id, "image_object_id": image.object_id,
            "roll_id": roll.roll_id, "result": roll.total})
    if roll.total != 1:
        return None
    # The roll ID rides on the retained receipt row, so the table animates this die where the hidden decision was.
    receipt = {"source_id": condition.source_definition_id, "text": text, "roll_id": roll.roll_id,
        "recipient_object_id": image.object_id, "condition_instance_id": condition.instance_id}
    if not destroy_image(engine, image.object_id, source, attacker.entity_id, intent_id):
        from . import CheckpointError
        raise CheckpointError("the intercepted image no longer has a live condition")
    return receipt
