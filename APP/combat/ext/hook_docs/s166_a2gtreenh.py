"""General final compilation seam (A2GTREENH): compile_bundle(bundle, info) ->
replacement bundle or None. Pure sequential transform before canonical sealing.
info supplies normalized owner_sheet, effective kit/owner_items after attunement
and leave-behind, numbers, actor_id, primary, and the selected typed mechanics
(info["mechanics"]), plus owned_ids (acquired ids) and mods (ability modifiers), which are context only.
Providers publish primitive
passives, actions, resources and sheet facts; they never mutate input documents.
No provider preserves prior bytes. Treasure armor benefits bind to the actual
worn inventory key and shield possession, never to talent names. Limited uses
are journaled conditions; no rest occurs in a running fight.
Heart-Ash uses this seam to replace the source-verified initial Foundation HP
contribution with twice PB at the owned Refined tier. It adds only the difference
to the admitted maximum, once before sealing; legacy sheets with no source-bound
initial mechanics retain their supplied HP. No input sheet is changed."""
