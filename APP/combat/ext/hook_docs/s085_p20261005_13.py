"""Reviewed passive trait adapter (P20261005-13):
  compile_passives(passives, info) -> new passive-row list; strict pure transform
  immediately after compile_blocks. info supplies source/hash-gated owned_ids,
  numbers and the selected typed mechanics (info["mechanics"]) so a plug-in
  reads its reviewed data from the authority the compiler was given rather than
  rereading the file on disk; it also supplies owner_sheet for consumers of
  sealed acquisition choices.
  character_creation.acquisition_choices.from_sheet reads only the builder's
  valid typed_choice_snapshot; a choice never grants ownership by itself.
  Native source-effective compilation evaluates this pure
  transform once per distinct numeric context (all owned_ids remain available),
  retaining each feature_id only from its own context. Providers must identify
  source-owned rows with feature_id; source-less rows retain default numbers.
  No overrides means one unchanged transform. compile_blocks likewise accepts
  optional numbers_by_source for CL/PB/key modifier, including compile_block hooks. An owned feature_blocks spec may add passive_traits alongside
  any ordinary block, including defense; block="passive_traits" is a traits-only
  marker and does not suppress the source's other effects. The adapter emits
  block="passive_trait" rows with the same feature_id and copied typed config.
  Configs have exact fields (one row per kind per source):
    {kind: forced_movement_reduction, distance_ft: nonnegative integer}
    {kind: standing_cost, cost_ft: nonnegative integer}
    {kind: effective_size, steps: positive integer, roles: [act|resist],
     purposes: [forced|shove|grapple|prone|comparison|brutal_shove|overrun]}
    {kind: grapple_escape_mode, mode: ADVANTAGE|DISADVANTAGE,
     checks: boolean, saves: boolean}, with at least one roll kind enabled.
  Unknown/missing fields, malformed types, repeated kinds and unsupported
  values raise at compile time. These are unconditional traits; unexpressed
  requirements, replacements, costs or additional effects must remain separate.
  passive_traits.py registers forced_distance only (never the second typed
  forced_movement_reduction checkpoint), so its cut applies once per existing
  on_forced_movement call. stand_cost is a pure quote; posture owns all standing
  gates and payment. size_steps requires both role and purpose to match and
  changes neither footprint nor reach. Escape check/save hooks require a
  supplied live Grappled hold on the roller and the actual source actor's
  compiled trait; another grappler, a helped ally's hold, and mere restraint
  do not qualify. Independent Advantage/Disadvantage replies combine normally.
  Runtime reads existing typed_passive_rows only, so retained bundles preserve
  their traits on reload without reading current source data. No new saved
  state, event, action or lock field is introduced; absent traits are inert."""
