"""Explore: any measure by any grouping, with the change since the previous month.

The value the workbook cannot give is the comparison, so these tests upload two months and
check that every number carries its own delta, and that the groups match the fixture's own
arithmetic rather than a remembered constant.
"""

from __future__ import annotations

import csv
import io
import statistics

import pytest
from fastapi.testclient import TestClient

from app import dashboard_config
from app.config import get_settings
from app.research import table as table_store
from tests.fixtures.research_workbook import (
    FUNDS,
    expected,
    research_fixture_xlsx_bytes,
    research_map,
    write_config,
)

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
AMC, CATEGORY, PLAN = 3, 4, 2  # column positions in FUNDS


@pytest.fixture(autouse=True)
def _fresh_database(tmp_path, monkeypatch):
    from app.storage.db import get_engine, get_session_factory

    monkeypatch.setenv("MFA_DATA_DIR", str(tmp_path / "data"))
    for cached in (get_settings, get_engine, get_session_factory):
        cached.cache_clear()
    table_store.clear_all()
    yield
    for cached in (get_settings, get_engine, get_session_factory):
        cached.cache_clear()


@pytest.fixture
def config(tmp_path, monkeypatch):
    """A dashboard.config.json whose research map is the fixture's, plus explore settings."""

    def use(research):
        path = write_config(tmp_path / "dashboard.config.json", research)
        monkeypatch.setenv("MFA_DASHBOARD_CONFIG_PATH", str(path))
        get_settings.cache_clear()
        dashboard_config._load.cache_clear()
        table_store.clear_all()
        return path

    rmap = research_map()
    rmap["narratives"]["explore"] = [
        {
            "default": "Grouped by {dimension}: {groups} in all, {eligible} with at least {min_group} rated funds."
        },
        {
            "default": "{top} holds the most top-quartile funds, {top_q1} of {top_rated} rated.",
            "requires": ["top"],
        },
        {
            "default": "Since {previous}, {riser} improved most on {measure}, by {riser_delta}.",
            "requires": ["riser", "previous"],
        },
    ]
    rmap["explore"] = {"presets": [{"label": "Score by house", "by": "amc", "measure": "score"}]}
    rmap["dashboard"] = {"callouts": ["best_value", "amc_league"]}
    use(rmap)
    yield use
    monkeypatch.delenv("MFA_DASHBOARD_CONFIG_PATH", raising=False)
    get_settings.cache_clear()
    dashboard_config._load.cache_clear()
    table_store.clear_all()


