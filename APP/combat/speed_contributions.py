"""Speed-hook provenance shared by Afflictions, Iron Fist, mounts and movement diagnostics.

An int-compatible result keeps mechanical consumers unchanged. Its transient
sources are (source ID, readable name, signed feet) tuples, never saved state.
"""


class SpeedContribution(int):
    def __new__(cls, sources):
        sources = tuple(sources)
        result = super().__new__(cls, sum(delta for _, _, delta in sources))
        result.sources = sources
        return result
