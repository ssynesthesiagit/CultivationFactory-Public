"""objects.attack_object_roll(ctx, obj, index=0) -> (hit, natural): public shared
recorded Cultivation/weapon attack vs object AC. Context owns source/bonus.
Uses the existing object roll procedure; attack-object users share it.
Death Rotting Grasp opts into parameters.replaces_attack=1, object_targets
and object_action; its player chooses ordinary/maximum damage on explicitly
decaying unattended nonmagical material. Unknown material grants no maximum.
Death servant Small/Medium size selection uses the same death_sizes plan.
Their sealed chassis supplies Undead typing and all three printed Grave Strike
types; Corpse Servant Grave Body uses source-aware save_mode named conditions.
match_start and summon_appeared install Corpse Servant/Grave Formation Darkvision; Lesser Corpse
Servants have no printed Darkvision. passive_perception_override supplies 8+PB.
Black-Lantern Commander seals +CL HP/+10 Speed onto owned Grave Formations.
zero_hp offers its once-per-scene final bloodied Grave Assault against perceived
enemies in native attack reach, then returns None to preserve normal collapse.
The owning summoner's evented spent condition shares the scene allowance across
formations. Declining leaves the allowance. can_strike rejects incapacitated
formations before consent or spending. No new zero-HP outcome is supplied.
Guard's step and Commander's last assault use pending_damage.current plus the
public choice_prompt.action_context helper to name the actual packet action,
source creature and protected/collapsing creature, never the outer intent."""
