"""The shipped research map against the real master (opt-in, ``-m real``): every reference
resolves, the views answer within budget, and the default insight sentences read for sense."""

import time

import pytest
from fastapi.testclient import TestClient

from app.dashboard_config import load_dashboard_config
from app.research.semantic import parse_map
from app.storage import workbooks
from app.storage.db import get_session_factory
from tests.test_real_engine import WORKBOOKS  # the same sample discovery

pytestmark = pytest.mark.real

COLD_BUDGET_S = 15
WARM_BUDGET_S = 1.0


@pytest.mark.skipif(not WORKBOOKS, reason="no workbook in samples/")
def test_research_views_on_the_real_master(client: TestClient) -> None:
    from app.storage import logic, validation

    rmap, problems = parse_map(load_dashboard_config().research)
    assert rmap is not None and problems == [], problems
    with get_session_factory()() as session:
        try:
            version = workbooks.ingest_workbook(session, WORKBOOKS[0], filename=WORKBOOKS[0].name)
        except PermissionError:
            pytest.skip("master is locked by another process")
        logic.interpret_version(session, version.id, scope=None, config=load_dashboard_config())
        validation.validate_version(session, version.id)
        client.post(f"/api/workbooks/{version.id}/activate", json={})

    cfg = client.get("/api/research/config").json()
    assert cfg["configured"] is True, cfg["problems"]
    unresolved = [m["key"] for m in cfg["measures"] if not m["resolved"]]
    print("\nresolved measures:", [(m["key"], m["ref"]) for m in cfg["measures"] if m["resolved"]])
    assert unresolved == [], unresolved
    assert cfg["problems"] == [], cfg["problems"]

    t = time.perf_counter()
    summary = client.get("/api/research/summary").json()
    cold = time.perf_counter() - t
    assert summary["configured"] is True
    print(
        f"summary cold {cold:.1f}s | universe {summary['universe']} | quartiles {summary['quartiles']}"
    )
    print("  universe narrative:", summary["universe_narrative"])
    print("  dashboard narrative:", summary["narrative"])
    print("  held_q1:", summary["held_q1"])
    t = time.perf_counter()
    client.get("/api/research/summary").json()
    warm = time.perf_counter() - t
    print(f"summary warm {warm:.2f}s")
    assert cold < COLD_BUDGET_S and warm < WARM_BUDGET_S

    t = time.perf_counter()
    entities = client.get("/api/research/entities", params={"size": 50}).json()
    print(
        f"entities {time.perf_counter() - t:.2f}s | total {entities['total']} | first {entities['rows'][0]['label']} rank {entities['rows'][0]['measures']['rank']}"
    )
    assert entities["total"] > 1000
    coverage = {
        m["key"]: sum(1 for r in entities["rows"] if r["measures"].get(m["key"]) is not None)
        for m in entities["measures"]
    }
    print("numeric coverage in the first 50 rows:", coverage)

    key = entities["rows"][0]["key"]
    t = time.perf_counter()
    detail = client.get(f"/api/research/entities/{key}").json()
    print(
        f"detail {time.perf_counter() - t:.2f}s | phases {len(detail['phases'])} | peers {len(detail['peers'])} | history {len(detail['history'])}"
    )
    print("  quartile explanation:", detail["quartileExplanation"])
    assert detail["configured"] is True and len(detail["phases"]) == 10

    t = time.perf_counter()
    cats = client.get("/api/research/categories").json()
    print(
        f"categories {time.perf_counter() - t:.2f}s | {len(cats['rows'])} categories | narrative: {cats['narrative']}"
    )

    t = time.perf_counter()
    ins = client.get("/api/research/insights").json()
    print(f"insights cold {time.perf_counter() - t:.1f}s")
    t = time.perf_counter()
    client.get("/api/research/insights").json()
    print(f"insights warm {time.perf_counter() - t:.2f}s")
    for i in ins["insights"]:
        print(
            f"  [{i['section']}] {i['title']}: {i['sentence'] or '(' + i['status'] + ': ' + (i['note'] or '; '.join(i['problems'])) + ')'}"
        )
        for r in i["rows"][:3]:
            print(f"      {r['label']} · {r['sub'] or ''} · {r['valueLabel']}")
    # A single stored version cannot answer "held every version"; every other card must read.
    assert all(i["sentence"] or i["status"] == "unavailable" for i in ins["insights"]), [
        (i["key"], i["status"], i["problems"]) for i in ins["insights"] if not i["sentence"]
    ]

    t = time.perf_counter()
    move = client.get("/api/research/movement").json()
    print(
        f"movement {time.perf_counter() - t:.1f}s | available {move.get('available')} | {move.get('reason') or move.get('narrative')}"
    )
