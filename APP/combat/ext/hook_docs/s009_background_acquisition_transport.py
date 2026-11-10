"""Background acquisition transport:
  compile_acquisition_ids(owner_sheet) -> list/tuple of canonical record IDs or
  None. Strict pure query before compile_blocks; each provider validates its
  own selected acquisition and source. Absent providers add no ownership. IDs do
  not themselves certify an automated mechanic. Canonical ownership has ordered-set
  semantics after alias/split expansion: one record is delivered once to compile
  hooks even when both sheet projections and earned occurrences name it. The
  original owner_sheet retains all occurrences for source-specific scaling.
  compile_passives info also
  includes owner_sheet for source-owning acquisition adapters; existing callers
  and default-inert providers retain their previous behavior.
  background_origins seals exact Background-scoped/public Origin selections
  against native Background options and the bundled stripped-section hash.
  Its ability_check_hazards provider reads actual authored check hazards:
  hunger/thirst/exposure/forced_march/sleep_deprivation/ordinary_deprivation;
  Street-Hardened requires place:<printed place> plus ordinary_ambush,
  pickpocket, tailing, lookout_signal or sudden_street_violence, and WIS Perception;
  prison detection requires notice plus weak_restraints/careless_guards/
  unsecured_doors/loose_bindings/bad_prison_habits; Quick Hands requires both
  hide_on_body and hand_sized_object. Hunger saves use matching save_categories.
  Missing facts/ownership are inert; independent Disadvantage cancels normally.
  These contracts do not infer facts or implement narrative information,
  surprise, initiative, object interactions or long-rest rerolls."""
