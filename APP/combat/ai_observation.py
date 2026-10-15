"""Personal, immutable inputs for analytic movement evaluation.

Used by ext.ai_movement and the menu destination provider. Opponents expose
only personally located positions/names and uncertainty, never HP, defenses,
resources or features. Journal receipts preserve personal memory on reload.
Unknown terrain and incomplete area boundaries remain explicitly unknown.
"""
from typing import Literal
from pydantic import BaseModel, ConfigDict


class FrozenFrame(BaseModel):
    model_config = ConfigDict(frozen=True, extra='forbid')


class KnownCreature(FrozenFrame):
    entity_id: str
    name: str
    position: tuple[int, int, int]
    observed_sequence: int
    mode: Literal['DIRECT', 'LAST_OBSERVED']
    relation: str = 'UNKNOWN'


class KnownSquare(FrozenFrame):
    position: tuple[int, int, int]
    known: bool
    cover: bool = False
    difficult: bool = False
    objective: bool = False
    hazard: bool = False

    def description(self):
        x, y, z = self.position
        facts = []
        if not self.known:
            facts.append('terrain unknown')
        else:
            if self.cover:
                facts.append('cover terrain; protection depends on the attack direction')
            if self.difficult:
                facts.append('difficult terrain costs extra movement')
            if self.objective:
                facts.append('observed objective')
            if self.hazard:
                facts.append('observed hazardous terrain')
            if not facts:
                facts.append('observed open terrain')
        return f'Square ({x}, {y}), {z * 5} feet high: ' + '; '.join(facts) + '.'


class ObservedHarm(FrozenFrame):
    position: tuple[int, int, int]
    damage: int
    sequence: int
    own_turn: int = 0
    # Empty means the boundary is unknown, not an empty/safe area.
    cells: tuple[tuple[int, int, int], ...] = ()
    complete_boundary: bool = False


class OwnKnowledgeFrame(FrozenFrame):
    version: int = 1
    actor_id: str
    # Knowledge revision deliberately excludes global state_version/seed.
    revision: str
    position: tuple[int, int, int]
    hp: int
    maximum_hp: int
    movement_ft: int
    own_turn: int = 0
    resources: tuple[tuple[str, int], ...]
    abilities: tuple[str, ...]
    goal: str = ''
    creatures: tuple[KnownCreature, ...] = ()
    squares: tuple[KnownSquare, ...] = ()
    harms: tuple[ObservedHarm, ...] = ()
    # Own native occupied volume, relative to the anchor. Pure movement
    # evaluators/menu providers translate it without reading engine truth.
    footprint_offsets: tuple[tuple[int, int, int], ...] = ((0, 0, 0),)

    def occupied_at(self, anchor):
        """Translate this creature's known volume to a proposed anchor."""
        return tuple(tuple(anchor[i] + offset[i] for i in range(3))
                     for offset in self.footprint_offsets)


def point(position):
    return (position.x, position.y, position.z)


def goal_from_sheet(sheet):
    """Existing chosen-sphere Dao plus authored I Ching response; no playbooks.

    This pure helper is also available to EMBEDMENU's sheet goal reader. It
    does not infer mechanical authority from guidance or call an LLM.
    """
    from factory_authoring.sphere_dao import character_dao, sheet_sphere_talents
    dao = character_dao(sheet_sphere_talents(sheet)) or {}
    surface = ((sheet.get('surfaces') or {}).get('dao_i_ching') or {}).get('data') or {}
    guidance = (sheet.get('dao_iching') or sheet.get('dao_i_ching') or
                (sheet.get('stats') or {}).get('dao_i_ching') or surface)
    if not isinstance(guidance, dict):
        guidance = {}
    guidance = guidance.get('dao_i_ching') or guidance
    if not isinstance(guidance, dict):
        guidance = {}
    parts = []
    def add(value):
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
        elif isinstance(value, (tuple, list)):
            for item in value:
                add(item)
        elif isinstance(value, dict):
            for key in ('name', 'image', 'meaning', 'core_theme', 'principles',
                        'reality_principle', 'change_rule', 'tactical_expression',
                        'roleplay_expression', 'strengths', 'risks'):
                add(value.get(key))
    add(dao.get('primary_sphere'))
    add(dao.get('dao_verbs'))
    for layer in dao.get('layers', ()):
        add(layer)
    add(dao.get('hexagram'))
    for posture in (dao.get('posture') or {}).values():
        add(posture)
    add(guidance.get('dao') or sheet.get('dao'))
    add(guidance.get('i_ching') or guidance.get('iching') or sheet.get('i_ching'))
    return '; '.join(dict.fromkeys(parts))
