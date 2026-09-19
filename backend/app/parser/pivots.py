"""Pivot tables as the workbook defines them, read from the OOXML pivot parts.

Excel stores each pivot as ``xl/pivotTables/pivotTableN.xml`` (layout: row, column, page
and data fields; the items shown or hidden) over a ``pivotCacheDefinition`` (the source
sheet and range, the field names in column order). Nothing here is workbook-specific: the
names come from the file, and the app recomputes the pivot from the engine's values.
"""

from __future__ import annotations

import datetime
import posixpath
import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import IO

from app.parser.models import PivotField, PivotSpec, PivotValue
from app.parser.package import NS_MAIN, NS_REL, _read_rels, _resolve

_PIVOT_REL = "/pivotTable"
_CACHE_REL = "/pivotCacheDefinition"
_AGG = {
    "sum": "sum",
    "count": "count",
    "average": "average",
    "max": "max",
    "min": "min",
    "countNums": "countNums",
    "product": "product",
    "stdDev": "stdDev",
    "stdDevp": "stdDevp",
    "var": "var",
    "varp": "varp",
}


def _q(tag: str) -> str:
    return f"{{{NS_MAIN}}}{tag}"


def _sheet_parts(zf: zipfile.ZipFile) -> dict[str, str]:
    """sheet part path -> sheet name."""
    wb_root = ET.fromstring(zf.read("xl/workbook.xml"))
    wb_rels = _read_rels(zf, "xl/_rels/workbook.xml.rels")
    out: dict[str, str] = {}
    for sh in wb_root.iter(_q("sheet")):
        rel_id = sh.attrib.get(f"{{{NS_REL}}}id", "")
        _type, target = wb_rels.get(rel_id, ("", ""))
        out[_resolve("xl", target)] = sh.attrib.get("name", "")
    return out


def _rels_of(part: str) -> str:
    d, f = posixpath.split(part)
    return posixpath.join(d, "_rels", f + ".rels")


def _shared_items(field_el: ET.Element) -> tuple[list[str], bool]:
    items: list[str] = []
    numeric = False
    shared = field_el.find(_q("sharedItems"))
    if shared is None:
        return items, numeric
    numeric = (
        shared.attrib.get("containsNumber") == "1"
        and shared.attrib.get("containsString", "0") != "1"
    )
    for child in shared:
        tag = child.tag.rsplit("}", 1)[-1]
        if tag in ("s", "n", "d", "b"):
            items.append(child.attrib.get("v", ""))
        elif tag == "m":
            items.append("")
    return items, numeric


def _refreshed(root: ET.Element) -> str | None:
    raw = root.attrib.get("refreshedDate")
    if not raw:
        return None
    try:
        stamp = datetime.datetime(1899, 12, 30) + datetime.timedelta(days=float(raw))
    except (ValueError, OverflowError):
        return None
    return stamp.replace(microsecond=0).isoformat()


def _parse_cache(
    zf: zipfile.ZipFile, part: str
) -> tuple[str, str, int, list[PivotField], list[list[str]], str | None]:
    root = ET.fromstring(zf.read(part))
    src = root.find(_q("cacheSource"))
    ws = src.find(_q("worksheetSource")) if src is not None else None
    sheet = ws.attrib.get("sheet", "") if ws is not None else ""
    ref = ws.attrib.get("ref", "") if ws is not None else ""
    if ws is not None and not ref and ws.attrib.get("name"):
        ref = ws.attrib["name"]  # a named range or table
    records = int(root.attrib.get("recordCount", "0") or 0)
    fields: list[PivotField] = []
    items: list[list[str]] = []
    cache_fields = root.find(_q("cacheFields"))
    for i, f in enumerate(cache_fields if cache_fields is not None else []):
        shared, numeric = _shared_items(f)
        fields.append(
            PivotField(name=f.attrib.get("name", f"Field {i + 1}"), index=i, numeric=numeric)
        )
        items.append(shared)
    return sheet, ref, records, fields, items, _refreshed(root)


def _axis_fields(table: ET.Element, tag: str, fields: list[PivotField]) -> list[str]:
    el = table.find(_q(tag))
    out: list[str] = []
    if el is None:
        return out
    for f in el:
        x = f.attrib.get("x")
        if x is None:
            continue
        i = int(x)
        if 0 <= i < len(fields):  # x == -2 is the "Values" pseudo-field
            out.append(fields[i].name)
    return out


