"""Set the shared password: writes MFA_AUTH_PASSWORD_HASH (and MFA_AUTH_SECRET when absent) into
the config file. Restart the service afterwards.

    python -m app.tools.set_password [--config-file C:\\MFAnalyser\\config.env] [--stdin]
"""

from __future__ import annotations

import argparse
import getpass
import secrets
import sys
from pathlib import Path

from app.auth import hash_password
from app.config import DEFAULT_CONFIG_FILE

MIN_LENGTH = 8


def upsert(path: Path, values: dict[str, str]) -> None:
    """Replace or append ``KEY=value`` lines, keeping every other line as it is."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    done: set[str] = set()
    out: list[str] = []
    for line in lines:
        key = line.split("=", 1)[0].strip()
        if key in values:
            out.append(f"{key}={values[key]}")
            done.add(key)
        else:
            out.append(line)
    for key, value in values.items():
        if key not in done:
            out.append(f"{key}={value}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def current(path: Path, key: str) -> str | None:
    if not path.exists():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        k, sep, v = line.partition("=")
        if sep and k.strip() == key and v.strip():
            return v.strip()
    return None


def read_stdin_line() -> str:
    """One line from stdin without the newline or a UTF-8 BOM (PowerShell pipes emit one)."""
    buffer = getattr(sys.stdin, "buffer", None)
    if buffer is not None:
        line = buffer.readline().decode("utf-8-sig")
    else:
        line = sys.stdin.readline()
    return line.lstrip("﻿").rstrip("\r\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Set the MF Analyser shared password.")
    parser.add_argument("--config-file", type=Path, default=DEFAULT_CONFIG_FILE)
    parser.add_argument(
        "--stdin", action="store_true", help="read the password from stdin (installer)"
    )
    args = parser.parse_args(argv)
    if args.stdin:
        password = read_stdin_line()
    else:
        password = getpass.getpass("New shared password: ")
        if password != getpass.getpass("Repeat it: "):
            print("The two entries differ; nothing changed.", file=sys.stderr)
            return 2
    if len(password) < MIN_LENGTH:
        print(f"Use at least {MIN_LENGTH} characters; nothing changed.", file=sys.stderr)
        return 2
    values = {"MFA_AUTH_PASSWORD_HASH": hash_password(password)}
    if not current(args.config_file, "MFA_AUTH_SECRET"):
        values["MFA_AUTH_SECRET"] = secrets.token_urlsafe(48)
    upsert(args.config_file, values)
    print(f"password set in {args.config_file}; restart the service to apply it")
    return 0


if __name__ == "__main__":
    sys.exit(main())
