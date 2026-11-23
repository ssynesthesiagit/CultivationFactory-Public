"""Mutual-knockout defeat query.

self_recovery(engine, actor) -> bool | None is a pure query for a downed
creature's own in-combat ability to revive, heal or stand without another
creature's help. True keeps its side live; None is default-inert. A natural 20
death save is not self-recovery. Ability costs, conditions and timing remain
the provider's responsibility. Only fights using the 2024 dying rules consult
this query; other fights retain their active/inactive defeat rules.
"""
