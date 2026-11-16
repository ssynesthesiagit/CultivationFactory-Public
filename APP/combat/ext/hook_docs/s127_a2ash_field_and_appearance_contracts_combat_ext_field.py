"""A2ASH field and appearance contracts (combat/ext/field_rules.py):
  hide_concealment_allowed(engine, actor) -> True | False | None, strict pure
      permission to Hide in lesser concealment. Shared by Hide admission and
      movement reveal; never bypasses Search, attack reveal or superior senses.
      No subscriber/opt-in leaves historical concealment unchanged.
  Native inside/trigger rows may declare exclude_owner=true for printed
      allies-only benefits, enforced as a hard zone_recipient_allowed veto.
      You-and-allies rows omit it; no flag preserves old saved recipients.
  Native inside rules: terrain_immunity {names, owner:source|any} excuses only
      named terrain's difficult ground/traversal, not its ability damage or other
      overlapping sources. Terrain immunity queries current_inside_grants at the
      live landed square, using sync_inside's eligibility/newest-copy policy; it
      emits no events and does not reorder independent entry damage.
      healing_minus_source_pb deducts each distinct source
      owner's PB while inside. concentration_disadvantage_if names a required
      typed condition; applies only to system:combat.concentration saves.
      suppress_hide_invisibility masks only native Hide, never other Invisible.
      step_after_enemy_miss_ft offers the defender an optional voluntary no-OA
      step through granted_movement.choices/move: native Speed/candidate vetoes,
      terrain/path costs and hazards apply; ordinary movement is preserved and
      opportunity immunity is scoped to this move. condition_choice_owner enrolls
      each active grant's manual bearer during AI turns; AI bearers stay automatic.
      The prompt names the granting source and actual triggering action/actors,
      with an explicit no-Action/no-Reaction/no-resource price.
      hide_in_light_obscurement grants the permission above while obscured.
      damage_resistance_rules carries native defense rows, optionally
      except_damage_types or mundane_only; native defense provenance, penetration
      and resistance suppression still apply. Missing keys are inert.
  summons.json appearance_traits is deep-copied into new sealed summon records.
      summon_appeared applies evented fly_speed_ft/flight_hover and
      destroyed_terrain {name,terrain,radius_ft,until_owner_next_start}.
      Zero-HP destruction creates one placed patch at the actual destroyed cell;
      dismissal never creates it. Consume the appearance condition once. Expiry
      occurs at the next actual or omitted nominal owner START_OF_TURN boundary.
      Old summon records lacking traits keep their original behavior.

  move_typed_area.perceived_aim=true limits automatic destination scoring to
      currently perceived enemies. No field preserves old saved-area preferences.
      Player choices still include every legal destination within the printed reach.
      field_rules' automatic miss-step preference consults the defender's own
      perception; an unseen attacker does not supply a position to score against."""
