"""Meld upgrade admission (existing candidate_allowed hook): actions with
meld_runtime=2 may declare parameters.meld_upgrades, containing persistent
(bool), enhanced_darkvision (bool) and temporary_hp (offered integer pool).
docket_senses compares these with the recipient's current grant/pool so AI
seats can renew a depleted pool or upgrade Concentration to persistence.
Absent metadata retains legacy suffix detection; manual renewals stay legal.
ai_restraint defers its same-Concentration veto for recipient-aware Melds to
this admission, so the built-in AI context preserves the admitted upgrades.
No state is changed by this query and non-Meld actions are unaffected."""
