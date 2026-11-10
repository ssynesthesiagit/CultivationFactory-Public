"""Native forced-save outcome checkpoint (A2GINS5):
  save_result_outcome(engine, target, ability, dc, roll, source_id, intent) -> None
  or {source_id: nonempty string, outcome: "success" | "failure"}. One strict
  provider may answer after all native save modifiers and before SAVE_ROLLED or
  numeric legacy consumers. The effective total is at least DC for success or
  below DC for failure, with the same arithmetic adjustment to modifier. The
  original draw is retained in the roll/rewrite history, and SAVE_ROLLED states
  forced_outcome, outcome_source_id and total_before_outcome. No new dice draw,
  actor schema or source ability case. No answer retains historical totals and
  event bytes; invalid/multiple replies roll back. d20_rewrite stages the exact
  roll-id/target-id receipt only for explicit Rule.outcome saves; staging and
  consumption join rollback. Non-native opposed saves retain their typed result
  override. The adapter makes Concentration/repeat/legacy callers honor explicit
  outcomes too, while ordinary rerolls and bonuses retain their existing route.
  _roll_save(..., outcome_receipt=dict) optionally copies total_before_outcome
  and any forced_outcome/outcome_source_id into a caller-owned transient dict.
  Ordinary typed-save and Concentration settlement use that original numeric
  result to avoid crediting unsuccessful support after an independent rescue;
  legacy totals stay intact.
Actual damage-defense receipt checkpoint (A2GINS5):
  before_damage_defenses(engine, target, amount, damage_type, source_id, source_actor_id) -> None.
  Strict notification in defend for positive packets after pre-defense transfers,
  immediately before the pure defense quote and one-packet Resistance consumption.
  Quote-only/AI queries do not enter it. Providers may retain primitive receipts
  in pending_damage.packet_scratch; they must not change HP, defenses, positions
  or payment, and must return None. Errors roll back the owning transaction.
  No subscribers or no owned consumer means no receipts, state or events.
  Already-defended bypasses retain their caller's result. insights_five uses this
  to recognize an independent next-packet Resistance after native consumption;
  its saved first-Lightning-packet round marker binds the printed first-packet
  reduction and mutually exclusive recovery variant to that round.
General carrying-capacity compilation query (A2GINS5):
  carrying_capacity_scale(info) -> positive integer | None. info carries the
  source/hash-admitted owned_ids, numbers and owner_sheet. Pure providers must
  not mutate these inputs. The compiler multiplies accepted scales into ordinary
  capacity before the encumbrance Speed decision and recomputes over from the
  existing textual load. Only integers/strings are sealed. Invalid replies fail
  compilation; absent providers preserve the original capacity and Speed.
  Native pickup/drop reads that sealed capacity; existing saved bundles are not
  recompiled. insights_five supplies Immortal's Sinews and Titan's Grip, whose
  independent printed capacity scales compound normally."""
