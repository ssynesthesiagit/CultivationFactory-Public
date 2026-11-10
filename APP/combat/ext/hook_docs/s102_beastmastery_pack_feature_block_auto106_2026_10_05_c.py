"""Beastmastery pack feature block (AUTO106 2026-10-05): combat/ext/beastmastery_pack.py reads the feature_blocks.d block
  "beastmastery_pack" (kinds "procession", "encirclement", "sovereign_pack_mind") it compiles through the ordinary
  compile_block hook. Ownership alone grants no active Action benefit.
  Sovereign Pack Mind's paid Bonus Action creates a native one-minute condition with data.choice_owner=1,
  exposing its manual owner's decisions to the service's AI-step probe only while active; d20_bonus then asks the owner
  through needle.ask before adding Proficiency Bonus to a present same-side Tamer/Rider Beast Ally's roll within
  120 feet. Only acceptance spends the integer _round_sovereign_pack_mind receipt; AI owners decide automatically.
  Without both the owned row and activation condition it is inert, including old saved bundles. The natural die
  and roll mode are unchanged. Procession's undefined fear resistance remains a GM reminder. Encirclement uses the documented per-reactor disengage_protection hook,
  a per-target first-hit round receipt, and chosen native granted movement; other enemies retain Disengage protection."""
