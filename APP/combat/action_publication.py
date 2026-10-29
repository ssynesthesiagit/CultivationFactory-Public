"""Compiler publication checks shared by grant headings and empty action rows.

This module describes whether an action has something to resolve; it does not
implement abilities, infer effects from prose, or change execution.
"""
import re


def grant_heading(record, text, mechanics):
    """A grant-only parent with separately typed child headings is not an action."""
    if record.get('effects') or record.get('riders') or record.get('options'):
        return False
    parts = re.split(r'^####\s+', text or '', flags=re.MULTILINE)
    if len(parts) < 2:
        return False
    intro = re.sub(r'^###\s+[^\n]+\n?', '', parts[0]).strip()
    if not re.fullmatch(r'When you learn [^\n]+, gain [^\n]+\.', intro):
        return False
    names = {row.get('name') for key, row in mechanics.items()
             if key != record.get('mechanic_id') and row.get('sphere_id') == record.get('sphere_id')}
    children = [part.splitlines()[0].strip() for part in parts[1:]]
    return all(name in names and name in intro for name in children)


def has_resolution(action, statuses, info):
    """Keep executable rows, reviewed manual rules, and explicit plug-in claims.

The compiler calls this after all action transforms. Automatically copied
gm_text alone is not a claim: every empty row used to receive that text.
"""
    if action.resolution_kind != 'TYPED':
        return True
    typed = action.parameters.get('typed') or {}
    if typed.get('effects') or typed.get('weapon') or typed.get('zone_spec') or typed.get('riders'):
        return True
    source = typed.get('option_of') or typed.get('source')
    if action.source_definition_id in info.get('implemented_action_ids', ()):
        return True
    if (statuses.get(source) or {}).get('status') == 'table':
        return True
    if action.parameters.get('gm_only') or action.parameters.get('manual'):
        return True
    from . import ext
    return any(reply is True for reply in ext.run_strict('empty_action_implemented', action, info))
