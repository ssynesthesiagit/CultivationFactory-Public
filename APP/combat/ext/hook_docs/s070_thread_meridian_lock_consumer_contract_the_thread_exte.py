"""Thread Meridian Lock consumer contract: the Thread extension subscribes to
paid_relocation_guard only while the moving actor has its source-stamped lock
condition and returns the exact CP pool IDs. movement_semantics reads sealed
self_movement=true rows (and excludes movement_role=rider) for the ordinary
candidate filter; custom effect plug-ins must mark voluntary self movement in
their reviewed typed row or compile hook. The assignment observer remains the
transactional backstop for hidden movement effects and late payments. Core does
not recognize Thread, CP aliases, Storm Step, or other ability names.
Extension effect rows may seal technique_categories=['movement'] or ['escape']
for permissions and custom techniques that do not directly change a position.
movement_semantics.technique_categories(row) adds the ordinary built-in travel,
forced movement and physical escape categories without reading ability prose.
Absent metadata leaves unrelated effects unclassified; the Thread consumer
uses these categories only to prohibit purchasing such techniques with CP."""
