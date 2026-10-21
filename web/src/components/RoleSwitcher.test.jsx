import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";

vi.mock("../api/client", async (orig) => ({ ...(await orig()), switchRole: vi.fn() }));

import * as api from "../api/client";
import RoleSwitcher from "./RoleSwitcher";

const patient = { access_token: "pat-tok", user: { role: "patient", roles: ["patient", "clinician"], patient_id: "p1", full_name: "Nia Nurse" } };
const clin = { access_token: "clin-tok", user: { role: "clinician", roles: ["patient", "clinician"], full_name: "Nia Nurse", allowed_pages: ["patients"] } };

const login = (s) => { localStorage.setItem("mb_token", s.access_token); localStorage.setItem("mb_user", JSON.stringify(s.user)); };
const Where = () => <p data-testid="where">{useLocation().pathname}</p>;
const ui = () => render(
  <MemoryRouter initialEntries={["/family"]}>
    <Routes><Route path="*" element={<><RoleSwitcher /><Where /></>} /></Routes>
  </MemoryRouter>,
);

beforeEach(() => {
  api.switchRole.mockImplementation(async (role) => { const s = role === "clinician" ? clin : patient; login(s); return s; });
});
afterEach(() => { cleanup(); localStorage.clear(); vi.clearAllMocks(); });

describe("RoleSwitcher", () => {
  it("renders nothing for a single-role account", () => {
    login({ access_token: "t", user: { role: "clinician", roles: ["clinician"] } });
    ui();
    expect(screen.queryByRole("combobox")).toBeNull();
  });

  it("lists every role in a labelled select with the active one chosen", () => {
    login(patient);
    ui();
    const sel = screen.getByRole("combobox", { name: "Acting as" });
    expect(sel.value).toBe("patient");
    expect([...sel.options].map((o) => o.textContent)).toEqual(["Patient", "Clinician"]);
  });

  it("switches: calls the API, stores the new session, lands on that role's page", async () => {
    login(patient);
    ui();
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "clinician" } });
    await waitFor(() => expect(screen.getByTestId("where").textContent).toBe("/patients"));
    expect(api.switchRole).toHaveBeenCalledWith("clinician", undefined);
    expect(localStorage.getItem("mb_token")).toBe("clin-tok");
    expect(JSON.parse(localStorage.getItem("mb_user")).role).toBe("clinician");
  });

  it("shows the server's refusal and stays put", async () => {
    login(patient);
    api.switchRole.mockRejectedValue({ response: { status: 403, data: { detail: "You do not hold that role." } } });
    ui();
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "clinician" } });
    expect((await screen.findByRole("alert")).textContent).toBe("You do not hold that role.");
    expect(screen.getByTestId("where").textContent).toBe("/family");
  });

  const need = (needs_code) => ({ response: { status: 428, data: { detail: { detail: "Confirm", reauth_required: true, needs_code } } } });

  it("428 asks for the password, then retries with it and lands on the new role", async () => {
    login(patient);
    api.switchRole.mockRejectedValueOnce(need(false));
    ui();
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "clinician" } });
    const pw = await screen.findByLabelText("Password");
    expect(screen.queryByLabelText("Authenticator code")).toBeNull();
    await waitFor(() => expect(document.activeElement).toBe(pw));
    fireEvent.change(pw, { target: { value: "hunter2hunter2" } });
    fireEvent.click(screen.getByRole("button", { name: "Switch role" }));
    await waitFor(() => expect(screen.getByTestId("where").textContent).toBe("/patients"));
    expect(api.switchRole).toHaveBeenLastCalledWith("clinician", { password: "hunter2hunter2" });
    expect(localStorage.getItem("mb_user")).not.toContain("hunter2");
    expect(screen.queryByLabelText("Password")).toBeNull();
  });

  it("asks for the authenticator code too when the server says so", async () => {
    login(patient);
    api.switchRole.mockRejectedValueOnce(need(true));
    ui();
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "clinician" } });
    fireEvent.change(await screen.findByLabelText("Password"), { target: { value: "pw-pw-pw-pw" } });
    fireEvent.change(screen.getByLabelText("Authenticator code"), { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "Switch role" }));
    await waitFor(() => expect(api.switchRole).toHaveBeenLastCalledWith("clinician", { password: "pw-pw-pw-pw", code: "123456" }));
  });

  it("a wrong password shows the message and keeps the prompt open; Cancel closes it", async () => {
    login(patient);
    api.switchRole.mockRejectedValueOnce(need(false))
      .mockRejectedValueOnce({ response: { status: 400, data: { detail: "Incorrect password." } } });
    ui();
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "clinician" } });
    fireEvent.change(await screen.findByLabelText("Password"), { target: { value: "bad" } });
    fireEvent.click(screen.getByRole("button", { name: "Switch role" }));
    expect((await screen.findByRole("alert")).textContent).toBe("Incorrect password.");
    expect(screen.getByLabelText("Password")).toBeTruthy();
    expect(screen.getByTestId("where").textContent).toBe("/family");
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByLabelText("Password")).toBeNull();
    expect(document.activeElement).toBe(screen.getByRole("combobox"));
  });
});
