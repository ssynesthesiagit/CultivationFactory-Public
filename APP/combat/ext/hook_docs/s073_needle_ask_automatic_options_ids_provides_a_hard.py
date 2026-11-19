"""needle.ask(..., automatic_options=ids) provides a hard subset for automatic
answers and no-provider fallbacks. Manual players retain the full printed
option set. The choice_options provider narrows automatic controllers' legal
options, bounds, and preferences to that subset; MANUAL, SUGGESTED, and
MANUAL_AI_BRIDGE participants keep the printed player choice. An empty subset
declines for automatic controllers.
Absent this argument preserves existing choice behavior. extra_targets rows
may declare automatic_recipients='enemies', 'allies', or 'allies_and_self'; the
subset is computed only after ordinary range/perception eligibility. It is a
legal bound, not a side preference. Hundred-Line Weaving uses enemies and also
requires the chooser to perceive each candidate. Printed all-creature effects
such as Heaven-Net continue to resolve their explicit full area roster."""
