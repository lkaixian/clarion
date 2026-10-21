import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";

vi.mock("../api/client", async (orig) => ({
  ...(await orig()),
  getProfiles: vi.fn(),
  switchProfile: vi.fn(),
}));

import * as api from "../api/client";
import ProfileSwitcher, { ActingBanner } from "./ProfileSwitcher";
import Layout from "./Layout";

const own = { access_token: "own-tok", user: { role: "patient", patient_id: "p1", full_name: "Ann Parent", acting_for: false, home_patient_id: "p1" } };
const kid = { access_token: "kid-tok", user: { role: "patient", patient_id: "p2", full_name: "Ben Child", acting_for: true, home_patient_id: "p1" } };
const profiles = { active_patient_id: "p1", profiles: [
  { patient_id: "p1", full_name: "Ann Parent", age: 40, is_self: true },
  { patient_id: "p2", full_name: "Ben Child", age: 6, is_self: false },
  { patient_id: "p3", full_name: "Old Dad", age: 70, is_self: false, pending_approval: true },
] };

const login = (s) => { localStorage.setItem("mb_token", s.access_token); localStorage.setItem("mb_user", JSON.stringify(s.user)); };
const Where = () => <p data-testid="where">{useLocation().pathname}</p>;
const ui = (children) => render(
  <MemoryRouter initialEntries={["/family"]}>
    <Routes><Route path="*" element={<>{children}<Where /></>} /></Routes>
  </MemoryRouter>,
);
const inMenu = (el) => !!el?.closest("#profile-menu");

beforeEach(() => {
  api.getProfiles.mockResolvedValue(profiles);
  api.switchProfile.mockImplementation(async (id) => { const s = id === "p2" ? kid : own; login(s); return s; });
});
afterEach(() => { cleanup(); localStorage.clear(); sessionStorage.clear(); vi.clearAllMocks(); });

describe("ProfileSwitcher", () => {
  it("renders nothing for staff", () => {
    login({ access_token: "t", user: { role: "clinician", full_name: "Dr X" } });
    ui(<ProfileSwitcher />);
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("lists profiles with You marked and moves focus into the menu", async () => {
    login(own);
    ui(<ProfileSwitcher />);
    fireEvent.click(screen.getByRole("button", { name: /Ann Parent/ }));
    const ben = await screen.findByRole("button", { name: "Ben Child" });
    expect(screen.getByText("You")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Add a family member" })).toBeTruthy();
    await waitFor(() => expect(inMenu(document.activeElement)).toBe(true));
    fireEvent.keyDown(ben, { key: "Escape" });
    expect(screen.queryByRole("button", { name: "Ben Child" })).toBeNull();
    expect(document.activeElement).toBe(screen.getByRole("button", { name: /Ann Parent/ }));
  });

  it("disables a profile that is waiting for approval", async () => {
    login(own);
    ui(<ProfileSwitcher />);
    fireEvent.click(screen.getByRole("button", { name: /Ann Parent/ }));
    const dad = await screen.findByRole("button", { name: /Old Dad/ });
    expect(dad.disabled).toBe(true);
    expect(dad.textContent).toContain("Waiting for their approval");
  });

  it("shows the server's refusal when a switch is denied", async () => {
    login(own);
    api.switchProfile.mockRejectedValue({ response: { status: 403, data: { detail: "Waiting for their approval." } } });
    ui(<ProfileSwitcher />);
    fireEvent.click(screen.getByRole("button", { name: /Ann Parent/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Ben Child" }));
    expect((await screen.findByRole("alert")).textContent).toBe("Waiting for their approval.");
  });

  it("switches: calls the API, stores the new token and user, goes to that patient's home", async () => {
    login(own);
    ui(<ProfileSwitcher />);
    fireEvent.click(screen.getByRole("button", { name: /Ann Parent/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Ben Child" }));
    await waitFor(() => expect(screen.getByTestId("where").textContent).toBe("/patients/p2"));
    expect(api.switchProfile).toHaveBeenCalledWith("p2");
    expect(localStorage.getItem("mb_token")).toBe("kid-tok");
    expect(JSON.parse(localStorage.getItem("mb_user")).patient_id).toBe("p2");
  });
});

describe("ActingBanner", () => {
  it("is hidden on your own profile", () => {
    login(own);
    ui(<ActingBanner />);
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("shows who you act for and goes back to your own profile", async () => {
    login(kid);
    ui(<ActingBanner />);
    expect(screen.getByRole("status").textContent).toContain("Ben Child");
    fireEvent.click(screen.getByRole("button", { name: "Back to my profile" }));
    await waitFor(() => expect(api.switchProfile).toHaveBeenCalledWith("p1"));
    await waitFor(() => expect(screen.getByTestId("where").textContent).toBe("/patients/p1"));
    expect(localStorage.getItem("mb_token")).toBe("own-tok");
  });

  it("shows a one-time notice when the link was removed", () => {
    login(own);
    sessionStorage.setItem("mb_notice", "You can no longer act for this profile");
    ui(<ActingBanner />);
    expect(screen.getByRole("status").textContent).toContain("no longer act");
    expect(sessionStorage.getItem("mb_notice")).toBeNull();
  });
});

describe("Layout while acting", () => {
  it("hides the Security link and explains why", () => {
    login(kid);
    ui(<Layout>x</Layout>);
    expect(screen.queryByRole("link", { name: "Security" })).toBeNull();
    expect(screen.getAllByText(/Account settings are available on your own profile/).length).toBeGreaterThan(0);
  });

  it("keeps the Security link on your own profile", () => {
    login(own);
    ui(<Layout>x</Layout>);
    expect(screen.getByRole("link", { name: "Security" })).toBeTruthy();
  });
});
