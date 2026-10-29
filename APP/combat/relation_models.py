"""Persisted, optional diplomacy data shared by engine and controller contexts."""
from typing import Literal

from pydantic import Field, model_validator

from .models import StrictModel

Relation = Literal['ALLY', 'ENEMY', 'NEUTRAL']
Opposition = Literal['GENUINE', 'STAGED', 'UNKNOWN']


class Relations(StrictModel):
    # Symmetric pairs, stored once with the smaller identifier first.
    teams: dict[str, dict[str, Relation]] = Field(default_factory=dict)
    actors: dict[str, dict[str, Relation]] = Field(default_factory=dict)
    # Owner/GM scene evidence, independent of team or diplomatic allegiance.
    opposition: dict[str, dict[str, Opposition]] = Field(default_factory=dict, exclude_if=lambda value: not value)

    @model_validator(mode='after')
    def canonical_pairs(self):
        for table in (self.teams, self.actors, self.opposition):
            if any(not left or not right or left >= right for left, row in table.items() for right in row):
                raise ValueError('Relation pairs must have distinct, sorted identifiers.')
        return self


class RelationChange(StrictModel):
    kind: Literal['TEAM_RELATION', 'ACTOR_RELATION', 'ACTOR_SIDE', 'SCENE_OPPOSITION']
    subject: str = Field(min_length=1, max_length=200)
    other: str = Field(min_length=1, max_length=200)
    relation: Relation | None = None
    opposition: Opposition | None = Field(default=None, exclude_if=lambda value: value is None)

    @model_validator(mode='after')
    def complete_change(self):
        if self.kind == 'SCENE_OPPOSITION':
            if self.opposition is None or self.relation is not None or self.subject == self.other:
                raise ValueError('Scene opposition needs two different creatures and GENUINE, STAGED or UNKNOWN evidence.')
            return self
        if self.opposition is not None:
            raise ValueError('Only a scene opposition command accepts opposition evidence.')
        if (self.kind == 'ACTOR_SIDE') != (self.relation is None):
            raise ValueError('A relation change needs a relation; a side change needs only a team.')
        if self.kind != 'ACTOR_SIDE' and self.subject == self.other:
            raise ValueError('Choose two different actors or teams.')
        return self
