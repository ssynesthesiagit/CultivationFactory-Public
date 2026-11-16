"""Plug-in hook points for sphere and talent mechanics (owner 2026-09-28: "we need to automate every aspect before another
playtest", several workers at once). A module in combat/ext/ registers what it adds with the decorators below; every module
in the package is imported once, the first time a hook is asked for, in name order."""
