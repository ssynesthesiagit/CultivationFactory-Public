"""General observer/sound queries (A2GQISUB10), default inert and pure:
zone_obscuration_ignored(engine, zone, viewer, seen) -> None/bool. Any True
removes only that zone's heavy obscurement or obscuring-wall contribution
for this ordered observer pair. It does not remove physical LOS/LoE barriers,
creature conditions, other areas or the reverse observer's contributions.
sound_path_allowed(engine, speaker, listener, source) -> None/bool. Any False
rejects ordinary hearing of this speaker. speech.can_hear_from first respects
the listener's Deafened rules, then combines providers. Recipient admission,
typed areas, generic reactions and area previews share this helper. Neither
query mutates state, consumes usage or changes damage rules. Invalid replies
fail transactionally. Mantra of Silence supplies a concentration-linked zone
with bounded exemptions and holder-next-start relief; it leaves Thunder intact.
"""
