import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { apiGet, UNAUTHENTICATED_EVENT } from "@/api/client";
import { jsonError, mockApi } from "@/test/mockApi";
import { LoginGate } from "./LoginGate";
import { useAuth } from "./useAuth";

function Inside() {
  const auth = useAuth();
  return (
    <div>
      <span>the app</span>
      {auth.required && (
        <button type="button" onClick={() => void auth.signOut()}>
          Sign out
        </button>
      )}
    </div>
  );
}

afterEach(() => vi.restoreAllMocks());

describe("LoginGate", () => {
  it("renders the app straight away when no password is configured", async () => {
    mockApi({ "GET /api/auth/session": { required: false, authenticated: true, sessionHours: 12 } });
    render(
      <LoginGate>
        <Inside />
      </LoginGate>,
    );
    expect(await screen.findByText("the app")).toBeInTheDocument();
    expect(screen.queryByText("Sign out")).toBeNull();
  });

  it("shows the sign-in form, rejects a wrong password, then opens the app", async () => {
    let signedIn = false;
    const calls = mockApi({
      "GET /api/auth/session": () => ({ required: true, authenticated: signedIn, sessionHours: 12 }),
      "POST /api/auth/login": (init?: RequestInit) => {
        const body = JSON.parse(String(init?.body)) as { password: string };
        if (body.password !== "open sesame") return jsonError(401, "That password is not right.");
        signedIn = true;
        return new Response(null, { status: 204 });
      },
      "POST /api/auth/logout": () => new Response(null, { status: 204 }),
    });
    render(
      <LoginGate>
        <Inside />
      </LoginGate>,
    );
    const field = await screen.findByLabelText("Shared password");
    expect(screen.queryByText("the app")).toBeNull();
    fireEvent.change(field, { target: { value: "nope" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("That password is not right.");

    fireEvent.change(field, { target: { value: "open sesame" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText("the app")).toBeInTheDocument();
    expect(calls.filter((c) => c.url === "/api/auth/login")).toHaveLength(2);

    // An expired session (any 401 from the API) brings the form back without a reload.
    act(() => window.dispatchEvent(new CustomEvent(UNAUTHENTICATED_EVENT)));
    expect(await screen.findByLabelText("Shared password")).toBeInTheDocument();
  });

  it("offers sign out when the gate is on, and locks after it", async () => {
    mockApi({
      "GET /api/auth/session": { required: true, authenticated: true, sessionHours: 12 },
      "POST /api/auth/logout": () => new Response(null, { status: 204 }),
    });
    render(
      <LoginGate>
        <Inside />
      </LoginGate>,
    );
    fireEvent.click(await screen.findByText("Sign out"));
    expect(await screen.findByLabelText("Shared password")).toBeInTheDocument();
  });

  it("explains when the server cannot be reached", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("Failed to fetch"));
    render(
      <LoginGate>
        <Inside />
      </LoginGate>,
    );
    expect(await screen.findByText("The server is not answering")).toBeInTheDocument();
  });
});

describe("api client", () => {
  it("announces a 401 from any non-auth request", async () => {
    mockApi({
      "GET /api/workbooks": () => jsonError(401, "Sign in to continue."),
      "POST /api/auth/login": () => jsonError(401, "That password is not right."),
    });
    const heard = vi.fn();
    window.addEventListener(UNAUTHENTICATED_EVENT, heard);
    await expect(apiGet("/workbooks")).rejects.toMatchObject({ status: 401 });
    await waitFor(() => expect(heard).toHaveBeenCalledTimes(1));
    const { login } = await import("@/api/auth");
    await expect(login("x")).rejects.toMatchObject({ status: 401 });
    expect(heard).toHaveBeenCalledTimes(1); // a wrong password is not an expired session
    window.removeEventListener(UNAUTHENTICATED_EVENT, heard);
  });
});
