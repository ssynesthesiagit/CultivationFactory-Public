from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable

_SEMVER = re.compile(
    r"^(?P<major>0|[1-9][0-9]*)\.(?P<minor>0|[1-9][0-9]*)\.(?P<patch>0|[1-9][0-9]*)"
    r"(?:-(?P<prerelease>[0-9A-Za-z.-]+))?(?:\+(?P<build>[0-9A-Za-z.-]+))?$"
)
_COMPARATOR = re.compile(r"^(>=|<=|>|<|==|=)?\s*(.+)$")


@dataclass(frozen=True, order=True)
class Version:
    major: int
    minor: int
    patch: int
    prerelease: tuple[str, ...] = ()

    @classmethod
    def parse(cls, text: str) -> "Version":
        if not isinstance(text, str):
            raise ValueError(f"invalid semantic version: {text!r}")
        match = _SEMVER.fullmatch(text.strip())
        if not match:
            raise ValueError(f"invalid semantic version: {text!r}")
        pre = tuple((match.group("prerelease") or "").split(".")) if match.group("prerelease") else ()
        return cls(int(match.group("major")), int(match.group("minor")), int(match.group("patch")), pre)

    def precedence_key(self) -> tuple[object, ...]:
        # Stable and adequate for compatibility checks used by this candidate tool.
        if not self.prerelease:
            return (self.major, self.minor, self.patch, 1, ())
        normalized: list[tuple[int, object]] = []
        for part in self.prerelease:
            normalized.append((0, int(part)) if part.isdigit() else (1, part))
        return (self.major, self.minor, self.patch, 0, tuple(normalized))


def _compare(left: Version, operator: str, right: Version) -> bool:
    a, b = left.precedence_key(), right.precedence_key()
    if operator in ("", "=", "=="):
        return a == b
    if operator == ">=":
        return a >= b
    if operator == "<=":
        return a <= b
    if operator == ">":
        return a > b
    if operator == "<":
        return a < b
    raise ValueError(operator)


def validate_range(expression: str) -> None:
    if not isinstance(expression, str) or not expression.strip():
        raise ValueError("version range must be a non-empty string")
    text = expression.strip()
    if text.startswith("^"):
        Version.parse(text[1:])
        return
    if text.startswith("~"):
        Version.parse(text[1:])
        return
    for component in [part.strip() for part in text.split(",")]:
        if not component:
            raise ValueError(f"invalid empty version-range component in {expression!r}")
        match = _COMPARATOR.fullmatch(component)
        if not match:
            raise ValueError(f"invalid version-range component: {component!r}")
        Version.parse(match.group(2))


def satisfies(version: str, expression: str) -> bool:
    validate_range(expression)
    current = Version.parse(version)
    text = expression.strip()
    if text.startswith("^"):
        base = Version.parse(text[1:])
        if base.major > 0:
            upper = Version(base.major + 1, 0, 0)
        elif base.minor > 0:
            upper = Version(0, base.minor + 1, 0)
        else:
            upper = Version(0, 0, base.patch + 1)
        return _compare(current, ">=", base) and _compare(current, "<", upper)
    if text.startswith("~"):
        base = Version.parse(text[1:])
        upper = Version(base.major, base.minor + 1, 0)
        return _compare(current, ">=", base) and _compare(current, "<", upper)
    components = [part.strip() for part in text.split(",")]
    return all(
        _compare(current, (_COMPARATOR.fullmatch(component).group(1) or ""), Version.parse(_COMPARATOR.fullmatch(component).group(2)))
        for component in components
    )


def first_unsatisfied(version: str, expressions: Iterable[str]) -> str | None:
    for expression in expressions:
        if not satisfies(version, expression):
            return expression
    return None
