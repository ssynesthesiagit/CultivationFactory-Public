"""Public roster availability, separate from immutable historical replay content.

CombatService and the saved-team picker share this policy. Historical engines and
saved fights deliberately retain their original actor definitions.
"""
from .gate2_runtime_content import LEE, LING

RETIRED_FIGHTERS = frozenset({LEE, LING})
PRACTICE_ENCOUNTER_ID = 'encounter:practice.duel'
RETIRED_MESSAGE = 'Ling Qi and Lee Jia are retired sample fighters. Choose a finished character for a new fight. Existing saved fights can still be opened.'


def retired(actor_id: str) -> bool:
    return str(actor_id).removeprefix('character_mapping:') in RETIRED_FIGHTERS


def public_catalog(payload: dict) -> dict:
    """Filter a caller-owned catalog copy; never alter the historical catalog."""
    payload['projections'] = [row for row in payload['projections'] if not retired(row['runtime_entity_id'])]
    for battlefield in payload['battlefields']:
        battlefield['starting_positions'] = {key: value for key, value in battlefield['starting_positions'].items() if not retired(key)}
    for index, team in enumerate(payload['teams'], 1):
        team['participant_ids'] = [aid for aid in team['participant_ids'] if not retired(aid)]
        team['display_name'] = f'Side {index}'
    for row in payload['projections']:
        row['team_display_name'] = next(team['display_name'] for team in payload['teams'] if team['team_id'] == row['team_id'])
    for encounter in payload['encounters']:
        encounter['stable_id'] = PRACTICE_ENCOUNTER_ID
        encounter['display_name'] = 'Practice duel — An Eui and Bai Meizhen'
        for team in encounter['teams']:
            team['participant_ids'] = [aid for aid in team['participant_ids'] if not retired(aid)]
    payload['known_limitations'] = [line for line in payload['known_limitations'] if '2v2' not in line]
    return payload


def preset_available(preset: dict) -> bool:
    teams = preset.get('teams')
    if not isinstance(teams, list):
        return True  # structural validation belongs to the preset store
    return not any(retired(member.get('pid', '')) for side in teams if isinstance(side, list)
                   for member in side if isinstance(member, dict))
