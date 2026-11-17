"""save_mode(engine, subject, ability, dc, source_id, context) -> None, ADVANTAGE or DISADVANTAGE,
a list/tuple of those modes, or {mode, effect, owner, why} with string labels. Strict pure
query read by Gate2Engine._save_mode_contributions for native saves and direct_save_mode.
Each mode is an independent contribution; all modes cancel together at the save's existing
boundary (Advantage and Disadvantage cancel). A dict reply adds a roll receipt (effect, owner,
why) shown on the roll's hover and feed; a bare mode gets a generic receipt. Any other reply
raises ValueError. Providers own their subject/ability/source gate and return None for everyone
else, so with no provider the save is unchanged. A provider that spends a next-save grant it
owns does so once, here. Numeric grants belong to save_mode_contributions below.
save_mode_contributions(engine, subject, ability, dc, source_id, context) ->
exactly {bonus: signed int, modes: list[ADVANTAGE|DISADVANTAGE]} or None is a
general transactional source-owned save contribution. Native _roll_save and
direct_save_mode use the common _save_mode_contributions reader alongside
save_mode, then cancel all modes at their existing boundary. Raw mode-only
callers set context.mode_only=True: providers still consume matching next-save
mode grants exactly once, but must return zero bonus without selecting or
spending numeric support that the raw caller cannot apply.
save_against.stored_modes is the single producer for its typed/native grants;
recognized pending consequence tags establish support purpose, while the held
grant supplies the real source actor/method. No grant or no provider keeps the
old save. The native roll_context.additional_bonus integer transports an actual
caller-owned contribution, default zero. concentration.save_contributions reads
the actual held mode grants before consuming next-save conditions and returns
(unsimplified modes, additional bonus); native damage and Speech-induced
concentration saves consume both. Its mode-only save_modes/save_mode adapters
disable numeric resolution while retaining next-mode consumption. With no
provider contribution, the caller's original save is unchanged.
Regulated Breathing supplies its real signed Key Ability save bonus for backlash;
end_effect supplies its source-qualified check bonus only for represented
support consequences of the selected condition. Unknown causes remain unknown.
All these callers use public support_values helpers and the same round receipt."""
