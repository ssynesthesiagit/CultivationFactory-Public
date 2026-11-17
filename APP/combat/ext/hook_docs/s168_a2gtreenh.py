"""General attack scope (A2GTREENH):
attack_resolution_scope(engine, actor, target, spec, intent) -> context manager
or None. Pure scope factory around one native strike, including declaration,
primary damage and hit notifications. Managers unwind on pause/error; nested
strikes have nested scopes. No provider is inert. A mandatory hit aftermath may
use native victory_deferred() so the primary packet and mandatory retaliation
settle before victory is declared. Typed attacks use effect_resolution_scope
for the enclosing hit riders; the nested native scope composes with it. Optional
reactions still own all ordinary eligibility and payment. No saved field or
ability-specific core branch is introduced. Treasure armor uses hit_snapshot to
freeze hit-time wearer/range/numbers and hit_final for mandatory Thorns damage,
including a killing hit, without rewriting an already declared terminal result."""
