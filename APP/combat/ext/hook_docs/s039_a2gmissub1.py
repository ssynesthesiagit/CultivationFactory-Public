"""General no-turn map assets (A2GMISSUB1):
  spirit_assets.assets/manifest/move/origins create, list, move and expose
  RuntimeObjectState bodies using ordinary OBJECT_UPDATED reducer events.
  The owning ability seals the profile. Component spirit_asset records the
  shared HP group and accepted area intent; no independent creature or turn.
  object_damage_admission(engine, attacker, obj, packets, source, *, area_scope_resolved=False) -> bool|None:
  False declines the entire object damage instance before defense/exposure or
  state mutation; None/True preserve ordinary resolution. Unrelated objects
  have no policy. area_scope_resolved is transient context supplied by deal:
  True means every packet already passed the shared per-payload recipient policy,
  including authoritative overrides. Do not reapply a scope-less area default;
  other admission guards still apply. Default False preserves ordinary delivery.
  A pooled asset admits area damage once per initiating intent.
  Accepted OBJECT_UPDATED damage synchronizes each body's shared HP eventfully.
  transfer_effect choose_instance=True uses the existing choice transport to
  select a represented effect before immunity/transfer, preserving source/DC.
"""
