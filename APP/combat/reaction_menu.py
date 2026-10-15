"""Discover reactions by declining on a disposable preview.

Normal engine checks own legality. No discovery payment/effect is committed.
Used by manual-action and local-AI previews in gate5_service.
"""
from .gate2_runtime_models import ReactionDecision


class MenuBoundary(BaseException):
    """End discovery at a different event or a mandatory choice."""


class ReactionMenuProbe:
    def __init__(self, first):
        self.first = first
        self.contexts = []

    def answer(self, context):
        first = self.first
        if (context.checkpoint != first.checkpoint or context.reactor_id != first.reactor_id
                or (context.extension_choice and not context.extension_choice.allow_decline)):
            raise MenuBoundary()
        key = (context.checkpoint, context.reactor_id, context.reaction_source_id)
        if not any((c.checkpoint, c.reactor_id, c.reaction_source_id) == key for c in self.contexts):
            self.contexts.append(context)
        return ReactionDecision(checkpoint=context.checkpoint, reactor_id=context.reactor_id,
                                reaction_source_id=context.reaction_source_id, selection="DECLINE")
