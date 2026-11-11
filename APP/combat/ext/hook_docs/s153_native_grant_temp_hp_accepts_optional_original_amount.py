"""Native _grant_temp_hp accepts optional original_amount and offer_cap integers.
typed temporary-HP producers retain the signed raw value for source-aware
selection and apply the printed cap after additions, before interception.
temp_hp_offers dispatches the public support-value provider separately from the
legacy positive-only temp_hp_offered_bonus hook, so a signed offer can qualify
without changing other providers' positive-offer gate. Typed _roll's optional
preserve_sign flag defaults false; HP/Temporary HP values preserve their raw
signed flat term before the ordinary grant/interception floor. Production compile
hooks seal support_method source snapshots on owned actions and passive/reaction
rows; runtime source membership requires those snapshots rather than raw labels."""
