"""Shared control ownership for check, rest, learning and activity providers.

Manual travel and an explicit Ask me plan retain player decisions. Autonomous
journey seats may select only options offered in their own visible menu.
"""


def autonomous(session, actor_id):
    actor = session.state['actors'][actor_id]
    return (actor['control_mode'] == 'LOCAL_AUTO'
            and actor['bundle'].get('reaction_plan',{}).get('mode') != 'ask')
