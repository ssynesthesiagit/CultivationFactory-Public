"""Effect types added by AUTO75 (absent = unchanged behaviour; combat/ext/ash_talents.py):
  periodic_damage_state effect: a printed "takes <dice> <damage types> damage at the start of each of its turns"
      state that outlives the activation that made it. The row carries ``name``, ``label``, ``applies_to``, an
      ordinary ``duration`` (the engine's expiry names), an optional ``requires_condition`` (the printed state the
      damage hangs on, e.g. "Restrained by accumulated ash", matched on the holder's own conditions by the same
      source and caster) and ``damage``: a list of the printed damage rows
      ({"dice": {"count", "sides", "bonus"}, "flat", "damage_types"}). It is stored as one typed condition
      (condition:typed.periodic_damage_state.<name>) whose data holds only those printed numbers, names and the
      anchor's name, so it survives a table commit and reload; the turn_start hook delivers each row through the
      ordinary typed path (a Context on the ability that put the state on, as rider_damage_states does for its own
      turn-start riders), so the holder's damage reactions and Ash Ward answer it, the best of a listed choice of
      damage types is chosen by typed_executor.choose_damage_type, the damage_dealt subscribers are notified, and
      a creature that dies to it dies the ordinary way. It ends with its own expiry or with the group that
      recorded it (a repeat saving throw, Concentration). No row, no anchor, or no compiled action = no damage.
  move_typed_area effect: a printed "As a Bonus Action, move one of your <areas> up to N feet". The row names
      the base ability whose areas move (``area_source``, compared against each compiled action's typed source,
      so every modifier variant of it is included), the reach (``distance_ft``), a ``choice`` id and a ``label``.
      The owner is asked which of its own active areas to move (only when it has more than one, and each area is
      labelled with where it is, because two areas of one kind share a printed name) and then which square it
      lands on: every legal centre within the printed reach, labelled with the distance the area will travel,
      chosen by clicking a highlighted square on the map and answered automatically for an AI. Both questions may
      be declined; declining either one leaves every area where it was and logs a plain line saying so (an AI still
      answers both automatically, and a fight nobody is answering still takes the preferred square). The area
      keeps its identity, cells, duration and printed rules and is published again, so a saved fight replays it
      as the same area. No such area, or nowhere within reach, = a GM line saying so. Shared API:
      ash_talents.area_destinations / in_ash_or_fire; the two choice ids are namespaced
      (choice:needle.move_area_to:<choice>, and <choice>.which_area: for the "which area" question)."""
