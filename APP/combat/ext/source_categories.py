"""Literal printed descriptors shared by action compilation and pressure readers.

Consumers: Returning Field saves/checks and repeats. Unknown descriptors remain
unknown. A source's name, sphere, appearance or actor's other abilities never
supplies a category. Snapshots survive bundle persistence and mechanical replay.
"""
import hashlib
import re
from . import hook


@hook('compile_action')
def capture(action, info):
    from ..rule_help import printed_rule_text
    typed = (action.parameters or {}).get('typed') or {}
    source = typed.get('source')
    if not source or source not in info['mechanics']:
        return None
    text = printed_rule_text(source)
    heading = text.split('\n', 1)[0]
    match = re.match(r'#+\s*.+?\s+-\s+(.+)$', heading)
    if not match:
        return None
    tags = [tag.strip().lower() for tag in match[1].split(',') if tag.strip()]
    return action.model_copy(update={'parameters': {**action.parameters, 'typed': {
        **typed, 'source_categories': tags,
        'source_decoded_sha256': hashlib.sha256(text.encode('utf-8')).hexdigest()}}})


def categories(action):
    """Read sealed descriptors only; missing/legacy snapshots stay unclassified."""
    typed = (getattr(action, 'parameters', None) or {}).get('typed') or {}
    return tuple(typed.get('source_categories') or ()) if typed.get('source_decoded_sha256') else ()
