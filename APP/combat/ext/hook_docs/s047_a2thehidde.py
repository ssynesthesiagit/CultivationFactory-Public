"""Hidden Eye second pass (A2THEHIDDE):
  stealth_search_before_roll(engine, searcher, hidden_target, source) is a strict
  checkpoint returning None, ADVANTAGE or DISADVANTAGE. It runs only immediately
  before an actual Search check, never in previews or sense-only discovery.
  Providers may ask the target's own controller and pay an optional reaction;
  pauses/errors unwind the service transaction. Ordinary Search calls it per
  target. Single-check Sweep calls it for every rolled target before drawing its
  shared dice, then combines each target's contributions independently. This
  does not make a creature visible or reveal its space to the searcher. A
  provider that asks a question at this checkpoint identifies the action that is
  actually resolving, through choice_prompt.action_context(engine, searcher,
  source, hidden_target): the service reads that explicit metadata and never
  recovers the outer turn, so a Search and a single-check Sweep each name
  themselves and the hidden creature they land on.

  Typed attack_mode(ctx, target) providers may return a legacy mode string or
  {mode: ADVANTAGE|DISADVANTAGE, cause: a supported selective-removal cause}.
  combat.attack_modes.typed_contribution validates explicit attribution and
  records it in the existing transient strike provenance. New supported token
  DISADVANTAGE:weather removes only attributed weather contributions, before
  Advantage/Disadvantage cancellation. Unrelated penalties and untagged legacy
  modes keep their ordinary meaning. Weather Shroud attributes its ranged
  weapon penalty and retains its normal one-shot consumption and expiry.
  Wind Reader opts focused owners into that token; Lurker opts reviewed owners
  into the Search checkpoint. No core resolver recognizes either ability ID.
"""
