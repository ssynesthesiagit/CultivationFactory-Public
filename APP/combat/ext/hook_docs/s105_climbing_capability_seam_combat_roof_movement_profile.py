"""Climbing capability seam (combat/roof_movement.profile, combat/ext/athletics.py):
  climbing(engine, actor) -> None or capability dictionary. Pure strict provider,
  queried once each time a creature's climbing capabilities are read, describing the
  map-marked roof climbing an owned ability adds. Supported fields:
    climb_speed_ft: nonnegative integer feet; the largest any row offers wins, and a
      nonzero value removes the one-extra-foot-per-foot climbing surcharge, never a
      slippery/few-handholds check.
    climb_without_check: boolean; any true row waives the map's climbing Athletics
      check ("climb ordinary surfaces without a check").
    climbing_disabled: boolean; any true row denies every climb, quote and menu.
    climb_physical_disabled: boolean; any true row withdraws physical grips,
      leaving independent virtual-wall routes and holds available.
    climb_check_abilities: tuple/list of "STR" and/or "DEX"; the union across rows is
      the abilities a manual owner may choose from for the climbing Athletics check
      (Strength is always offered). Only an ability printing the choice returns it.
    climb_check_modes: tuple/list of "ADVANTAGE"/"DISADVANTAGE"; combined once for
      that check, like any other scoped mode (Sure Grip's Advantage).
    climb_check_choice_name: readable name of the owned ability that offers the
      Strength/Dexterity choice, shown in the player's question.
    climb_check_choice_source: that ability's source id, carried as feature provenance.
  A provider must return early (None) for an actor that does not own its row, so the
  seam is inert for every other character and for old saved bundles. A malformed
  return (non-dictionary row, negative/non-integer feet, an ability outside STR/DEX,
  a mode outside ADVANTAGE/DISADVANTAGE, or non-string provenance) fails strictly.
  With no provider the map's own roof rules alone apply and no choice is asked.
  Return a plain dictionary; never mutate engine, actor or condition state."""
