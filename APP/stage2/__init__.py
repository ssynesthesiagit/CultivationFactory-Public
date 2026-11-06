"""Stage 2 package exports.

Keep the service import lazy so catalog compilation can consume the small
typed Insight authority helper without importing the full persistence stack
back through ``catalog.service``.
"""

__all__ = ["Stage2AdvancementService"]


def __getattr__(name: str):
    if name == "Stage2AdvancementService":
        from .service import Stage2AdvancementService

        return Stage2AdvancementService
    raise AttributeError(name)
