"""Elephant King's Trampling Advance uses pass_through, candidate_allowed and
movement_attempt. Passage is a pure observed query after a committed straight
20-foot run. It never grants allied or unseen creature passage. Actual continuing
entry resolves nearest enemies first and records a turn-scoped affected roster.
Nearest outside placements require normal footprint/wall legality and a physical
route. movement_paths.resolve owns forced defenses/reactions, movement records,
landing hazards and interruptions; a blocked displacement stops the King's move.
No King state means no permission or other behavior change."""
