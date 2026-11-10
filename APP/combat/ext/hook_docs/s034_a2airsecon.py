"""General support and pre-descent seams (A2AIRSECON):
  support_surface(engine, actor, position) -> True | None is a pure strict query
  after native empty-volume validation. True grants support to that full footprint
  at that position; None is inert. It never grants flight, suppresses collision,
  or removes native ground support. Native walking, falls and landing share it.
  falling_prepare(engine, falling_actors, cause, intent) -> None runs before
  fall reactions and distance plans. A provider may record a chosen delay;
  native falling rechecks eligibility before publishing plans or offering
  protection. It never resolves damage. No provider changes no prior result.
  falling_ready(engine, falling_actors, cause, intent) -> None runs after all
  falling reactions, before descent. A provider owns its consent and recorded
  relocation; it may use normal granted movement to adjust a protected descent.
  Pauses unwind the enclosing transaction. The native fall rechecks support and
  eligibility afterward. No providers preserves previous ordering and results.
  Air consumers use sealed feature/zone opt-ins: Wind-Line Archer records a
  Current direction and scoped range-only removal, Cloud-Step Novice uses native
  suspension expiry and horizontal movement, Sky Road offers horizontal support.

"""
