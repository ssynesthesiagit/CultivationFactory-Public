"""A2DEATHSEC general summon compilation seam:
compile_summon(bundle, info) -> replacement bundle or None, strict and pure,
composed sequentially on an independent individual bundle copy before sealing.
info supplies owned_ids, creature_key (referenced chassis or group fallback for
inline creatures), group, source, plan, numbers, pb and cl.
A returned dictionary must keep actor_id. Providers may complete typed actions,
reactions, template statistics and integer/string policies in summon metadata.
No consumer preserves compilation; runtime consumes only the sealed bundle.
Death uses this for Guard stance/attack provenance/zero-damage voluntary step,
chosen formation size and Corpse Engine. Ritual remains are selected before
combat through summon_plan.death_sizes keyed by group or individual actor_id;
Grave Formations allow large (default) or huge. Generic bound footprints now
map large/huge/gargantuan to 2/3/4 cells; template size and skills are carried
into ActorState for every summon. Old absent fields retain their defaults.
Corpse Engine uses turn_boundary_start and ordinary healing restrictions, capped
at half maximum HP. Dismissal is a player-owned, no-Action choice on their turn."""
