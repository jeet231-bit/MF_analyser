"""Sheet scope helpers: which sheets a set of sheets depends on, derived from formula text.

The interpreted model only knows sheets that were in scope, so deciding *what* to put in
scope needs a cheaper, model-free view: every ``Sheet!`` reference in every formula. The
closure is a fixed point over those references; it is how ``dashboard.config.json``'s
``sheetScope`` is derived and checked (an in-scope set must be upstream-closed, otherwise
out-of-scope sheets silently become external inputs).
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable

from app.parser.models import RawSheet, RawWorkbook

_STRING_LITERAL = re.compile(r'"(?:[^"]|"")*"')
_QUOTED_SHEET = re.compile(r"'((?:[^']|'')+)'!")
_BARE_SHEET = re.compile(r"(?<![A-Za-z0-9_.'\]])([A-Za-z_][A-Za-z0-9_.]*)!")

SheetLoader = Callable[[str], RawSheet]


def sheet_references(sheet: RawSheet) -> Counter[str]:
    """Count references from this sheet's formulas to other sheets (by name, self included)."""
    counts: Counter[str] = Counter()
    for formula in sheet.cells.formula:
        if not formula:
            continue
        body = _STRING_LITERAL.sub('""', formula)
        for m in _QUOTED_SHEET.finditer(body):
            counts[m.group(1).replace("''", "'")] += 1
        for m in _BARE_SHEET.finditer(body):
            counts[m.group(1)] += 1
    return counts


class ScopeClosure:
    def __init__(self, sheets: list[str], unresolved: list[str]) -> None:
        self.sheets = sheets
        self.unresolved = unresolved


def upstream_closure(meta: RawWorkbook, load_sheet: SheetLoader, seeds: list[str]) -> ScopeClosure:
    """Every sheet the seeds read, transitively, in workbook order (seeds included).

    Unknown seed names raise ``ValueError``; references to names that are not sheets
    (external workbooks, table names) are reported in ``unresolved`` rather than followed.
    """
    names = set(meta.sheet_names)
    unknown = [s for s in seeds if s not in names]
    if unknown:
        raise ValueError(f"sheets not in workbook: {unknown}")
    closure: set[str] = set(seeds)
    unresolved: set[str] = set()
    todo = list(seeds)
    while todo:
        name = todo.pop()
        for ref in sheet_references(load_sheet(name)):
            if ref not in names:
                unresolved.add(ref)
            elif ref not in closure:
                closure.add(ref)
                todo.append(ref)
    ordered = [s for s in meta.sheet_names if s in closure]
    return ScopeClosure(ordered, sorted(unresolved))


def missing_upstream(meta: RawWorkbook, load_sheet: SheetLoader, scope: list[str]) -> list[str]:
    """Sheets read by ``scope`` that are not in it (empty means the scope is upstream-closed)."""
    closure = upstream_closure(meta, load_sheet, scope)
    return [s for s in closure.sheets if s not in set(scope)]
