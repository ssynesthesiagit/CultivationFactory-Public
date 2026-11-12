"""A2GTRA1 — death-save failure interception:
death_save_failure(engine, subject, natural, source_id) -> bool | None runs
after a failed death save has been rolled/recorded and before its failure(s)
are counted. True ignores that entire roll's failure, including natural 1;
False/None retain it. Providers run lazily in order, stopping on True before
another provider can spend. Invalid replies/errors propagate for transaction
rollback. Providers own consent, economy, costs and protection effects. No
providers preserves the ordinary lifecycle and deterministic dice stream.
Candlemaker consumes this seam for Last Flame; borrowed_final_breath consumes
the existing fresh_zero_hp LIFE_STATE_CHANGED event for its single debt.
New effects dream_touch_waking and choir_hymn_success use existing effect,
event, expiry and needle choice transport. Cursed Sleep's bond intervention
uses match_start/additional_actions and its existing repeat-save path.
boundary_walker.border_passage returns existing pass_through='difficult'
only while its owned state is active. Bearing Without Name changes one rider
per actual turn, retaining paid tokens, route categories and damage count.
"""
