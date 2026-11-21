"""Persistence policy hooks (A2IMBUEMEN):
  persist_variants(info, technique) -> None or ordered list of {key, label, cp, rounds?}.
    Pure compile query. First provider owns the variants; no reply preserves the
    ordinary button, price and remaining-duration behavior. A key suffix names
    an extra paid variant; rounds measures its duration from the setting action.
  persist_cost(engine, actor, effect) -> None or nonnegative CP price.
    Pure quote shared by candidate eligibility and payment. First provider owns
    the quote; no reply uses the effect's base price.
  persist_paid(ctx, effect, paid) -> None.
    Strict transactional notification after payment and before detachment; errors
    unwind the transaction. No subscribers create no state or events. Existing
    copy ownership, expiry and cleanup remain authoritative."""
