"""ability_check_hazards(engine, actor, ability, skill, hazards) -> str|None adds
an opt-in named hazard such as DISADVANTAGE to that exact ability/skill check.
Return None when the actor, check, or hazard is outside the provider's rule;
providers must be pure and leave unrelated checks unchanged. Thread Heaven-Net
uses it only for grounded hostile escape checks made with Acrobatics."""
