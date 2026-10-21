import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

vi.mock("../api/client", async (orig) => ({ ...(await orig()), scanEmergencyCard: vi.fn(), refreshAccessToken: vi.fn() }));

import * as api from "../api/client";
import App from "../App";
import EmergencyPublic from "./EmergencyPublic";

const pub = { tier: "public", full_name: null, age: null, allergies: [{ substance: "Penicillin", severity: "severe", reaction: "Anaphylaxis" }], conditions: [], family_notification: "secret-note" };
const resp = { ...pub, tier: "responder", full_name: "Ann Lee", age: 40, blood_type: "O+", emergency_contact: { name: "Bob Lee", relationship: "Husband", phone: "+60123" }, conditions: ["Asthma"] };

function at(path) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/e/:ref" element={<EmergencyPublic />} />
      </Routes>
    </MemoryRouter>,
  );
}
const tick = (ms = 1100) => act(async () => { await vi.advanceTimersByTimeAsync(ms); });
const setVisibility = (v) => {
  Object.defineProperty(document, "visibilityState", { configurable: true, get: () => v });
  document.dispatchEvent(new Event("visibilitychange"));
};

beforeEach(() => vi.useFakeTimers({ shouldAdvanceTime: true }));
afterEach(() => {
  cleanup(); vi.clearAllMocks(); vi.useRealTimers(); localStorage.clear();
  delete document.visibilityState; delete document.prerendering;
});

