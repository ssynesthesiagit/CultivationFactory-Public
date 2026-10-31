"""Keep mechanical path receipts out of player prose; no combat behavior."""
from . import hook


@hook('history_event_metadata')
def geometry_history(event, events):
    if (event.get('event_type') == 'PASSIVE_TRIGGERED'
            and (event.get('payload') or {}).get('checkpoint') == 'PACKET_GEOMETRY_COMMITTED'):
        return {'history_hidden': True}
