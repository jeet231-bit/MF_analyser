"""Excel function inventory: which functions a formula calls, and how often across a workbook.

The inventory bounds what the engine must support (CLAUDE.md, known constraints), so it must
be exact: string literals are stripped first so text such as ``"SUM("`` is never counted, and
``_xlfn.`` / ``_xlws.`` future-function prefixes are normalised away.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable

_STRING_LITERAL = re.compile(r'"(?:[^"]|"")*"')
_FUNCTION_CALL = re.compile(r"(?<![A-Za-z0-9_.!'\]])([A-Za-z_][A-Za-z0-9_.]*)\s*\(")
_PREFIXES = ("_xlfn.", "_xlws.", "_xlpm.")


def normalise_function_name(raw: str) -> str:
    name = raw
    changed = True
    while changed:
        changed = False
        for prefix in _PREFIXES:
            if name.lower().startswith(prefix):
                name = name[len(prefix) :]
                changed = True
    return name.upper()


def functions_in_formula(formula: str) -> list[str]:
    """Function names called by one formula, in order of appearance (duplicates kept)."""
    body = _STRING_LITERAL.sub('""', formula)
    return [normalise_function_name(m.group(1)) for m in _FUNCTION_CALL.finditer(body)]


class FunctionInventory:
    """Counts formulas per function (a formula calling SUM twice counts once for SUM)."""

    def __init__(self) -> None:
        self._counts: Counter[str] = Counter()

    def add_formula(self, formula: str) -> None:
        for name in set(functions_in_formula(formula)):
            self._counts[name] += 1

    def add_formulas(self, formulas: Iterable[str]) -> None:
        for f in formulas:
            self.add_formula(f)

    def merge(self, other: FunctionInventory) -> None:
        self._counts.update(other._counts)

    def as_dict(self) -> dict[str, int]:
        return dict(sorted(self._counts.items(), key=lambda kv: (-kv[1], kv[0])))
