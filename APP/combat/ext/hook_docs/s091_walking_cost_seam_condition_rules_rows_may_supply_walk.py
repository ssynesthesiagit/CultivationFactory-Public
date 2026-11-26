"""Walking cost seam: condition_rules rows may supply walking_extra_cost (integer
extra feet per foot, default 0; duplicate rows use the maximum). posture.walking_extra
is a pure shared query walking_extra(engine, actor), used by ground path search
and flight.step_cost execution. walking_cost(engine, actor, normal_extra) ->
None | nonnegative integer is a pure hook to reduce the condition's extra cost
(minimum answer wins; None preserves it). It is only queried for a positive
condition cost; providers must be inert without their own ability/state.
Gate2Grid reachable/shortest_path/movement_step_multiplier accept the optional
extra_step_multiplier=0, added to terrain before drag pricing. Speed and standing
cost are unchanged. No condition carrying the key preserves legacy paths/costs.
The separate no_jumping condition flag (default false) prevents jump offers;
extra walking cost alone does not restrict other movement modes.
posture.standing_cost is the pure stand_allowed/stand_cost query for a mid-turn
Stand Up offer; posture.stand_up remains the sole recorded state transition.
Both use standing_cost's eligibility, veto, cost-provider and budget checks;
explicit ability costs bypass cost providers, and ignore_speed permits zero
Speed, but neither bypasses vetoes or the movement budget.
Standing candidate metadata contract: gate2_engine.legal_candidates produces
standing_cost_ft as a nonnegative integer number of movement feet (including 0)
only for an eligible system:combat.stand_up candidate. It denotes movement-only
payment, consuming neither Action nor Bonus Action; tabletop_service uses it
for the cost label. LocalDeterministicController treats its PRESENCE as an
unconditional posture score of 10000, preferring standing over ordinary choices.
Other providers must not attach this key to unrelated actions. Absence leaves
normal presentation/scoring unchanged; no new saved-state field is introduced."""
