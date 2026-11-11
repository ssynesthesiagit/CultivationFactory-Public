"""Whole-instance damage opt-in:
  damage_instance_requested(engine, ctx, effects) -> bool | None is a pure
  query run once before an activation's effect batch. True asks the executor to
  collect every plain damage row of this batch (its type and amount) before the
  first Hit Point commit, so a reaction can answer a later portion of the same
  simultaneous instance; None (or no subscriber) leaves resolution in its
  original per-row roll/commit order. The collection rolls those rows once
  through the activation's own damage cache, so no portion draws extra dice.
  Consumers must gate on actual ownership/eligibility: the hook is inert for
  every character that does not own the asking ability, and an activation with
  no eligible recipient keeps the original order."""
