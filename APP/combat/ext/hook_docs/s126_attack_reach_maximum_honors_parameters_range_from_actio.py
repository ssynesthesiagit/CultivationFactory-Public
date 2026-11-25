"""attack_reach.maximum honors parameters.range_from_action: an owned direct
catalog source binding, with no chaining, supplies its current weapon reach
(catalog reach variants plus condition-bound additions). Missing/wrong-owner
bindings reject. Absent binding retains all historical queries.
extra_targets action_reach reads that live maximum; exclude_self removes the
user, and legal_recipient checks ordinary recipients.allowed for each choice,
preserving LoS, LoE, range, relations and creature knowledge. These flags are
opt-in; old rows retain their old menus. Circle-Cleaving Saber is the consumer.
stance hit_riders turn_clock="current" limits once_per_turn by current actor
ID and turns_started, rather than the owner's turn reset. The token stays in
existing turn_flags. kill_ally_consent is copied into the native condition;
Sabers' Execution Platform Presence event consumer asks the selected ally via
Needle's ordinary choice transport before ending exactly one Frightened effect.
Without these fields legacy stances retain their clocks and choices.
sabers_riders uses compile_actions to seal a selectable physical expression per
qualifying base saber (excluding reach/off-hand/delivery variants). The first
keeps its prior id/label; alternatives name their weapon. Each uses the same
range_from_action, saber_weapon_source and weapon_source_id for reach, attack
numbers, damage and possession; candidate_allowed withholds unavailable or
stowed expressions. A player explicitly chooses the expression. The Qi-only 30-foot
Feint variant is sealed at compile time; no live sheet/current prose is read.
Feint's attack_mode query is pure; attack_result consumes its target/sphere
condition only on an actual roll. Native end-current-turn expiry owns unused
benefits and source-specific opportunity denial. Attach-saber weapon damage
honors the new sealed saber_weapon_source; absent fields retain legacy lookup.
kill_ally_consent requires the selected ally's own willingness answer, with
ordinary ally/range eligibility and no printed perception prerequisite. Only
computer-controlled recipient choices are bounded by the actor's perception;
manual recipient and ally consent choices remain the player's decisions.


  attack_spec_choice(ctx, target, attack, spec, attack_index) -> None.
  General per-strike choice seam after declaration/spec preparation and before
  flat attack/damage bonus hooks, attacked reactions or the roll. Providers may alter this transient spec's
  attack bonus, damage DiceSpec, fixed damage and private typed metadata; never
  mutate the catalog, sequence dice or ctx.typed. Called inside current_strike's
  scope, whose scratch lasts through hit riders and restores on nested attacks,
  pauses and exceptions. Without a subscriber, the historical spec stays identical.
  A replaced spec['typed'] becomes the private current-strike Context metadata
  for remaining hooks and hit riders, then resets before the next strike.
  attack_abilities.select_strike_ability replaces one weapon ability and marks
  it resolved; substitution providers check resolved_strike_ability to avoid
  adding a second ability delta. Additive bonuses are unaffected.
  attack_ability_options(ctx) -> dict[ability abbreviation, integer modifier] | None.
  Runtime substitution providers offer currently legal ordinary alternatives;
  they check their own ownership, delivery and printed eligibility. Collected
  by attack_abilities.strike_options for player/AI choice; never edits saves.
  attack_only_ability_options(ctx) -> dict[option id, {modifier: int, label: str}] | None.
  Strict; each provider owns runtime eligibility. Collected by
  attack_abilities.strike_attack_only_options. These named alternatives preserve
  the prepared weapon's damage ability; ids must not collide with ordinary
  abilities or another provider. Without a subscriber, no options are added. Named options
  remain separate from an ability's attack-and-damage grant.
  select_strike_ability(..., damage_modifier=None) accepts an explicit separate
  damage ability component; omission retains its attack-and-damage behavior.
  Wrong-Hand Strike uses both shared contracts for per-strike ability choices;
  an attack-only option labels and logs its unchanged damage scope.
  forced_destination.ask(..., prompt_context=None) forwards optional display-only
  action metadata to Needle. Existing consumers retain their prompts and choices.
  choice_prompt.action_context(..., action=None) accepts an explicit current
  action for resolution-built reactions absent from the sealed catalog; omission
  keeps source lookup unchanged. rider_choices.step(..., prompt_context=None)
  forwards display metadata for the same Drunken Style attack follow-up choices."""