def _upload(client: TestClient, name: str, variant: str = "base") -> str:
    r = client.post(
        "/api/workbooks", files={"file": (name, research_fixture_xlsx_bytes(variant), XLSX)}
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["validation_status"] in ("passed", "passed_with_warnings"), body["pipeline_notes"]
    assert client.post(f"/api/workbooks/{body['id']}/activate", json={}).status_code == 200
    return body["id"]


def _by_group(variant: str, column: int, field: str = "score") -> dict[str, list[float]]:
    """The fixture's own arithmetic: group -> the numeric values of one field in it."""
    exp = expected(variant)
    out: dict[str, list[float]] = {}
    for f in FUNDS:
        value = exp[f[0]][field]
        out.setdefault(f[column], [])
        if isinstance(value, int | float):
            out[f[column]].append(float(value))
    return out


def test_groups_match_the_workbooks_own_arithmetic(client: TestClient, config) -> None:
    _upload(client, "master.xlsx")
    body = client.get(
        "/api/research/explore", params={"by": "amc", "measure": "score", "agg": "mean", "limit": 0}
    ).json()
    assert body["configured"] is True
    assert body["by"] == {"key": "amc", "label": "AMC", "kind": "dimension"}
    assert body["measure"]["key"] == "score" and body["measure"]["higherIsBetter"] is True

    wanted = _by_group("base", AMC)
    quartiles = _by_group("base", AMC, "quartile")
    rows = {g["label"]: g for g in body["groups"]}
    assert set(rows) == set(wanted)
    for name, scores in wanted.items():
        assert rows[name]["funds"] == sum(1 for f in FUNDS if f[AMC] == name)
        assert rows[name]["value"] == pytest.approx(statistics.fmean(scores))
        # "Rated" is the workbook's own test: a fund the master gave a quartile, which is
        # fewer than the funds carrying a score (a small category is left unranked).
        assert rows[name]["rated"] == len(quartiles[name])
        assert sum(int(n) for n in rows[name]["quartiles"].values()) == rows[name]["rated"]
        assert rows[name]["quartiles"]["1"] == sum(1 for q in quartiles[name] if q == 1)
    # Sorted by the measure, best first, because a higher score is better.
    assert body["sort"] == "value" and body["dir"] == "desc"
    values = [g["value"] for g in body["groups"] if g["value"] is not None]
    assert values == sorted(values, reverse=True)
    # The grand total is every fund, not the sum of the groups.
    assert body["totals"]["funds"] == len(FUNDS)
    assert body["narrative"].startswith("Grouped by AMC:")


def test_change_since_the_previous_month(client: TestClient, config) -> None:
    _upload(client, "aug.xlsx", "base")
    _upload(client, "sep.xlsx", "shift")  # Alpha One jumps, Beta One - Reg drops
    body = client.get(
        "/api/research/explore", params={"by": "amc", "measure": "score", "limit": 0}
    ).json()
    assert body["compare"]["available"] is True
    assert body["compare"]["previous"]["filename"] == "aug.xlsx"

    before, after = _by_group("base", AMC), _by_group("shift", AMC)
    rows = {g["label"]: g for g in body["groups"]}
    for name in after:
        delta = rows[name]["delta"]
        assert delta["new"] is False
        assert delta["value"] == pytest.approx(
            statistics.fmean(after[name]) - statistics.fmean(before[name])
        )
        assert delta["funds"] == 0  # the shift moves scores, not funds
    moved = [n for n in after if abs(rows[n]["delta"]["value"]) > 1e-9]
    assert moved, "the shift variant must change at least one group's mean"
    assert body["totals"]["delta"]["value"] == pytest.approx(
        statistics.fmean([v for vs in after.values() for v in vs])
        - statistics.fmean([v for vs in before.values() for v in vs])
    )
    assert "improved most on Score" in body["narrative"]

    # Asking not to compare drops the deltas and the second table build.
    plain = client.get("/api/research/explore", params={"by": "amc", "compare": "false"}).json()
    assert plain["compare"]["available"] is False
    assert all(g["delta"] is None for g in plain["groups"])


def test_one_version_says_there_is_nothing_to_compare(client: TestClient, config) -> None:
    _upload(client, "master.xlsx")
    body = client.get("/api/research/explore", params={"by": "category"}).json()
    assert body["compare"] == {
        "requested": True,
        "available": False,
        "previous": None,
        "note": "no earlier version with a baseline run to compare with",
    }
    assert all(g["delta"] is None for g in body["groups"])


def test_grouping_by_plan_band_and_the_small_group_flag(client: TestClient, config) -> None:
    _upload(client, "master.xlsx")
    by_plan = client.get(
        "/api/research/explore", params={"by": "plan", "measure": "score", "limit": 0}
    ).json()
    assert {g["label"] for g in by_plan["groups"]} == {f[PLAN] for f in FUNDS}

    options = {o["key"]: o for o in by_plan["options"]["by"]}
    assert options["category"]["kind"] == "dimension"
    assert "corpus_band" in options and options["corpus_band"]["kind"] == "band"
    banded = client.get(
        "/api/research/explore", params={"by": "corpus_band", "measure": "score", "limit": 0}
    ).json()
    assert banded["by"]["kind"] == "band"
    assert sum(g["funds"] for g in banded["groups"]) == sum(1 for f in FUNDS if f[8] is not None)

    # minGroupCount is 2 in the fixture: smaller groups are listed but marked, never ranked.
    by_cat = client.get(
        "/api/research/explore", params={"by": "category", "measure": "score", "limit": 0}
    ).json()
    assert by_cat["minGroupCount"] == 2
    for g in by_cat["groups"]:
        assert g["small"] == (g["rated"] < 2)


def test_sorting_limit_aggregations_and_errors(client: TestClient, config) -> None:
    _upload(client, "master.xlsx")

    def get(**params):
        r = client.get("/api/research/explore", params=params)
        return r.status_code, r.json()

    _code, ranked = get(by="amc", measure="rank", limit=0)
    assert ranked["dir"] == "asc"  # a lower rank is better, so the best group comes first
    ranks = [g["value"] for g in ranked["groups"] if g["value"] is not None]
    assert ranks == sorted(ranks)

    _code, by_size = get(by="amc", measure="corpus", agg="sum", sort="funds", dir="desc", limit=2)
    assert by_size["agg"] == "sum" and len(by_size["groups"]) == 2
    assert by_size["groupCount"] >= len(by_size["groups"])
    counts = [g["funds"] for g in by_size["groups"]]
    assert counts == sorted(counts, reverse=True)
    corpus = {}
    for f in FUNDS:
        corpus.setdefault(f[AMC], 0.0)
        corpus[f[AMC]] += float(f[8])
    assert by_size["groups"][0]["value"] == pytest.approx(corpus[by_size["groups"][0]["label"]])

    _code, shares = get(by="amc", measure="quartile", limit=0)
    assert shares["sort"] == "q1_share"  # a quartile measure ranks houses by their Q1 share
    for g in shares["groups"]:
        assert g["q1Share"] == (
            pytest.approx(int(g["quartiles"]["1"]) / g["rated"]) if g["rated"] else None
        )

    assert get(by="amc", agg="nope")[0] == 422
    assert get(by="amc", sort="nope")[0] == 422
    # An unknown grouping or measure falls back to the first one the map offers, never a 500.
    _code, fallback = get(by="not-a-dimension", measure="not-a-measure")
    assert fallback["configured"] is True and fallback["by"]["kind"] in ("dimension", "band")


def test_export_carries_every_group_and_its_change(client: TestClient, config) -> None:
    _upload(client, "aug.xlsx", "base")
    _upload(client, "sep.xlsx", "shift")
    r = client.get(
        "/api/research/explore/export", params={"by": "amc", "measure": "score", "format": "csv"}
    )
    assert r.status_code == 200
    rows = list(csv.reader(io.StringIO(r.content.decode("utf-8-sig"))))
    assert rows[0][:4] == ["AMC", "Funds", "Rated", "Q1"]
    assert "Change since" in " ".join(rows[0])
    assert rows[-1][0] == "All"
    assert len(rows) == 1 + len({f[AMC] for f in FUNDS}) + 1  # header, groups, total
    x = client.get("/api/research/explore/export", params={"by": "category", "format": "xlsx"})
    assert x.status_code == 200 and x.content[:2] == b"PK"


def test_dashboard_callouts_come_from_the_config(client: TestClient, config) -> None:
    _upload(client, "master.xlsx")
    body = client.get("/api/research/summary").json()
    assert [c["key"] for c in body["callouts"]] == ["best_value", "amc_league"]
    first = body["callouts"][0]
    assert first["title"] and first["sentence"] and "keys" in first["drill"]

    config({**research_map(), "dashboard": {"callouts": []}})
    assert client.get("/api/research/summary").json()["callouts"] == []


def test_not_configured_is_a_200_with_problems(client: TestClient, config) -> None:
    config(None)
    _upload(client, "master.xlsx")
    body = client.get("/api/research/explore", params={"by": "amc"}).json()
    assert body["configured"] is False and body["problems"] and body["groups"] == []
