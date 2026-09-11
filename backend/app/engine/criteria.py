"""Excel criteria strings (COUNTIF family) as vectorised predicates over Values."""

from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np

from app.engine.values import (
    BOOL,
    EMPTY,
    ERROR,
    NUMBER,
    TEXT,
    StringTable,
    Values,
    XlError,
    parse_number_text,
    round15,
)

_OPS = ("<>", "<=", ">=", "=", "<", ">")


@dataclass(frozen=True)
class Criterion:
    op: str
    is_number: bool
    number: float = 0.0
    text: str = ""  # casefolded
    pattern: re.Pattern[str] | None = None
    is_bool: bool = False
    is_error: XlError | None = None
    is_empty: bool = False


def _wildcard(text: str) -> re.Pattern[str] | None:
    if "*" not in text and "?" not in text and "~" not in text:
        return None
    out = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "~" and i + 1 < len(text):
            out.append(re.escape(text[i + 1]))
            i += 2
            continue
        out.append(".*" if ch == "*" else "." if ch == "?" else re.escape(ch))
        i += 1
    return re.compile("^" + "".join(out) + "$", re.IGNORECASE | re.DOTALL)


def parse_criterion(value: object) -> Criterion:
    """A criterion given as a Python scalar: number, bool, None, or string like '>=5', '<>--', 'a*'."""
    if value is None:
        return Criterion(op="=", is_number=False, is_empty=True)
    if isinstance(value, bool):
        return Criterion(op="=", is_number=False, is_bool=True, number=1.0 if value else 0.0)
    if isinstance(value, int | float):
        return Criterion(op="=", is_number=True, number=float(value))
    text = str(value)
    op = "="
    for candidate in _OPS:
        if text.startswith(candidate):
            op = candidate
            text = text[len(candidate) :]
            break
    if text == "" and op == "=":
        return Criterion(op="=", is_number=False, is_empty=True)
    if text == "" and op == "<>":
        return Criterion(op="<>", is_number=False, is_empty=True)
    err = XlError.from_text(text)
    if err is not None:
        return Criterion(op=op, is_number=False, is_error=err)
    upper = text.strip().upper()
    if upper in ("TRUE", "FALSE"):
        return Criterion(
            op=op, is_number=False, is_bool=True, number=1.0 if upper == "TRUE" else 0.0
        )
    num = parse_number_text(text)
    if num is not None:
        return Criterion(op=op, is_number=True, number=num)
    return Criterion(
        op=op,
        is_number=False,
        text=text.casefold(),
        pattern=_wildcard(text) if op in ("=", "<>") else None,
    )


def _apply(op: str, lhs: np.ndarray, rhs: float | str) -> np.ndarray:
    if op == "=":
        return lhs == rhs
    if op == "<>":
        return lhs != rhs
    if op == "<":
        return lhs < rhs
    if op == "<=":
        return lhs <= rhs
    if op == ">":
        return lhs > rhs
    return lhs >= rhs


def criterion_mask(
    values: Values, crit: Criterion, table: StringTable, rounded: np.ndarray | None = None
) -> np.ndarray:
    """Boolean array (values.shape): which cells satisfy the criterion, per Excel rules.

    ``rounded`` may carry ``round15(values.num)`` precomputed by a caller that evaluates many
    criteria against the same range.
    """
    kind = values.kind
    if crit.is_empty:
        if crit.op == "<>":
            return kind != EMPTY
        return kind == EMPTY
    if crit.is_error:
        m = (kind == ERROR) & (values.err == int(crit.is_error))
        return ~m if crit.op == "<>" else m
    if crit.is_bool:
        m = (kind == BOOL) & ((values.num != 0) == (crit.number != 0))
        return ~m if crit.op == "<>" else m
    if crit.is_number:
        numeric = kind == NUMBER
        nums = rounded if rounded is not None else round15(values.num)
        threshold = float(round15(crit.number))
        m = numeric & _apply(crit.op, nums, threshold)
        return ~(numeric & (nums == threshold)) if crit.op == "<>" else m
    # text criterion
    text = kind == TEXT
    if not text.any():
        return (
            np.ones(values.shape, dtype=bool)
            if crit.op == "<>"
            else np.zeros(values.shape, dtype=bool)
        )
    if crit.op in ("=", "<>"):
        if crit.pattern is not None:
            strings = table.decode(values.code[text])
            hit = np.array([bool(crit.pattern.match(s)) for s in strings], dtype=bool)
        else:
            fold = table.fold_array()
            target = table._folds.get(crit.text, -2)  # noqa: SLF001 - same package
            hit = fold[values.code[text]] == target
        m = np.zeros(values.shape, dtype=bool)
        m[text] = hit
        return ~m if crit.op == "<>" else m
    strings = table.decode(values.code[text])
    folded = np.array([s.casefold() for s in strings], dtype=object)
    m = np.zeros(values.shape, dtype=bool)
    m[text] = _apply(crit.op, folded, crit.text)
    return m
