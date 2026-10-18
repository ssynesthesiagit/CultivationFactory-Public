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
        actor_id=attacker.entity_id, reason=f"AFTERIMAGE:{source}:{index}")
    engine._record_roll(roll)
    engine._append_event("PASSIVE_TRIGGERED", condition.source_definition_id,
        actor_id=attacker.entity_id, target_ids=(target.entity_id,), payload={
            "kind": "afterimage_targeting",
            "log": f"Afterimage: {attacker.display_name} targets "
                + (f"{target.display_name}'s image, destroying it." if roll.total == 1 else f"{target.display_name} normally."),
            "attack_source_id": source, "intent_id": intent.intent_id, "attack_index": index,
            "condition_instance_id": condition.instance_id, "image_object_id": image.object_id,
            "roll_id": roll.roll_id, "result": roll.total})
    if roll.total != 1:
        return None
    receipt = {"source_id": condition.source_definition_id,
        "recipient_object_id": image.object_id, "condition_instance_id": condition.instance_id}
    if not destroy_image(engine, image.object_id, source, attacker.entity_id, intent.intent_id):
        from . import CheckpointError
        raise CheckpointError("the intercepted image no longer has a live condition")
    return receipt
