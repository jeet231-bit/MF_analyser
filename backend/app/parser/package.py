"""Direct inspection of the OOXML package (zip parts) for what openpyxl's streaming reader omits:
merged ranges, tables, defined names, sheet parts, macros, pivots and external links.

Everything here is cheap: small XML parts are parsed with ElementTree; large sheet parts are
only scanned with a regex for ``<mergeCell>`` elements.
"""

from __future__ import annotations

import posixpath
import re
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO

from app.parser.models import DefinedName, TableDef

NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
REL_TABLE = "/table"
MERGE_RE = re.compile(rb'<mergeCell\b[^>]*\bref="([^"]+)"')


@dataclass
class SheetPart:
    name: str
    sheet_id: int
    rel_id: str
    path: str  # e.g. xl/worksheets/sheet1.xml
    state: str = "visible"
    is_chartsheet: bool = False
    merged_ranges: list[str] = field(default_factory=list)
    tables: list[TableDef] = field(default_factory=list)


@dataclass
class PackageInfo:
    sheets: list[SheetPart]
    defined_names: list[DefinedName]
    has_macros: bool
    has_pivots: bool
    has_external_links: bool
    epoch: int


def _resolve(base_dir: str, target: str) -> str:
    if target.startswith("/"):
        return target.lstrip("/")
    return posixpath.normpath(posixpath.join(base_dir, target))


def _read_rels(zf: zipfile.ZipFile, rels_path: str) -> dict[str, tuple[str, str]]:
    """rId -> (type, target) for a .rels part; empty when the part does not exist."""
    if rels_path not in zf.namelist():
        return {}
    root = ET.fromstring(zf.read(rels_path))
    out: dict[str, tuple[str, str]] = {}
    for rel in root.iter(f"{{{NS_PKG_REL}}}Relationship"):
        out[rel.attrib["Id"]] = (rel.attrib.get("Type", ""), rel.attrib.get("Target", ""))
    return out


def _parse_table(zf: zipfile.ZipFile, path: str, sheet_name: str) -> TableDef:
    root = ET.fromstring(zf.read(path))
    columns = [c.attrib.get("name", "") for c in root.iter(f"{{{NS_MAIN}}}tableColumn")]
    return TableDef(
        name=root.attrib.get("name", root.attrib.get("displayName", "")),
        display_name=root.attrib.get("displayName", root.attrib.get("name", "")),
        sheet=sheet_name,
        ref=root.attrib.get("ref", ""),
        columns=columns,
        header_row=root.attrib.get("headerRowCount", "1") != "0",
        totals_row=root.attrib.get("totalsRowCount", "0") != "0",
    )


def _parse_defined_names(root: ET.Element, sheet_names: list[str]) -> list[DefinedName]:
    names: list[DefinedName] = []
    for dn in root.iter(f"{{{NS_MAIN}}}definedName"):
        name = dn.attrib.get("name", "")
        local = dn.attrib.get("localSheetId")
        scope = None
        if local is not None and local.isdigit() and int(local) < len(sheet_names):
            scope = sheet_names[int(local)]
        names.append(
            DefinedName(
                name=name,
                refers_to=(dn.text or "").strip(),
                scope=scope,
                builtin=name.startswith("_xlnm."),
                hidden=dn.attrib.get("hidden", "0") in ("1", "true"),
            )
        )
    return names


def inspect_package(source: str | Path | IO[bytes]) -> PackageInfo:
    with zipfile.ZipFile(source) as zf:
        names = set(zf.namelist())
        wb_root = ET.fromstring(zf.read("xl/workbook.xml"))
        wb_rels = _read_rels(zf, "xl/_rels/workbook.xml.rels")

        sheets: list[SheetPart] = []
        for sh in wb_root.iter(f"{{{NS_MAIN}}}sheet"):
            rel_id = sh.attrib.get(f"{{{NS_REL}}}id", "")
            rel_type, target = wb_rels.get(rel_id, ("", ""))
            path = _resolve("xl", target)
            sheets.append(
                SheetPart(
                    name=sh.attrib.get("name", ""),
                    sheet_id=int(sh.attrib.get("sheetId", "0") or 0),
                    rel_id=rel_id,
                    path=path,
                    state=sh.attrib.get("state", "visible"),
                    is_chartsheet=rel_type.endswith("/chartsheet") or "/chartsheets/" in f"/{path}",
                )
            )

        for part in sheets:
            if part.is_chartsheet or part.path not in names:
                continue
            with zf.open(part.path) as fh:
                data = fh.read()
            part.merged_ranges = [m.decode() for m in MERGE_RE.findall(data)]
            sheet_dir, sheet_file = posixpath.split(part.path)
            rels = _read_rels(zf, posixpath.join(sheet_dir, "_rels", sheet_file + ".rels"))
            for rel_type, target in rels.values():
                if rel_type.endswith(REL_TABLE):
                    table_path = _resolve(sheet_dir, target)
                    if table_path in names:
                        part.tables.append(_parse_table(zf, table_path, part.name))

        sheet_names = [s.name for s in sheets]
        defined_names = _parse_defined_names(wb_root, sheet_names)

        pr = wb_root.find(f"{{{NS_MAIN}}}workbookPr")
        epoch = 1904 if pr is not None and pr.attrib.get("date1904", "0") in ("1", "true") else 1900

        return PackageInfo(
            sheets=sheets,
            defined_names=defined_names,
            has_macros=any(n.endswith("vbaProject.bin") for n in names),
            has_pivots=any(n.startswith("xl/pivotTables/") for n in names),
            has_external_links=any(n.startswith("xl/externalLinks/") for n in names),
            epoch=epoch,
        )
