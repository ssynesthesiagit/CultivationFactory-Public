"""Surface-dependent benefits (surface_contact.py):
  contact(engine, actor, materials, stable=True, standing=True) -> bool is a pure shared support query.
  surface_contact(engine, actor) -> None or {material: str, stable: bool,
  touching: bool}; strict, pure and default-inert. Ordinary floor/solid columns
  are stable ground. Active rule.surface_contact carries the same shape for
  explicit non-ground/unstable footing; incorporeal/no_physical_contact rules
  veto contact. Mismatching material or false touching vetoes contact; false
  stable vetoes it when stable=True. standing=False allows explicit authored
  contact without map support; absent metadata still requires map support.
  Mountain Core Earth Resilience uses this helper at AC, saves, forced movement,
  effective Shove size and post-relocation falling damage. No persisted field
  or change to a creature without the retained owned marker is introduced.
  Optional surface_contact fields: solid: bool explicitly classifies unusual
  material, surface_id: nonempty str names a continuous connected component.
  contact(..., materials=None, solid=True) accepts any solid material; known
  solids are earth, stone, metal, wood, ice, glass, crystal and bone. Unknown
  material needs solid=True; explicit False vetoes solid eligibility.
  solid_contact(engine, actor) allows bodily touching without stable standing.
  connected_contact(engine, first, second) requires solid contact by both and
  matching authored surface_id components, or native floor/finite-column/roof
  connectivity when neither is tagged. Roof paths follow solid cells of one
  native surface at the feet's walking height; separate roofs and open
  apertures never bridge a gap. Unsupported untagged contact cannot
  prove connection. Probes may obtain metadata from the same pure hook.
  Avatar qualifies only its live state's grant; Heaven-Drum qualifies only
  its owned grant and connected sensed source. Mountain Core defaults persist.

"""
