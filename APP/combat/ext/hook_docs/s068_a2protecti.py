"""General area arrival checkpoint (A2PROTECTI):
  zone_arrival(engine, mover, start, end, forced) -> None runs strictly in
  zones.on_moved after arrival membership is captured and before entry payloads.
  It covers landed steps, typed forced paths and teleport arrivals. triggers=False
  is inert. Providers may resolve an owned entry effect or raise ControllerPause;
  the existing action transaction owns rollback, answers and replay. They must
  return None, must check actual volume membership at both supplied positions,
  and must not move the subject or change unrelated areas. With no providers,
  the checkpoint does nothing.
  Protection's new protection_sanctuary row binds one owned Ward and stores an
  integer relief policy on its native state condition. Only those stamped rows
  use strict turn_boundary_start (before observational ongoing payloads) and
  zone_arrival; old Sanctuary rows retain their original interpreter.
  Transport-less engines retain that legacy state route. Relief choices use
  exact condition instance ids and allies only. They guard the native minute
  deadline before pre-expiry choices, permit one benefit per activation, and
  offer relief only on the first entry per table turn. Unknown extra ongoing
  and unattributed named sources stay manual; current authority does not
  replace saved rows.
  protection.own_wards(engine, owner) is the public pure query for live owned
  Protection Wards used by Sanctuary activation and relief.
Trap second pass (A2TRAP): trap_aerial decorates only newly reviewed
  trap_capability rows at compilation. Set Trap seals the capability on its
  own action and placement; markerless saved actions retain ground behavior.
  Optional rigging needs ground or an explicit solid surface anchor,
  including a wall/ceiling face for suspended devices. Native
  landed zone entry resolves threats within the CL height cap; the footprint
  stops below solid obstacles. Falling-Sky darts use physical 3D effect rays
  and the actual hit (including immune damage) for their STR save. Native
  Fly Speed, Hover, falling and holder-next-start expiry remain authoritative.
  Net/Noose pull along a validated native forced path before restraint. A
  sprung Heaven-Net seals an exact-hold lattice and state_event ends only that
  lattice on release; terrain fields retain ordinary one-minute expiry.
  Terrain lattices include legal upper spaces above solid columns; nonflyers
  pay ordinary terrain cost only at the base plane, flyers throughout.
  The existing difficult_zone_exempt hook limits the lattice to creatures
  with a Fly Speed, including a temporarily zeroed Fly Speed. Rigging is one
  Trigger Talent and a second requires the active two-Trigger inheritance;
  separate Layered Mechanism compatibility remains a rider. Heaven-Net rigs its Net/Terrain forms automatically.
  Set Trap: choose a space and its raised-surface companion use ordinary owner choices,
  payment and supported visible 3D destinations rather than changing native
  CELL menus. Empty Road asks which compatible Trigger talents each placement
  carries, at most two total, including Aerial, Remote and Trap Within the Trap,
  with no extra Focus payment. Rigging uses one of those slots. Newly sealed
  Road relocation preserves altitude and validates its route and destination
  anchors, then rebuilds the rigged height below obstacles. Warning choices
  follow owner choice authority. Actual automatic actors admit allies/self only.
  Player-controlled MANUAL, SUGGESTED and MANUAL_AI_BRIDGE owners may warn enemies;
  their warning decisions disable automatic answers. Automatic aiming reads perceived foes."""
