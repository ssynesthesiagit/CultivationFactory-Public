"""Reviewed generic reaction metadata: range_scale="speed" measures the subject
against the reactor's live effective Speed; subject_relation="any" admits
allies and enemies without changing the row's includes_self gate. Both fields
are optional and leave existing rows unchanged. They are transported by the
authority builder and compiler, without ability identifiers in core code.
Athletics Unbroken Pursuit uses the existing reaction_subject_allowed query,
teleport_settled and nested event observers for owned willing-movement sources,
then granted_movement.choices/move for all native paths, terrain, zones and OAs.
Its destination choice includes every closer legal path; only the triggering
creature is exempt from Opportunity Attacks. Providers are inert without that
owned reaction row. Native walking already publishes the moved event.
Supplemental movement observers use typed_reactions.dispatch_creature_reactions
(engine, subject, kind, moved_ft=0, accept=None, target=None, source_id=None)
to dispatch reaction rows only; accept(row, watcher) -> bool selects rows.
It returns None and skips motion.after_move and its subscribers: producers
retain their own movement-benefit contracts, including single counting.
Ordinary events continue through on_creature_event. With no matching owned
reaction rows the supplemental dispatch grants no reactions or benefits.
The existing climbing(engine, actor) capability also accepts climb_ceiling:
True admits a grip against a sealed roof slab from below, using the actor's
volume height and ordinary climbing routes, costs, checks and falling. Absent
metadata retains upright wall climbing. Spider's Touch with Sure Grip supplies
it while at least one hand is free; neither row alone grants ceiling traversal.
climb_physical_disabled=True withdraws physical wall/ceiling grips only; it
does not veto an independent virtual-wall provider or its recorded support.
Absent metadata retains physical grips. climbing_disabled remains the global
veto for conditions that prohibit every form of climbing.
climbing may also return climb_virtual_wall=True: native climb routes use a
provisional wall at any legal volume, charge difficult terrain, and retain
ordinary occupancy, step reactions, zones and shared movement accounting.
Absent metadata retains real-wall geometry. Routes are bounded by available
feet; all reachable destinations remain offered. The provider must revoke the
capability at its printed boundary. Air Stunt seals its owned Wall Stunt
prerequisite at compile_passives and revokes provisional support at turn_end,
then invokes native falling, preserving independent flight and surface support.
climb_hold_virtual=True separately permits a recorded grip on a virtual wall;
without it real physical grips still work but provisional air does not stop
falling. Air Stunt records its support on movement_begin and expires it at the
owner's next turn end, including movement taken as an off-turn reaction."""
