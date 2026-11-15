"""Foundation combat conversions (A2GFOU2): foundation_combat uses compile_block,
compile_action, compile_actions, after_hit_choice, save_final, technique_used,
final_damage, d20_bonus, save_mode, ability_check_mode, attack_magical,
escape_check_mode and event callbacks.
Reviewed foundation_alignment lists seal a technique's eligible conversion
families; no runtime sphere/name inference. Resource clocks belong to pressure.
transaction_settled(engine, source_id, actor_id, intent, first_sequence) -> None
is a general strict, default-inert receipt boundary inside the transaction, after
foreground resolution, action-completed responses and final falling, including
terminal outcomes and native turn effects. first_sequence is the sequence before
this transaction. intent may be None at unprompted system/bootstrap boundaries.
Subscribers consume settled receipts; they must not start new damage or actions.
damage_receipt_facts(engine, target, source_id, source_actor_id) -> dict | None
is a pure, default-inert query immediately before committed HP changes. Replies
add nonoverlapping primitive int/string/list fields to DAMAGE_COMMITTED, never
replace base packet fields. Ash-owned fights record target_active_before (integer
0/1), target_conditions_before (internal condition IDs) and target_perceived_by
(observer IDs captured before defeat). Consumers must not expose hidden condition
IDs or unseen creatures in prompts or automatic-seat context.
foundation_context supplies public source_method_facts, settled_execution_events,
adjudicated_event_context and ash_aligned for Ash generation/Strike/Garden/Mercy.
Exact source hashes seal method categories at compilation. These are conditional
method facts, not unconditional alignment. Actual table/controller answers bind
public scene judgments to one source/target/event/intent in a PASSIVE_TRIGGERED
receipt whose fact_kind is foundation_event_context.
Unknown circumstances, residue and ending judgments stay unknown; automatic seats
cannot attest unknown scene facts. In Ash-generator fights, choice_reactors
enrolls conscious human-controlled witnesses. damage_receipt_facts additionally
records target_context_witnesses_before (IDs of those who perceived the target
before the packet). An automatic owner can consume their event-scoped public
table testimony for incoming, outgoing and ending routes; without such a witness
it answers unknown unless public encounter facts were explicitly recorded at
fight setup. foundation_context.public_scene_choices uses prefight_setup_choices
to declare optional, default-unknown public circumstances, battlefield residue
and meaningful-enemy-defeat rulings known to that creature for this encounter.
The existing service validates/seals these integer lists in genesis. match_start
journals them as foundation_public_scene receipts; public_scene_context(engine,
owner) returns only that owner's public receipt, never another actor's knowledge.
Automatic owners consume these established facts without a human prompt, while
event receipts still enforce hostility, prior helplessness and actual observed
defeat. Unspecified details remain unknown; fire damage cannot establish residue,
mercy or cautery. Context receipts link setup_sequence to their public provenance.
No setup declaration grants Ash or changes its clocks/costs. Testimony never
transfers the owner's spending decisions. Leave varying/private context unknown.
Ending context uses the matched damage receipt for witnesses, target and causal
action metadata; a generic defeat-wrapper source never replaces that packet.
adjudicated_event_context accepts alignment_only=True for hit consumers that
need source-method/residue facts without generation-only danger exclusions.
Its default False preserves generation circumstance prompts and public setup or
witness adjudication; generation consumers additionally require circumstances
equal to real. ash_aligned checks alignment only, not resource eligibility.
unconscious_condition recognizes
the supported unconscious states, including Dream Sleep, for both live owners
and pre-packet helplessness; it does not treat all incapacitation as helplessness.
The Ash generator consumes these receipts only
after settlement; native pressure alone owns its cap, round clock and expiry.
foundation_mercy consumes that same settled boundary for owned Ash Mercy spends.
Its native choices bind restraint testimony to an actual paid source, a perceived
mechanically helpless/defeated creature left unharmed by that execution, and one
recipient within 30 feet. Unknown intent never becomes a positive fact. These
receipts do not assert cautery or clean-ending provenance or generate resources.
foundation_context.public_scene_declarant(engine, owner, subject, source_actor_id)
returns a manual owner or a conscious player-controlled ally who can perceive
the source, subject and owner and is perceived by the owner. The owner must
perceive the subject; current relations determine allies. Mercy uses this
event-scoped testimony without inferring positive intent from setup facts.
foundation_context.event_source_facts(engine, event) -> dict returns public
source_definition_id, name and actor_id. Defeat wrappers resolve defeating_source
or the matching lethal damage packet in the same transaction; unknown identities
keep a neutral description. Generation uses its explicit matched damage receipt.
foundation_context.paid_source_facts(engine, event) -> dict | None returns an
owned compiled action/reaction/passive's mechanic_id and name only for a positive
RESOURCE_SPENT receipt. Administrative drains, expiry and unknown sources are
inert. Identity alone establishes neither mercy nor resource provenance policy.
Selected Refined expressions are evented, exclusive fight settings. The optional
foundation_expression_selected(engine, actor, feature_id) -> bool | None pure
query narrows an owned Foundation rider; False vetoes, absent replies are inert.
The public foundation_conversion_bonus.conversion_bonus(engine, actor,
conversion, receipt_id=None) pure query and settle_conversion_bonus(engine,
actor, conversion, receipt_id, source_id) paid consumer share numeric increases
between foundations4 Cut/Guard, foundations4_rolls Clarity/Blackblood/Reed/Witness and foundations3 Lotus-Root Recovery.
The pure conversion_consent_note(engine, actor, conversion) -> str helper
supplies these consumers' pre-consent shared-round warning; absent, suppressed,
unselected or already-spent once-round rows return no warning.
Owners publish foundation_conversion_bonus feature blocks: conversions (strings), extra_pb
(integer), selected (exclusive Refined setting), once_round (boolean), and optional resource_id (the paid pool's id, default Severance Edge),
names (conversion -> printed name map), pool_label and bonus_phrase (printed wording, default Severance Edge). Quotes
never claim a round. Settlement requires a matching native resource debit,
stores primitive receipt fields and changes one existing conversion value.
Unowned rows are inert. compile_bundle carries explicit owner-sheet Foundation
status with provenance; Suppressed vetoes the improvement, absent/unknown
status is preserved. Selected rows use native setting actions and AI defaults.
Owned rows also publish native "record suppression/recovery" table settings,
which record a Game Master's source ruling rather than granting suppression or
repair. Accepted settings persist explicit source status and provenance until
the opposite ruling is recorded. They cost no combat resource, do not reset a
round receipt, and have no AI default; ordinary dispels do not alter them.
Foundations4 conversion riders (MGR-T14 whole Refined parents):
foundations4.conversion_evolution_pb(engine, actor, row) -> nonnegative int is
the shared public helper every Foundation conversion family's Refined rider
reads. A compiled foundations4 row may seal refined_expression, the feature id
of its printed Refined evolution; the helper returns that row's own PB only when
a foundation_expression_selected hook explicitly answers True and no hook
vetoes, else 0. Guard, Return and Refusal riders read it on their own compiled
rows. The Perfected term of the same conversion is settled by
foundation_conversion_bonus.settle_conversion_bonus, so Refined and Perfected
improvements stack at the same numeric point of one conversion -- the same
actual spend, Reaction and damage packet, never a second Reaction or resource
spend. The Blackblood family's Refined expression is an ordinary Foundation
expression setting (foundation_combat declarations and selected_query, group
'blood'): an evented, exclusive, once-per-fight choice offered by the compiled
Foundation stage, which is cumulative, so a Perfected owner also owns and may
select its Refined expression.
Blackblood Refusal's selectable Refined expression (Venom-Dark Marrow, the 'blood'
group) is read the same way: its foundations4_rolls conversion adds its own PB to the
same roll through conversion_evolution_pb with that refined_expression.
technique_cost_discount(engine, actor, source_id, cost_totals) -> mapping | None
is a strict pure query before technique_cost_floor in technique_costs.effective.
Values are nonnegative integer reductions of listed resource costs; reductions
sum and clamp to that resource's cost. Costs, duplicate rows and zero events
retain order; no subscribers preserve exact prior costs. Consumers own sealed
eligibility and evented use limits. Quotes never consume a use; actual payment
owns RESOURCE_SPENT and the transaction owns rollback. Callers explicitly
supplying reduced_costs keep their own arithmetic: this hook is not asked, while
the payer's ordinary temporary cost reductions and technique_cost_floor still are.
damage_value_adjustment(engine, target, amount, damage_type, source_id, source_actor_id, intent) -> int is an opt-in resolution hook.
Core sums validated adjustments into the original packet before resistance,
damage reactions, concentration checks and DAMAGE_COMMITTED. Providers own
eligibility, consent and any resource debit; they must not create a second packet.
damage_value_reduction(engine, target, amount, damage_type, source_id, source_actor_id, intent) -> int is an opt-in resolution hook.
Core applies validated nonnegative reductions before defenses and reactions,
clamping damage at zero. Providers own eligibility and once-use state; they must
not create a second packet. No providers means no behavior change.
The typed extra_damage data flag inherit_damage_type (boolean, default false)
inherits the confirmed hit's damage type from its Context damage cache rather
than asking for a new type; absent confirmed damage it retains the listed
damage_types fallback. It changes only opted-in damage rows, not base damage.
Dream-Mirror's dream_mirror_conversion compile_block is an ownership marker:
Reflection Cut is offered only after a hit or failed damaging save, never as
an upfront modifier. Its spend has no round limit; Trace generation and Domain
amplification keep their separate round clocks. Sovereign Momentum resolves
its distinct second legal conversion inside the triggering spend, never by
refunding a spend for a future trigger.
escape_check_choice_required(ctx, effect, dc, grips, hazards) -> dict | None:
pure optional ownership query before a native escape; a reply names the
feature requiring a choice among every sealed skill. None retains the native
selector. No skill is removed; AI ranks only its own known bonuses/modes.
The following existing observation/AI contracts also belong to this module
docstring (their detailed notes remain beside the registry below):
target_personal_knowledge(engine, viewer, target) -> Knowledge | False | None:
pure personal targeting override; False means unknown, None retains native
knowledge. Native/manual execution does not consume this hook.
personal_observation_receipt(engine) -> dict[str, primitive] | None:
committed-target observation metadata stamped into the final event. Providers
own disjoint top-level keys; receipts merge without discarding other providers.
No reply adds nothing, and queries never write or increment a sequence.
Void-Touched Cultivator records its owner's actually perceived terrain cells
here and at movement_landed, never recomputing old sight from today's geometry.
ai_observation_frame(engine, actor, candidates, policy) -> OwnKnowledgeFrame | None:
pure personal projection excluding hidden truth and global revisions. None
retains native behavior; remembered creatures do not expose private sheets.
ai_movement_hazards(engine, viewer, candidates, frame) -> dict | None:
pure perceived hazard estimates; no candidate removal or mechanics change.
None retains native hazard metadata.
ai_policy_enrichment(policy, sheet) -> dict[str, Any] | None:
pure optional policy additions from the owner's sheet/package guidance.
None is default-inert and leaves the base policy unchanged.
ai_movement_order(context, rows) -> tuple[candidate_id, ...] | None:
pure destination ordering; every reply must be a permutation of the full
native menu. None retains native ordering; no legal option is removed.
ai_decision_annotations(engine, viewer, candidates, known_actors, frame, policy)
-> dict[candidate_id, dict] | None: pure ordinary-turn scoring metadata. Called
only for AI non-bystanders after perceived hazards/knowledge are prepared.
Providers may add estimates to detached candidates, never change identities,
remove options, simulate effects, or grant execution authority. None adds
nothing. Queries and caches must expire with this one decision; frame may be
None. Ground attack forecasts and future tactical annotations share this seam.
ai_score_components(context, candidate, option_ids) -> tuple[ComponentScore, ...] | None:
pure additive analytic values, without rolls, spends or engine copies.
None adds nothing; ordinary scoring and emergency precedence remain intact.
ai_light_policy(engine, actor, action) -> {"creates_darkness": bool} | None:
pure classification of one owned ability for the Tricky darkness terms (spec
§9, §11 S4). Asked per owned action while the AI profile is built; reads only
that action's own typed data. None means the ability makes no Darkness; the
darkness-maker row list lives with the rule (combat/ext/lighting.py), not in
the AI. Answers only add the darkness weight; no legal option is removed.
Banked Furnace Expenditure uses native payment_substitution; normal payment is
also offered. Automatic Court choices contain only perceived allies; rosters are rechecked for side
and range at each roll. Subject declarations consume no action.
"""
