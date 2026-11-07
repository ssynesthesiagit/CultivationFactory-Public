"""Private source-authoring transport for Glass Heart and Read the Thread.

Hide both the source record and its native authoring-command envelope. The
owner's journal retains them for replay; neither is a creature's gameplay action
or a public observation. No table-fact events means no display change.
"""
from . import hook
from ..table_facts import SOURCE


@hook('history_event_metadata')
def owner_source_history(event, events):
    if event.get('source_definition_id') == SOURCE:
        return {'history_hidden': 1}
    return None
