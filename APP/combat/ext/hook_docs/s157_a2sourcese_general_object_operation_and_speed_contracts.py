"""A2SOURCESE general object-operation and Speed contracts:
  object_operation_gate(engine, actor, object, operation, source_id, intent) -> None or bool.
      Strict dispatch. False refuses an opening, moving or breaking attempt,
      after ordinary costs but before object mutation/damage. Consumers are
      Thread the Object's selected OPEN/move and objects.deal (all damage
      callers). Closing is not an opening. Providers may roll native checks,
      journal results and raise ControllerPause for transaction rollback.
      No provider/None preserves ordinary operation; environmental actor=None
      has no creature check by default. Source Lock uses persisted source_lock
      zone profiles {source_lock:true, dc:int, object_id?:str} and the native
      movement_attempt/forced_movement_attempt hooks. Object seals end when
      their target is destroyed. A passed section traversal is scoped to the
      accepted movement intent; it never exempts later uses.
  condition.data.speed_penalty_group / speed_penalty_ft:
      Opt-in timed, nonstacking Speed reductions in the base engine. The group
      is a nonempty string; feet is a nonnegative integer. Only the maximum
      feet in each group counts, while distinct groups add to existing Speed
      deltas before the normal zero floor. Each condition retains its own
      caster and expiry, so the next strongest live contribution resumes when
      a stronger one ends. suppress_speed_penalty_if_floor=True optionally
      ignores that contribution while an ordinary Speed-floor feature is
      active. Missing fields preserve every historical calculation. Source
      Pulse uses this data; no ability name or special case is in core.
      motion.speed_adjustment(engine, actor, replacing_source=None) is the
      shared fixed-adjustment query used by base Speed, typed Speed-setting
      effects and derived walking-Speed bonuses. It includes grouped penalties
      and their live suppression. replacing_source omits integer ADD modifiers
      that a setting effect is about to refresh. Zero overrides, halving and
      passive/hook bonuses remain at their existing caller stages; the helper
      never calls Speed hooks or changes state.
      motion.grouped_speed_penalty(engine, actor, condition) returns one live
      contribution before group aggregation, or zero while suppressed/floor
      ignored. end_effect categories speed and movement use this same reader
      to select individual reductions under their normal source/team filters.
      Meridian Unbinding uses speed for both its menu and removal, and asks
      the player to choose one instance. Ending one never ends a whole group.
  Remote Source Pulse origins reuse effect_origins for range/LOS/LOE/cover.
      Known mechanical terrain supplies mineral material; cosmetic floors do
      not. The visible point is within 30 feet of the physical caster. Target
      perception resets to physical caster geometry, never the remote point;
      automatic modes require the caster to perceive the target. Section
      seals use positive mechanical material evidence at the same altitude.

  General temporary battlefield presence (A2SPACETHI):
  battlefield_presence(engine, actor) -> False or None is a pure opt-in veto.
  Automatic summon placement (initial one-cell and whole-footprint restoration)
  excludes active creatures vetoed by this query from occupied cells; retained
  coordinates alone never obstruct a landing. Present active bodies still block.
  No provider preserves occupancy, invariants, perception, remembered targeting
  and falling. Self-knowledge stays available for permitted self-only actions;
  no outside perception is granted. Life state, victory and initiative remain independent. Providers
  must handle lightweight senses.cell_probe objects (conditions is available).
  spatial_absence {applies_to, duration/expires_on, incapacitated?, repeat_save?,
  on_return?, end_concentration_on_return?} stores an exact-instance native condition and a JSON-only return
  record. Native expiry/repeat saves, dispels and concentration loss converge on
  nearest legal whole-body return at the original altitude. Printed incapacitation
  uses no_actions/no_reactions/speed_zero and ends the recipient's concentration.
  On-return effects run after presence returns, with original owner's numbers.
  Opt-in end_concentration_on_return ends the exact recorded current/held copy,
  preserving unrelated activations; default false keeps other consumers inert.
  The recipient remains alive/in initiative and cannot affect outside creatures;
  zones and outside damage cannot affect it. Absence vetoes command_reachable
  and summon_check for either absent owner or absent creature; a SELF button
  does not imply a self-only effect. Summon/restore buttons declare the existing
  summon_group metadata so candidate_allowed hides them during owner absence.
  Command buttons use their normal commandable query for matching eligibility.
  Proximity qualifications query engine._on_battlefield rather than active life
  state: an absent ally's retained coordinates cannot qualify an outside hit.
  These queries are inert without a presence provider/matching absence record.
  A full map retains a pending return
  and retries at turn starts rather than overlapping another body. No matching
  condition means no behavior/event changes. Ordinary perceived enemy selection
  remains authoritative. Fold Prison and Exile use the complete
  route; Void's Action uses it with delayed psychic damage. Void's Reaction is
  still a visible manual clause and is not claimed automated.
  teleport_settled(ctx, subject, previous, destination, unwilling) -> None is a
  strict transactional checkpoint after a shared teleport and its entry hazards.
  No provider adds a choice or event. Default unwilling=False preserves all
  existing cooperative/self consumers; subject_repositioning seals target rows as
  imposed unless their explicit unwilling flag says otherwise. The caller owns
  that accepted transport's willingness. Anchored Soul asks the affected owner
  for its optional prior-space return, marks its allowance only on an accepted
  hop and does not spend a Reaction. Its compiled passive marker also supplies
  spatial-save Advantage from explicit teleport/absence consequence rows or
  spatial_transport={banishment,pocket_entry,possession,planar_travel,
  unwilling_teleport} metadata; unrelated saves and unowned recipients are inert.
  zones.on_moved(..., reappeared=False) is a general entry-only arrival flag:
  true treats each arrival area as newly entered even when returning to the same
  coordinates. Native subject gates, entry counters and triggers remain in force;
  false preserves ordinary movement and historical teleports. spatial_absence
  is the first caller, so reappearing cannot evade an existing damaging area.


  Saving-throw bonus statuses (A2SPACETHI): save_bonus_status.native_save_bonus
  uses the existing save_bonus(engine, target, ability, dc, source_id, intent)
  checkpoint and native d20_context.named to honor the status's ability/against
  filters on repeat and legacy saves. active_save_pending identifies typed saves
  already adjusted by the save hook, so each bonus applies once. No matching
  status returns None; no state, events, mode or dice draws are changed."""
