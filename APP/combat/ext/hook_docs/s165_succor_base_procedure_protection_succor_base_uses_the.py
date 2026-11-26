"""Succor base procedure: protection_succor_base uses the existing compile_bundle
transform only for owners of PROTECTION_BASE_SUCCOR and generic reactions that
explicitly sacrifice a Persistent Aegis on an ally. It inherits the 300-foot
recipient limit and orders sacrifice before the talent effect; no new hooks,
talent effects, triggers, or saved-state fields are introduced. Luck retains its
existing d20_rewrite provider and pre-effect on_use sacrifice."""
