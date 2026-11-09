"""Public concentration helpers (A2IMBUEMEN):
  concentration.is_recipient_effect(row) distinguishes bearer grants from
    activation bookkeeping; hidden alone does not imply bookkeeping.
  concentration.end_recipient(engine, caster, source, bearer, reason,
    applied_sequence=None) removes only that bearer's activation-owned grants
    through events, releasing live/held/detached tracking after the last bearer.
    The optional grant sequence selects a copy. Sibling recipients and newer
    copies remain; no saved model fields or ability identifiers are introduced."""
