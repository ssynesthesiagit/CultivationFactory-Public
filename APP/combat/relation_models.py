"""Persisted, optional diplomacy data shared by engine and controller contexts."""
from typing import Literal

from pydantic import Field, model_validator

from .models import StrictModel

Relation = Literal['ALLY', 'ENEMY', 'NEUTRAL']


class Relations(StrictModel):
    # Symmetric pairs, stored once with the smaller identifier first.
    teams: dict[str, dict[str, Relation]] = Field(default_factory=dict)
    actors: dict[str, dict[str, Relation]] = Field(default_factory=dict)

    @model_validator(mode='after')
    def canonical_pairs(self):
        for table in (self.teams, self.actors):
            if any(not left or not right or left >= right for left, row in table.items() for right in row):
                raise ValueError('Relation pairs must have distinct, sorted identifiers.')
        return self


class RelationChange(StrictModel):
    kind: Literal['TEAM_RELATION', 'ACTOR_RELATION', 'ACTOR_SIDE']
    subject: str = Field(min_length=1, max_length=200)
    other: str = Field(min_length=1, max_length=200)
    relation: Relation | None = None

    @model_validator(mode='after')
    def complete_change(self):
        if (self.kind == 'ACTOR_SIDE') != (self.relation is None):
            raise ValueError('A relation change needs a relation; a side change needs only a team.')
        if self.kind != 'ACTOR_SIDE' and self.subject == self.other:
            raise ValueError('Choose two different actors or teams.')
        return self
