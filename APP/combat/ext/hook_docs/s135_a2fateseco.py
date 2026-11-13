"""Second-pass general roll contracts (A2FATESECO):
before_d20_bonus(engine, request, intent) -> int | None runs transactionally
before a deterministic d20 draws any die. request is a fresh dict with actor_id,
reason, mode and modifier; providers cannot see a result. Contributions are
additive integers; bool/non-integer replies fail and unwind the transaction.
Providers own choices, payment, consumption and events. prepared_d20 performs
this checkpoint and the initial draw without post-draw rewrites; opposed checks
use it once per participant, then rewrite against the opposing totals in their
existing order. d20 also uses it before its immediate post-draw rewrite.
raw_d20 intentionally
bypasses this checkpoint for an already-selected replacement/reroll. Absent
providers/owners add nothing. Do not also add the same bonus in attack_bonus,
check_bonus or save. The stored RollRecord includes the final modifier.
d20_mode_removed(engine, request, intent) -> None or an iterable of
"ADVANTAGE"/"DISADVANTAGE" runs transactionally in the same pre-draw checkpoint,
after before_d20_bonus and before a fixed natural result. request is a fresh
dict with the already resolved actor_id, reason, mode and modifier. A token that
matches the resolved mode cancels it to NORMAL for this one draw only; a token
that does not match is inert, and a NORMAL roll is never turned into a mode.
Providers own eligibility, choices, costs and events (a choice pause unwinds and
re-runs the whole action, as with every transactional hook). No provider means
every roll is drawn exactly as before.
Skill-specific check consumption: ext.roll_context.check_skill_receipts reads
CHECK_ROLLED payload.skill for the acting check and payload.target_skill for the
defending check. Both identify the actual selected skill, or None for an
unskilled check. Saves/DCs are not check receipts; against is descriptive only.
Legacy single-check producers may omit the key and use a skill-suffixed reason.
Display labels belong in payload.check, not skill. Legacy combined-skill checks
may use mode_skills (target_mode_skills for the defender) to name every exact
skill-mode input actually consulted for their one draw with the existing better
bonus. This metadata consumes matching one-check benefits without pretending a
skill was selected or adding a roll. ext.scoped_checks.escape_skill_metadata
is shared by the escape resolver and Trap for these receipts. Shared recipient
views must prepare all modes before the first receipt and repeat the same skill
metadata/dice; a consumption event cannot change later views of that draw.
Consumers retain their non-skill restrictions when consuming a skill benefit.
attack_mode_contribution(engine, attacker, target) -> roll mode | None is a
strict PURE query for both native and typed attacks and menu presentation.
It contributes before ordinary cancellation and removal, preserving other
Advantage/Disadvantage sources. It must never ask, spend or consume effects;
before_attack owns any triggering choice. No owner means no contribution.
Roll-reason attribution (2026-10-16): a provider may instead return an
attributed dict reply {"mode": "ADVANTAGE"|"DISADVANTAGE", "effect": name,
"why": plain reason, optional "owner" display name} so the displayed roll
reasons name that ability; a bare mode string keeps the shared generic
label. Same-kind contributions from different providers are each kept
visible; unique_sources collapses only literally identical rows.
Help acceptance: help_policy.allowed(engine, helper, recipient) is the public
strict policy for assistance explicitly granted through Help. Producers query
before offering/delivering Help; ordinary buffs never call it. Optional PURE
help_benefit_allowed(engine, helper, recipient) -> bool | None can veto only
the recipient's acceptance. No provider defaults True; invalid replies fail
the transaction. Feint, Pact-Brother Battle Rhythm, Accomplice and assistance
with an escape all use this policy. Helping oneself is separately permitted
by the originating ability; this policy never grants new actions or targets.
A2GTRA2 packet allocation:
  damage_bypasses_temporary_hp(engine, target, defended_amount, damage_type, source_definition_id, source_actor_id) -> bool or None.
    Strict pure query for early drop/bloodied checks and, after defenses, before final floors, deferral,
    survival and DAMAGE_COMMITTED. Any True leaves Temporary HP intact and applies
    the remaining packet to HP; floors and survival see only available HP.
    No provider preserves ordinary absorption. damage_allocation.available_temporary_hp
    shares that decision with drop/bloodied thresholds; maximum_packet_before_hp_floor
    applies it to hold-at-one/rescue floors and lethal_threshold answers whether a
    defended packet reaches current HP. Early queries use the active
    damage_delivery identity and may supply an empty type when the old hook has none.
    The shared temporary_hp_bypass
    module owns a damage row's bypass_temporary_hp=True: a per-recipient/source nested scope
    restored on errors/player pauses, so reaction damage cannot inherit it."""
