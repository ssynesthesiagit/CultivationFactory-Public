"""Historical rule-arena fixture writer used by arena and placement regressions.

Only test writers expose retired geometry to seal old-style fixtures. Production
services always reject these ids for new fights; readers use sealed documents.
"""
from combat.gate5_service import CombatService


class HistoricalArenaWriter(CombatService):
    def factory_arenas(self, *, include_retired=False):
        return super().factory_arenas(include_retired=True)
