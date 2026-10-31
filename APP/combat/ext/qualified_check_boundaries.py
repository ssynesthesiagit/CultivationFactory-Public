"""Compilation boundaries shared by Air and Drunken Style check consumers.

Their owned passive rows carry manual_handling when real check producers are
still missing. Preserve the explanation in the ordinary compiler notes; the
keeps_compiling marker also retains the native not-automated passive listing.
This publishes no action, roll mode or hidden information.
"""
from . import hook


@hook('compile_bundle')
def partial_check_notes(bundle, info):
    notes = [row['manual_handling'] for row in bundle.get('typed_passives', ())
             if row.get('manual_handling')]
    if not notes:
        return None
    diagnostics = dict(bundle.get('diagnostics') or {})
    diagnostics['notes'] = list(dict.fromkeys([*diagnostics.get('notes', ()), *notes]))
    return {**bundle, 'diagnostics': diagnostics}
