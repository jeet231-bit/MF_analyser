"""A fixture workbook with a real pivot table part, built the way Excel would save it.

openpyxl cannot write pivot tables, so the OOXML pivot parts (cache definition, pivot
table, their relationships) are injected into the zip. The parser only needs the parts and
their relationships; openpyxl's read-only loader ignores them.
"""

from __future__ import annotations

import io
import zipfile

import openpyxl

from app.parser.package import inspect_package
from tests.fixtures.workbook import inject_cached_values, workbook_bytes

# Name, Group, Plan, Corpus (constant), Score (formula = Corpus / 100, cached by "Excel")
RECORDS: list[tuple[str, str, str, float]] = [
    ("Alpha One", "Large", "Direct", 1200.0),
    ("Alpha One - Reg", "Large", "Regular", 800.0),
    ("Beta One", "Large", "Direct", 400.0),
    ("Gamma One", "Small", "Direct", 250.0),
    ("Gamma One - Reg", "Small", "Regular", 150.0),
    ("Delta One", "Small", "Direct", 50.0),
    ("Epsilon One", "Mid", "Direct", 900.0),
    ("Zeta One", "Mid", "Regular", 300.0),
]
FIRST_ROW = 2


def build_pivot_workbook() -> openpyxl.Workbook:
    wb = openpyxl.Workbook()
    data = wb.active
    data.title = "Data"
    data.append(["Name", "Group", "Plan", "Corpus", "Score"])
    for i, (name, group, plan, corpus) in enumerate(RECORDS):
        row = FIRST_ROW + i
        data.append([name, group, plan, corpus, f"=D{row}/100"])
    pivot = wb.create_sheet("Pivot")
    pivot["A1"] = "Plan"
    pivot["B1"] = "Direct"
    pivot["A3"] = "Row Labels"
    pivot["B3"] = "Average of Corpus"
    return wb


def _cache_xml(records: int) -> str:
    names = ["Name", "Group", "Plan", "Corpus", "Score"]
    groups = sorted({r[1] for r in RECORDS})
    plans = sorted({r[2] for r in RECORDS})
    fields = [
        '<cacheField name="Name" numFmtId="0"><sharedItems count="{n}">{items}</sharedItems></cacheField>'.format(
            n=len(RECORDS), items="".join(f'<s v="{r[0]}"/>' for r in RECORDS)
        ),
        '<cacheField name="Group" numFmtId="0"><sharedItems count="{n}">{items}</sharedItems></cacheField>'.format(
            n=len(groups), items="".join(f'<s v="{g}"/>' for g in groups)
        ),
        '<cacheField name="Plan" numFmtId="0"><sharedItems count="{n}">{items}</sharedItems></cacheField>'.format(
            n=len(plans), items="".join(f'<s v="{p}"/>' for p in plans)
        ),
        '<cacheField name="Corpus" numFmtId="0"><sharedItems containsSemiMixedTypes="0" containsString="0" containsNumber="1" minValue="50" maxValue="1200"/></cacheField>',
        '<cacheField name="Score" numFmtId="0"><sharedItems containsSemiMixedTypes="0" containsString="0" containsNumber="1" minValue="0.5" maxValue="12"/></cacheField>',
    ]
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<pivotCacheDefinition xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        f'refreshedBy="Excel" refreshedDate="45900.5" createdVersion="8" refreshedVersion="8" minRefreshableVersion="3" recordCount="{records}">'
        f'<cacheSource type="worksheet"><worksheetSource ref="A1:E{FIRST_ROW + records - 1}" sheet="Data"/></cacheSource>'
        f'<cacheFields count="{len(names)}">{"".join(fields)}</cacheFields>'
        "</pivotCacheDefinition>"
    )


def _table_xml() -> str:
    plans = sorted({r[2] for r in RECORDS})
    direct = plans.index("Direct")
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<pivotTableDefinition xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" name="PivotFunds" cacheId="1" '
        'applyNumberFormats="0" applyBorderFormats="0" applyFontFormats="0" applyPatternFormats="0" applyAlignmentFormats="0" '
        'applyWidthHeightFormats="1" dataCaption="Values" updatedVersion="8" minRefreshableVersion="3" useAutoFormatting="1" '
        'itemPrintTitles="1" createdVersion="8" indent="0" outline="1" outlineData="1" multipleFieldFilters="0" rowHeaderCaption="Row Labels">'
        '<location ref="A3:C7" firstHeaderRow="1" firstDataRow="1" firstDataCol="1" rowPageCount="1" colPageCount="1"/>'
        '<pivotFields count="5">'
        '<pivotField showAll="0"/>'
        '<pivotField axis="axisRow" showAll="0"><items count="4"><item x="0"/><item x="1"/><item x="2"/><item t="default"/></items></pivotField>'
        f'<pivotField axis="axisPage" showAll="0"><items count="3"><item x="0"/><item x="1"/><item t="default"/></items></pivotField>'
        '<pivotField dataField="1" showAll="0"/>'
        '<pivotField dataField="1" showAll="0"/>'
        "</pivotFields>"
        '<rowFields count="1"><field x="1"/></rowFields>'
        '<rowItems count="4"><i><x/></i><i><x v="1"/></i><i><x v="2"/></i><i t="grand"><x/></i></rowItems>'
        '<colFields count="1"><field x="-2"/></colFields>'
        '<colItems count="2"><i><x/></i><i i="1"><x v="1"/></i></colItems>'
        f'<pageFields count="1"><pageField fld="2" item="{direct}" hier="-1"/></pageFields>'
        '<dataFields count="2">'
        '<dataField name="Average of Corpus" fld="3" subtotal="average" baseField="0" baseItem="0"/>'
        '<dataField name="Count of Name" fld="0" subtotal="count" baseField="0" baseItem="0"/>'
        "</dataFields>"
        '<pivotTableStyleInfo name="PivotStyleLight16" showRowHeaders="1" showColHeaders="1" showRowStripes="0" showColStripes="0" showLastColumn="1"/>'
        "</pivotTableDefinition>"
    )


def pivot_fixture_xlsx_bytes() -> bytes:
    """The fixture with cached values for the Score formulas and the pivot parts injected."""
    cached = {("Data", f"E{FIRST_ROW + i}"): r[3] / 100 for i, r in enumerate(RECORDS)}
    xlsx = inject_cached_values(workbook_bytes(build_pivot_workbook()), cached)
    info = inspect_package(io.BytesIO(xlsx))
    pivot_part = next(s.path for s in info.sheets if s.name == "Pivot")  # xl/worksheets/sheetN.xml
    sheet_file = pivot_part.rsplit("/", 1)[-1]
    src = zipfile.ZipFile(io.BytesIO(xlsx))
    out = io.BytesIO()
    rels_ns = "http://schemas.openxmlformats.org/package/2006/relationships"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            dst.writestr(item, src.read(item.filename))
        dst.writestr("xl/pivotCache/pivotCacheDefinition1.xml", _cache_xml(len(RECORDS)))
        dst.writestr("xl/pivotTables/pivotTable1.xml", _table_xml())
        dst.writestr(
            "xl/pivotTables/_rels/pivotTable1.xml.rels",
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="{rels_ns}">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/pivotCacheDefinition" Target="../pivotCache/pivotCacheDefinition1.xml"/>'
            "</Relationships>",
        )
        dst.writestr(
            f"xl/worksheets/_rels/{sheet_file}.rels",
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="{rels_ns}">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/pivotTable" Target="../pivotTables/pivotTable1.xml"/>'
            "</Relationships>",
        )
    return out.getvalue()
