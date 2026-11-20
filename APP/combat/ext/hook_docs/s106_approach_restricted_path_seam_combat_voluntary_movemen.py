"""Approach-restricted path seam (combat/voluntary_movement.py, combat/rules/typed_conditions.json,
combat/ext/approach_restriction.py):
  any condition whose engine rule carries no_approach keeps its holder from taking a willing step
  toward the creature that applied it -- Frightened, and a printed "cannot willingly move closer to
  you" (Name-Striking Tone's Kept at Distance, Spear's World-Transfixing Point, Thread's Sever the
  Battle Line, Daemonic Cultivation's Consume Fear). The set is read from the shared rules table, so
  a new ability needs the rule and nothing in code. The sight exception belongs to the rule, not to
  the query: a rule that also carries no_approach_requires_source_visible (Frightened's printed "It
  can't willingly take a step closer while that source is visible") bites only while that creature is
  visible; a rule without it binds from anywhere. fear_sources returns every such source,
  unconditional_sources the subset that needs no sight. Forced movement never uses this query;
  a voluntary teleport does, through the engine's own teleport_check seam
  (approach_restriction), and only for the unconditional rules -- Frightened's printed rule is about
  steps, so its teleports stay legal. A creature with no such condition keeps every step and every
  teleport it had before."""
