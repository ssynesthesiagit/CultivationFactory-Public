"""Deterministic work budgets for MASTERMIND decisions.

A budget counts native work checkpoints, never elapsed time. Each checkpoint
consumes one unit. A slow or loaded host therefore walks the same checkpoints
in the same order and reaches the same decision record from the same state.
Wall-clock time is diagnostic only and must never gate a decision input.
"""


class WorkBudget:
    """Shared, finite checkpoint allowance. budget=None means unbounded."""

    __slots__ = ("left", "spent")

    def __init__(self, steps):
        self.left = max(0, int(steps))
        self.spent = 0

    def open(self):
        """True while work remains. Does not consume a checkpoint."""
        return self.left > 0

    def step(self):
        """Consume one checkpoint; False once the allowance is exhausted."""
        if self.left <= 0:
            return False
        self.left -= 1
        self.spent += 1
        return True