def _items_of(pivot_field: ET.Element | None) -> list[ET.Element]:
    if pivot_field is None:
        return []
    items = pivot_field.find(_q("items"))
    if items is None:
        return []
    return [it for it in items if it.attrib.get("x") is not None]


def parse_pivots(source: str | Path | IO[bytes]) -> list[PivotSpec]:
    """Every pivot table in the package, in sheet order, with its layout and saved filters."""
    with zipfile.ZipFile(source) as zf:
        names = set(zf.namelist())
        sheets = _sheet_parts(zf)
        out: list[PivotSpec] = []
        for sheet_part, sheet_name in sheets.items():
            rels = _read_rels(zf, _rels_of(sheet_part))
            for _rid, (rtype, target) in rels.items():
                if not rtype.endswith(_PIVOT_REL):
                    continue
                part = _resolve(posixpath.dirname(sheet_part), target)
                if part not in names:
                    continue
                spec = _parse_table(zf, part, sheet_name, names)
                if spec is not None:
                    out.append(spec)
        return out


def _parse_table(
    zf: zipfile.ZipFile, part: str, sheet_name: str, names: set[str]
) -> PivotSpec | None:
    table = ET.fromstring(zf.read(part))
    cache_part = None
    for _rid, (rtype, target) in _read_rels(zf, _rels_of(part)).items():
        if rtype.endswith(_CACHE_REL):
            cache_part = _resolve(posixpath.dirname(part), target)
    if cache_part is None or cache_part not in names:
        return None
    src_sheet, src_ref, records, fields, items, refreshed = _parse_cache(zf, cache_part)
    loc = table.find(_q("location"))
    anchor = loc.attrib.get("ref", "") if loc is not None else ""

    values: list[PivotValue] = []
    data_fields = table.find(_q("dataFields"))
    for d in data_fields if data_fields is not None else []:
        i = int(d.attrib.get("fld", "-1"))
        if not 0 <= i < len(fields):
            continue
        values.append(
            PivotValue(
                label=d.attrib.get("name") or fields[i].name,
                field=fields[i].name,
                agg=_AGG.get(d.attrib.get("subtotal", "sum"), "sum"),
            )
        )

    # Page (filter) fields and the selection Excel saved: one item, or the items left shown.
    filters: list[str] = []
    saved: dict[str, list[str]] = {}
    pf_root = table.find(_q("pivotFields"))
    pivot_fields = list(pf_root) if pf_root is not None else []
    page_fields = table.find(_q("pageFields"))
    for pf in page_fields if page_fields is not None else []:
        i = int(pf.attrib.get("fld", "-1"))
        if not 0 <= i < len(fields):
            continue
        name = fields[i].name
        filters.append(name)
        field_el = pivot_fields[i] if i < len(pivot_fields) else None
        entries = _items_of(field_el)
        item = pf.attrib.get("item")
        if item is not None:
            j = int(item)
            if 0 <= j < len(entries):
                x = int(entries[j].attrib["x"])
                if 0 <= x < len(items[i]):
                    saved[name] = [items[i][x]]
        elif field_el is not None and field_el.attrib.get("multipleItemSelectionAllowed") == "1":
            shown = [
                items[i][int(it.attrib["x"])]
                for it in entries
                if it.attrib.get("h") != "1" and int(it.attrib["x"]) < len(items[i])
            ]
            if shown and len(shown) < len(items[i]):
                saved[name] = shown

    return PivotSpec(
        name=table.attrib.get("name", posixpath.basename(part)),
        sheet=sheet_name,
        anchor=anchor,
        source_sheet=src_sheet,
        source_ref=src_ref,
        records=records,
        refreshed=refreshed,
        fields=fields,
        rows=_axis_fields(table, "rowFields", fields),
        cols=_axis_fields(table, "colFields", fields),
        filters=filters,
        values=values,
        saved_filters=saved,
    )


_A1 = re.compile(r"^[A-Z]{1,3}\d+(:[A-Z]{1,3}\d+)?$")


def is_a1_range(ref: str) -> bool:
    return bool(_A1.match(ref.replace("$", "")))
