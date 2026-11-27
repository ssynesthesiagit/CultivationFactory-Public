"""Default-inert shared movement and equipment seams, each read by one general core
query that every ability reuses:
  movement_segment_surcharge(engine, actor, previous, destination, mode) ->
  nonnegative integer feet added to that one edge's price. Quotes and commits
  call the same movement_costs.segment_surcharge, so the menu price and the
  movement actually spent are always the same number. The default is 0 feet;
  non-integer or negative answers raise. Forced displacements charge no
  movement and never price it.
  movement_edge_allowed(engine, actor, previous, destination) -> bool vetoes
  one physical edge; only False vetoes and no answer is inert, so a creature
  with no provider crosses every edge exactly as before. Every movement mode
  and native vertical displacement honour it.
  equipment_use_allowed(engine, actor, kind) -> bool is a checkpoint: False
  vetoes using equipment of that kind and never transfers, destroys or drops an
  owned item; the default permits use. Only 'shield' has a reader today
  (armour.shield_bonus_earning); a weapon reader joins it in the slice whose
  ability needs one, reusing this checkpoint instead of a second query.
  pass_through_allowed(engine, actor, occupant) -> bool vetoes passage through
  that occupant's space; only False vetoes and the default grants nothing.
  support_override(engine, actor, position) -> bool supplies or withholds
  ordinary ground support at one position. True grants support immediately;
  False withholds it but still honours an independently granted
  support_surface(engine, actor, position) -> True.
  technique_refund_allowed(engine, actor, source_id, resource, refund,
  refund_source) -> bool vetoes a native refund; only False vetoes.
Conditions may carry movement_credit_mode (native mode), movement_credit_ft
(nonnegative integer feet), and movement_credit_axis (horizontal/vertical or
absent). Pure movement_credit_allowed(engine, actor, condition) -> False may
veto a receipt; None retains it. Applicable credits pay actual committed steps
before ordinary movement, with CONDITION_UPDATED receipts and MOVEMENT_COMMITTED
cost_ft recording ordinary feet only. The planner, route validator and executor
share flight.path_allowance for the exact path and spend the same receipts per
edge. jump_allow_unsupported=1 in an active jump credit keeps
every legal jump option reachable for AI seats as well as humans. No such
metadata means unchanged native routes, movement spending and AI policy.
INS7E general Study observation seams (shield_breaking_eye provider):
  study_creature(ctx, effect) is a harmless typed effect observing each active,
  actually seen target and strictly notifying creature_studied(ctx, target) -> None.
  No subscriber means no information or state change; consumers require their own
  compiled row. visible_defensive_posture(engine, target) -> True/None is a pure
  observable posture query. Native carried shields, Dodge, Guarded Stance and
  Turning Guard are recognized through their public condition contracts;
  source-authored conditions may carry integer data.visible_defensive_posture=1.
  Missing facts are inert; concealed AC bonuses alone never establish an obvious
  posture. study_action=1 marks a Study Action; no automatic Reaction/resource spending."""
