"""Tokenizer for Excel formulas (the text after the leading '=')."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from openpyxl.utils import column_index_from_string

from app.model.formula.refs import MAX_COL, MAX_ROW

TokenKind = Literal[
    "number", "string", "bool", "error", "ref", "external", "name", "sref", "func", "op", "eof"
]  # fmt: skip


@dataclass(frozen=True)
class Token:
    kind: TokenKind
    text: str
    pos: int
    sheet: str | None = None  # for ref / name: the sheet prefix, unquoted


class TokenizeError(ValueError):
    def __init__(self, message: str, pos: int) -> None:
        super().__init__(f"{message} at position {pos}")
        self.pos = pos


_SHEET_PREFIX = r"(?:'(?:[^']|'')+'|[A-Za-z0-9_.À-￿]+)!"
_CELL = r"\$?[A-Za-z]{1,3}\$?\d+"
_REF_BODY = rf"(?:{_CELL}(?::{_CELL})?|\$?[A-Za-z]{{1,3}}:\$?[A-Za-z]{{1,3}}|\$?\d+:\$?\d+)"

WS = re.compile(r"\s+")
STRING = re.compile(r'"(?:[^"]|"")*"')
NUMBER = re.compile(r"(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?")
ERROR = re.compile(r"#(?:N/A|DIV/0!|VALUE!|REF!|NAME\?|NUM!|NULL!|SPILL!|CALC!|GETTING_DATA)")
EXTERNAL = re.compile(rf"(?:'\[[^\]]+\][^']*'|\[[^\]]+\][A-Za-z0-9_.]*)!{_REF_BODY}")
REF = re.compile(rf"(?P<sheet>{_SHEET_PREFIX})?(?P<body>{_REF_BODY})(?![A-Za-z0-9_.(\[])")
FUNC = re.compile(r"[A-Za-z_][A-Za-z0-9_.]*(?=\s*\()")
SREF = re.compile(r"[A-Za-z_][A-Za-z0-9_.]*(?=\[)|(?=\[)")
NAME = re.compile(rf"(?P<sheet>{_SHEET_PREFIX})?(?P<name>[A-Za-z_\\][A-Za-z0-9_.\\?]*)")
OP = re.compile(r"<=|>=|<>|[-+*/^&=<>%:,;(){}]")


def _unquote_sheet(prefix: str | None) -> str | None:
    if not prefix:
        return None
    name = prefix[:-1]  # drop '!'
    if name.startswith("'") and name.endswith("'"):
        name = name[1:-1].replace("''", "'")
    return name


def _valid_ref(body: str) -> bool:
    """Reject identifiers that merely look like references (e.g. ZZZ1 beyond column XFD)."""
    for part in body.split(":"):
        letters = "".join(ch for ch in part if ch.isalpha())
        digits = "".join(ch for ch in part if ch.isdigit())
        if letters and column_index_from_string(letters.upper()) > MAX_COL:
            return False
        if digits and int(digits) > MAX_ROW:
            return False
    return True


def _scan_brackets(text: str, start: int) -> int:
    depth = 0
    i = start
    while i < len(text):
        ch = text[i]
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    raise TokenizeError("unbalanced structured reference", start)


def tokenize(body: str) -> list[Token]:
    tokens: list[Token] = []
    i = 0
    n = len(body)
    while i < n:
        if m := WS.match(body, i):
            i = m.end()
            continue
        if m := STRING.match(body, i):
            tokens.append(Token("string", m.group(0), i))
        elif m := ERROR.match(body, i):
            tokens.append(Token("error", m.group(0), i))
        elif m := EXTERNAL.match(body, i):
            tokens.append(Token("external", m.group(0), i))
        elif (m := REF.match(body, i)) and _valid_ref(m.group("body")):
            tokens.append(Token("ref", m.group("body"), i, _unquote_sheet(m.group("sheet"))))
        elif m := NUMBER.match(body, i):
            tokens.append(Token("number", m.group(0), i))
        elif m := FUNC.match(body, i):
            tokens.append(Token("func", m.group(0), i))
        elif (m := SREF.match(body, i)) and m.end() < n and body[m.end()] == "[":
            end = _scan_brackets(body, m.end())
            tokens.append(Token("sref", body[i:end], i))
            i = end
            continue
        elif m := NAME.match(body, i):
            name = m.group("name")
            sheet = _unquote_sheet(m.group("sheet"))
            if sheet is None and name.upper() in ("TRUE", "FALSE"):
                tokens.append(Token("bool", name.upper(), i))
            else:
                tokens.append(Token("name", name, i, sheet))
        elif m := OP.match(body, i):
            tokens.append(Token("op", m.group(0), i))
        else:
            raise TokenizeError(f"unexpected character {body[i]!r}", i)
        i = m.end()
    tokens.append(Token("eof", "", n))
    return tokens
