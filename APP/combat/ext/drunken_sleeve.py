"""Sleeve, Bowl, and Boot remains a printed rider, pending an object-use seam.

When using Reeling Step, draw or pick up one unattended Tiny or Small mundane
object within reach as part of the same Bonus Action. Until the end of that
turn, use that object as an improvised weapon for Drunken Style talents only.
It must be plausibly manipulable with one hand, foot, sleeve, hip or shoulder.

The existing held-improvised condition grants ordinary attacks and every
sphere benefit without an ability-specific permission. Granting it here
would overgrant the talent; expiring possession would wrongly discard the
held object. No hook is registered until possession and scoped permission
can be represented separately. Ordinary object interactions remain intact.
"""

from . import effect


@effect("drunken_sleeve_grab")
def sleeve_grab(ctx, row):
    """Keep earlier saved action rows executable without granting broad permission."""
    ctx.rider("Sleeve, Bowl, and Boot: as part of Reeling Step's Bonus Action, you may pick up one unattended Tiny or Small "
              "mundane object within reach. Until this turn ends, you may use it as an improvised weapon for Drunken Style "
              "talents only. It must be something you can plausibly manipulate with one hand, foot, sleeve, hip, or shoulder. "
              "The GM resolves this object use; no general improvised-weapon permission is granted.")
