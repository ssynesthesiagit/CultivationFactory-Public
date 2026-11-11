"""cell_candidate_metadata(engine, actor, action, destination) -> None or exactly
{expected_damage: nonnegative int, hostiles_in_area: nonnegative int,
 empty_area: bool}. Pure, strict single-provider footprint estimates for free-cell
placement actions; no provider keeps the legacy empty-placement metadata.
This hook changes estimates only, never legality, geometry or recipients.
AI providers use candidate_knowledge.roster and the actual action footprint,
never hidden current positions. Substantial Phantasm consumes the public
figment.creation_cells preview."""
