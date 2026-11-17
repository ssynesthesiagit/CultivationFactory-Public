"""Pressure Points second pass (A2PRESSURE): pressure_points_second_pass uses the
existing effect, compile_action, candidate_allowed, choice_reactors, event,
contest_check_mode, attack_packet_start, attack_result, after_miss and
hit_snapshot and hit_final hooks. Recovery
asks the willing recipient for exactly one benefit and stores a recipient-wide
short/long-rest receipt. No rest transition occurs during a fight. Pulse Diagnosis
uses resolve_opposed_check with hazards=["pressure_points"], a table-selected
printed anatomy DC, and reveals selected represented facts. Patient Hand's new
row opts into a perceived target choice; automatic choices are restricted to
perceived enemies rather than treating side as a preference. The represented
Medicine check consumes it only after an actual CHECK_ROLLED receipt.
Heartbeats binds its opening to the first actual ATTACK_ROLLED id. A confirmed
primary packet delivers its selected 6d10 Force/Psychic attached bonus using
Context.on_hit_context; a miss or post-roll cancellation consumes the opening
without damage. hit_final delivers the same bonus if a confirmed attack has
no primary damage packet. Preview/mode queries are pure. The binding is a primitive
namespaced turn flag, and nested attacks cannot claim the parent's bonus.
Stolen Pulse Step seals its new effect in the owned Point row, samples the mark
before damage/on-hit riders via a pure hit_snapshot receipt, and uses the existing
native granted-movement adapter. Its owned sealed Point row enrolls its manual
owner in choice_reactors independently of reaction automation, so an off-turn
hit cannot give the controller the player's distance/destination decisions.
Pressure Points choices separate chooser and affected subject and use the shared
choice_prompt.action_context for the actual delivery action, including nested
attacks. Diagnosis consent is independent of whether the recipient perceives the
caster: only the printed eligible states or self-targeting bypass that question.
A free source-owned setting permits a Point rather than a Seal on marked targets.
Shut the Heaven Gate queries ordinary condition immunity and delivers Dazed on
a failed save by a Stunned-immune target. Intercepting Tap parks the hit/miss
outcome with attack_reduction.park on the still-pending triggering hit; its
counterattack uses the normal unarmed profile. Meridian Stillness Field queries
qiweaving_common.is_secret_inheritance before its once-per-round trigger.
Its field predicate uses live ENEMY relations for every standing hindrance and
activation trigger, including marked neutral and cross-team allied creatures.
No per-ability core branch or new hook.
"""
