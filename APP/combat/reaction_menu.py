"""Discover reactions by declining on a disposable preview.

Normal engine checks own legality. No discovery payment/effect is committed.
Used by manual-action and AI previews in gate5_service. Hit and damage
checkpoints for one attack share a menu; different rolls, packets, reactors and
mandatory choices are boundaries. A payment choice is also a boundary: declining
it cancels the technique instead of continuing to another response. This changes
discovery only, never execution.
"""
from .gate2_runtime_models import ReactionDecision


class MenuBoundary(BaseException):
    """End discovery at a different event, mandatory choice or payment prompt."""


def attack_identity(engine):
    """Read the active roll's public provenance for typed and native attacks.

    A source or attacker alone is insufficient: Extra Attack and nested attacks
    need separate cards even when they use the same weapon against one target.
    """
    from .ext.attack_scope import current
    frame = current(engine)
    if frame is not None and frame["roll_id"]:
        return frame["actor_id"], frame["target_id"], frame["source"], frame["roll_id"]
    frame = engine.d20_context()
    if frame is None or frame.get("kind") != "attack":
        return None
    for event in reversed(engine.events):
        if (event.event_type == "ATTACK_ROLLED" and event.actor_id == frame["actor_id"]
                and event.source_definition_id == frame["source_id"]
                and frame["target_id"] in event.target_ids):
            return event.actor_id, frame["target_id"], event.source_definition_id, event.payload["roll_id"]
    return None


class ReactionMenuProbe:
    def __init__(self, first):
        self.first = first
        self.contexts = []
        self.attack = None
        self.packet = None
        self.started = False

    def answer(self, context, engine=None):
        first = self.first
        checkpoint = context.checkpoint.split("@", 1)[0].removeprefix("TYPED:")
        defenses = {"ATTACK_HIT_BEFORE_DAMAGE", "DAMAGE_APPLICATION"}
        attack, packet, packet_scope = None, None, None
        if engine is not None and checkpoint in defenses:
            from .pending_damage import current as pending, packet_scratch
            attack = attack_identity(engine)
            # At a nested hit these still belong to the enclosing damage
            # resolution. Bind only when this attack enters damage application.
            if checkpoint == "DAMAGE_APPLICATION":
                packet = pending(engine)
                packet_scope = packet_scratch(engine)
        if not self.started:
            self.attack, self.packet, self.started = attack, packet_scope, True
        same_attack = (self.attack is not None and attack == self.attack
                       and checkpoint in defenses)
        same_packet = (self.packet is not None and packet_scope is self.packet
                       and checkpoint == "DAMAGE_APPLICATION" and (self.attack is None or attack == self.attack))
        # A hit can lead into its first damage packet, but never into a second
        # component or a nested packet, even if the enclosing roll is unchanged.
        if same_attack and packet is not None:
            if (packet.source_actor_id, packet.target_id, packet.source_id) != (
                    attack[0], attack[1], attack[2]):
                raise MenuBoundary()
            if self.packet is None:
                self.packet = packet_scope
            elif packet_scope is not self.packet:
                raise MenuBoundary()
        if (not (same_attack or same_packet) and context.checkpoint != first.checkpoint
                or context.reactor_id != first.reactor_id
                or (context.extension_choice and not context.extension_choice.allow_decline)):
            raise MenuBoundary()
        key = (context.checkpoint, context.reactor_id, context.reaction_source_id)
        if not any((c.checkpoint, c.reactor_id, c.reaction_source_id) == key for c in self.contexts):
            # Some amount-choice transports name the damage in prose but omit
            # the numeric field. Snapshot the known child packet for pure menu
            # hints; this is preview metadata, never an execution decision.
            if (packet is not None and getattr(context, "pending_damage", None) is None
                    and type(getattr(packet, "amount", None)) is int):
                context = context.model_copy(update={"pending_damage": packet.amount})
            # Keep the current packet's type with its amount for conditional
            # presentation estimates, never an enclosing or historical packet.
            if packet is not None and isinstance(getattr(packet, "damage_type", None), str):
                context = context.model_copy(update={"choice_trigger": {
                    **(context.choice_trigger or {}), "damage_type": packet.damage_type}})
            self.contexts.append(context)
        # Alternative payments already carry every legal quote in one choice.
        # Its decline cancels the action, so simulating that decline would leak
        # GATE2_PAYMENT_DECLINED out of discovery and hide the real player prompt.
        # Keep the full context above, then stop before making any fake decision.
        if checkpoint.startswith("PAYMENT_SHORTFALL:") and context.extension_choice:
            raise MenuBoundary()
        return ReactionDecision(checkpoint=context.checkpoint, reactor_id=context.reactor_id,
                                reaction_source_id=context.reaction_source_id, selection="DECLINE")
