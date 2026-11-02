"""Empty Bowl Soul Anchor Foundation resource generation (owner 2026-09-28 automation push, Wen Xue's worker).

Gather Empty Bowl Mark ("Once per round after you resolve a Fixed Empty Bowl Scope technique/effect that
feeds, heals, stabilizes, protects, comforts, or answers real need ... gain 1 Empty Bowl Mark") is a narrative
trigger the table cannot judge in general (a GM call on whether a given scene counts as "real need"). As a
text-grounded stand-in, this generates the Mark after Wen Xue's own already-typed healing/protective support
actions resolve on an ally or herself: Healing Hymn (heals), Dawn Ward and Rhythmic Guard (protect by reducing
incoming damage), Harmonizing Breath and Mercy of Morning (comfort -- end a fear/charm response or grant
Temporary HP). combat/pressure.py's generate() (Foundation resource triggers) does the actual gain, capped at
1 and once a round, via combat/rules/feature_blocks.d/wenxue.json's "generate" row for this feature with the
custom "on" reason "wenxue_empty_bowl_support" (pressure.py's own vocabulary -- damaged/hit_aggressor/
pressure_save -- has no matching reason, so this plug-in supplies its own and calls generate() directly rather
than editing pressure.py's shared call sites).
"""

from __future__ import annotations

from typing import Any

from . import hook

QUALIFYING_SUPPORT = {
    "tianxia.talent.music.healing_hymn",
    "tianxia.talent.radiance.dawn_ward",
    "tianxia.talent.music.rhythmic_guard",
    "tianxia.talent.music.harmonizing_breath",
    "tianxia.talent.radiance.mercy_of_morning",
}


@hook("technique_used")
def gather_empty_bowl_mark(ctx: Any) -> None:
    if ctx.typed.get("source") not in QUALIFYING_SUPPORT:
        return
    from .. import pressure

    pressure.generate(ctx.engine, ctx.actor, "wenxue_empty_bowl_support")
