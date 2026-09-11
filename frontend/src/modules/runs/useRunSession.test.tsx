import { act, renderHook, waitFor } from "@testing-library/react";
import { mockApi } from "@/test/mockApi";
import { version } from "@/test/fixtures";
import { baselineRun, whatIfRun } from "@/test/runFixtures";
import { useRunSession } from "./useRunSession";

afterEach(() => vi.restoreAllMocks());

describe("useRunSession", () => {
  it("collects a draft, posts it as overrides and keeps the what-if run active", async () => {
    const calls = mockApi({ [`POST /api/workbooks/${version.id}/runs`]: whatIfRun });
    const onBusy = vi.fn();
    const { result } = renderHook(() => useRunSession(version.id, onBusy));
    act(() => result.current.setDraft("Inputs!B3", { value: 200, type: "number", label: "Units", sheet: "Inputs", address: "B3" }));
    expect(result.current.draft.size).toBe(1);
    await act(async () => {
      await result.current.runAnalysis();
    });
    expect(calls[0].body).toEqual({ overrides: { "Inputs!B3": 200 }, mode: "auto", background: false });
    expect(onBusy).toHaveBeenCalledWith(true, "Running analysis with 1 override(s)");
    expect(onBusy).toHaveBeenLastCalledWith(false);
    expect(result.current.activeRun?.id).toBe(whatIfRun.id);
    expect(result.current.draft.size).toBe(0);

    // A further edit stacks on the active run's overrides.
    act(() => result.current.setDraft("Inputs!B2", { value: 0.5, type: "number", label: "Threshold", sheet: "Inputs", address: "B2" }));
    await act(async () => {
      await result.current.runAnalysis();
    });
    expect((calls[1].body as { overrides: unknown }).overrides).toEqual({ "Inputs!B2": 0.5, "Inputs!B3": 200 });

    act(() => result.current.backToBaseline());
    expect(result.current.activeRun).toBeNull();
  });

  it("reports a failed run without losing the draft", async () => {
    mockApi({
      [`POST /api/workbooks/${version.id}/runs`]: () =>
        new Response(JSON.stringify({ detail: "Series!D2 holds a formula" }), { status: 422 }),
    });
    const { result } = renderHook(() => useRunSession(version.id, () => {}));
    act(() => result.current.setDraft("Series!D2", { value: 1, type: "number", label: null, sheet: "Series", address: "D2" }));
    await act(async () => {
      await result.current.runAnalysis();
    });
    expect(result.current.error).toBe("Series!D2 holds a formula");
    expect(result.current.draft.size).toBe(1);
  });

  it("polls a background full run until it settles", async () => {
    vi.useFakeTimers();
    let polls = 0;
    mockApi({
      [`POST /api/workbooks/${version.id}/runs`]: { ...baselineRun, id: "job-1", status: "running" },
      "GET /api/runs/job-1": () => {
        polls += 1;
        return polls < 2 ? { ...baselineRun, id: "job-1", status: "running" } : { ...baselineRun, id: "job-1", status: "ok" };
      },
    });
    const onSettled = vi.fn();
    const { result } = renderHook(() => useRunSession(version.id, () => {}, onSettled));
    await act(async () => {
      await result.current.runFull();
    });
    expect(result.current.job?.status).toBe("running");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1100);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1100);
    });
    vi.useRealTimers();
    await waitFor(() => expect(result.current.job?.status).toBe("ok"));
    expect(onSettled).toHaveBeenCalled();
    act(() => result.current.dismissJob());
    expect(result.current.job).toBeNull();
  });
});
