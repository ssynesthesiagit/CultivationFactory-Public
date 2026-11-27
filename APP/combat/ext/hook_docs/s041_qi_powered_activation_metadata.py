"""Qi-powered activation metadata:
  typed.qi_powered is an optional explicit boolean activation fact. Balanced
  Flow reads it before source/cost inference; False excludes prepared-item
  consumption even when the item's printed source belongs to a Qi Subpath.
  Owned Balanced Flow on a Qi-powered sheet marks zero-cost Sphere expressions
  True. Omission retains the source/cost inference; no core ability cases exist."""