describe("EmergencyPublic", () => {
  it("public tier: call buttons, allergies, empty list wording, sign-in link, no name or notification", async () => {
    api.scanEmergencyCard.mockResolvedValue(pub);
    at("/e/REF1");
    await tick();
    expect(await screen.findByText("Penicillin")).toBeTruthy();
    expect(api.scanEmergencyCard).toHaveBeenCalledWith("REF1");
    expect(screen.getByRole("link", { name: "Call 999" }).getAttribute("href")).toBe("tel:999");
    expect(screen.getByRole("link", { name: "Call 112" }).getAttribute("href")).toBe("tel:112");
    expect(screen.getByText("None recorded as critical")).toBeTruthy();
    expect(screen.getByRole("link", { name: /Responder\? Sign in/ }).getAttribute("href")).toBe("/login?next=%2Fe%2FREF1");
    expect(document.body.textContent).not.toContain("secret-note");
    expect(screen.getByRole("link", { name: "Get the CLARION app" }).getAttribute("href")).toBe("/get-app.html");
  });

  it("responder tier shows name, blood type and a tap-to-call contact; no sign-in prompt", async () => {
    api.scanEmergencyCard.mockResolvedValue(resp);
    at("/e/REF1");
    await tick();
    expect(await screen.findByText("Ann Lee")).toBeTruthy();
    expect(screen.getByText("O+")).toBeTruthy();
    expect(screen.getByRole("link", { name: /\+60123/ }).getAttribute("href")).toBe("tel:+60123");
    expect(screen.queryByText(/Sign in to see more/)).toBeNull();
    expect(document.body.textContent).not.toContain("secret-note");
  });

  it("404 shows the invalid-card message and keeps Call 999", async () => {
    api.scanEmergencyCard.mockRejectedValue({ response: { status: 404, data: { detail: "Invalid or expired emergency card" } } });
    at("/e/BAD");
    await tick();
    expect((await screen.findByRole("alert")).textContent).toMatch(/not valid or has expired.*call 999/);
    expect(screen.getByRole("link", { name: "Call 999" })).toBeTruthy();
  });

  it("network error shows a friendly message and Retry reloads immediately", async () => {
    api.scanEmergencyCard.mockRejectedValueOnce(new Error("Network Error")).mockResolvedValueOnce(pub);
    at("/e/REF1");
    await tick();
    expect((await screen.findByRole("alert")).textContent).toMatch(/Could not load. Call 999 now./);
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("Penicillin")).toBeTruthy();
  });

  it("sets then removes the privacy meta tags and keeps the ref out of the title", () => {
    api.scanEmergencyCard.mockResolvedValue(pub);
    const { unmount } = at("/e/SECRETREF");
    expect(document.querySelector('meta[name="robots"]').content).toBe("noindex");
    expect(document.querySelector('meta[name="referrer"]').content).toBe("no-referrer");
    expect(document.title).not.toContain("SECRETREF");
    unmount();
    expect(document.querySelector('meta[name="robots"]')).toBeNull();
  });

  it("does not scan before the page has stayed visible for about a second, and scans once", async () => {
    api.scanEmergencyCard.mockResolvedValue(pub);
    at("/e/REF1");
    expect(screen.getByRole("link", { name: "Call 999" })).toBeTruthy(); // there while loading
    await tick(500);
    expect(api.scanEmergencyCard).not.toHaveBeenCalled();
    await tick(700);
    expect(api.scanEmergencyCard).toHaveBeenCalledTimes(1);
    await tick(5000);
    expect(api.scanEmergencyCard).toHaveBeenCalledTimes(1);
  });

  it("never scans while prerendering", async () => {
    Object.defineProperty(document, "prerendering", { configurable: true, value: true });
    api.scanEmergencyCard.mockResolvedValue(pub);
    at("/e/REF1");
    await tick(5000);
    expect(api.scanEmergencyCard).not.toHaveBeenCalled();
  });

  it("waits while hidden, cancels the timer if hidden mid-wait, and re-arms when visible", async () => {
    setVisibility("hidden");
    api.scanEmergencyCard.mockResolvedValue(pub);
    at("/e/REF1");
    await tick(5000);
    expect(api.scanEmergencyCard).not.toHaveBeenCalled();
    setVisibility("visible");
    await tick(600);
    setVisibility("hidden");
    await tick(2000);
    expect(api.scanEmergencyCard).not.toHaveBeenCalled();
    setVisibility("visible");
    await tick(1100);
    expect(api.scanEmergencyCard).toHaveBeenCalledTimes(1);
  });

  it("sanitises the phone number in the tel: link but displays the original", async () => {
    api.scanEmergencyCard.mockResolvedValue({ ...resp, emergency_contact: { name: "B", phone: "+60 12-345 6789;ext=1" } });
    at("/e/REF1");
    await tick();
    const link = await screen.findByRole("link", { name: /\+60 12-345/ });
    expect(link.getAttribute("href")).toBe("tel:+601234567891");
  });

  it("stale token: refreshes once and re-scans once, showing the higher tier", async () => {
    localStorage.setItem("mb_token", "old");
    api.scanEmergencyCard.mockResolvedValueOnce(pub).mockResolvedValueOnce(resp);
    api.refreshAccessToken.mockResolvedValue("new");
    at("/e/REF1");
    await tick();
    expect(await screen.findByText("Ann Lee")).toBeTruthy();
    expect(api.refreshAccessToken).toHaveBeenCalledTimes(1);
    expect(api.scanEmergencyCard).toHaveBeenCalledTimes(2);
  });

  it("stale token and refresh fails: keeps the public view", async () => {
    localStorage.setItem("mb_token", "old");
    api.scanEmergencyCard.mockResolvedValue(pub);
    api.refreshAccessToken.mockRejectedValue(new Error("401"));
    at("/e/REF1");
    await tick();
    expect(await screen.findByText("Penicillin")).toBeTruthy();
    expect(api.scanEmergencyCard).toHaveBeenCalledTimes(1);
    expect(screen.getByText(/Viewing: basic information/)).toBeTruthy();
  });

  it("no token: no refresh attempt", async () => {
    api.scanEmergencyCard.mockResolvedValue(pub);
    at("/e/REF1");
    await tick();
    await screen.findByText("Penicillin");
    expect(api.refreshAccessToken).not.toHaveBeenCalled();
  });

  it("is a public route in the real App (no login redirect), and /e/n/... is not a route", async () => {
    api.scanEmergencyCard.mockResolvedValue(pub);
    window.history.pushState({}, "", "/e/REF9");
    render(<App />);
    await tick();
    expect(await screen.findByText("Penicillin")).toBeTruthy();
    expect(window.location.pathname).toBe("/e/REF9");
  });
});
