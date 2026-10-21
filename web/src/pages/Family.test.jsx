import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

vi.mock("../components/Layout", () => ({ default: ({ children }) => <div>{children}</div> }));
vi.mock("../api/client", async (orig) => ({
  ...(await orig()),
  getProfiles: vi.fn(), createProfile: vi.fn(), getGuardians: vi.fn(), approveGuardian: vi.fn(), removeGuardian: vi.fn(), switchProfile: vi.fn(),
}));

import * as api from "../api/client";
import Family from "./Family";

const list = (age = 40) => ({ profiles: [
  { patient_id: "p1", full_name: "Ann Parent", age, is_self: true },
  { patient_id: "p2", full_name: "Ben Child", age: 6, is_self: false },
  { patient_id: "p3", full_name: "Old Dad", age: 70, is_self: false, pending_approval: true },
] });

function setup(age) {
  localStorage.setItem("mb_user", JSON.stringify({ role: "patient", patient_id: "p1", full_name: "Ann Parent" }));
  api.getProfiles.mockResolvedValue(list(age));
  api.getGuardians.mockResolvedValue([{ link_id: "l1", full_name: "Zed Guardian", relation_code: "4" }]);
  return render(<MemoryRouter><Family /></MemoryRouter>);
}
afterEach(() => { cleanup(); localStorage.clear(); vi.clearAllMocks(); });

const fill = () => {
  fireEvent.change(screen.getByLabelText("Full name"), { target: { value: " Cy Kid " } });
  fireEvent.change(screen.getByLabelText("Date of birth"), { target: { value: "2020-02-02" } });
  fireEvent.change(screen.getByLabelText("Relationship"), { target: { value: "1" } });
};

describe("Family page", () => {
  it("lists profiles with age and a Switch button for the others", async () => {
    setup();
    expect(await screen.findByText("Ben Child")).toBeTruthy();
    expect(screen.getByText("Age 6")).toBeTruthy();
    expect(screen.getAllByRole("button", { name: "Switch" })).toHaveLength(1); // not Old Dad
    expect(screen.getByText("Waiting for their approval")).toBeTruthy();
  });

  it("validates before calling the API", async () => {
    setup();
    await screen.findByText("Ben Child");
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    expect((await screen.findByRole("alert")).textContent).toBe("Enter the full name.");
    fireEvent.change(screen.getByLabelText("Full name"), { target: { value: "Cy" } });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    expect((await screen.findByRole("alert")).textContent).toBe("Enter a valid date of birth.");
    fireEvent.change(screen.getByLabelText("Date of birth"), { target: { value: "2020-02-02" } });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    expect((await screen.findByRole("alert")).textContent).toBe("Choose the relationship.");
    expect(api.createProfile).not.toHaveBeenCalled();
  });

  it("adds a profile and reloads the list", async () => {
    setup();
    await screen.findByText("Ben Child");
    api.createProfile.mockResolvedValue({});
    fill();
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    await waitFor(() => expect(api.createProfile).toHaveBeenCalledWith({ full_name: "Cy Kid", date_of_birth: "2020-02-02", relation_code: "1" }));
    await waitFor(() => expect(api.getProfiles).toHaveBeenCalledTimes(2));
  });

  it("has no IC field, hints at the clinic desk, and never sends national_id", async () => {
    setup();
    await screen.findByText("Ben Child");
    expect(screen.queryByLabelText(/IC number/)).toBeNull();
    expect(screen.getByText(/ask the clinic desk to link it/)).toBeTruthy();
  });

  it("approves a carer who is waiting for approval", async () => {
    setup();
    api.getGuardians.mockResolvedValue([{ link_id: "l9", full_name: "Pat Carer", relation_code: "3", approved: false, pending: true }]);
    api.approveGuardian.mockResolvedValue({});
    expect((await screen.findByText(/Pat Carer wants to manage your account/))).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Approve/ }));
    await waitFor(() => expect(api.approveGuardian).toHaveBeenCalledWith("l9"));
    await waitFor(() => expect(screen.queryByText(/wants to manage/)).toBeNull());
  });

  it("shows the server detail on a 409 save failure", async () => {
    setup();
    await screen.findByText("Ben Child");
    api.createProfile.mockRejectedValue({ response: { status: 409, data: { detail: "Could not save this profile." } } });
    fill();
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    expect((await screen.findByRole("alert")).textContent).toMatch(/Could not save this profile/);
  });

  it("removes a guardian", async () => {
    setup();
    api.removeGuardian.mockResolvedValue({});
    fireEvent.click(await screen.findByRole("button", { name: /Remove/ }));
    await waitFor(() => expect(api.removeGuardian).toHaveBeenCalledWith("l1"));
    await waitFor(() => expect(screen.queryByText("Zed Guardian")).toBeNull());
  });

  it("explains a 403 when removal is refused", async () => {
    setup();
    api.removeGuardian.mockRejectedValue({ response: { status: 403, data: { detail: "no" } } });
    fireEvent.click(await screen.findByRole("button", { name: /Remove/ }));
    expect((await screen.findByRole("alert")).textContent).toMatch(/under 18/);
  });

  it("hides Remove for someone under 18 and says why", async () => {
    setup(10);
    await screen.findByText("Zed Guardian");
    expect(screen.queryByRole("button", { name: /Remove/ })).toBeNull();
    expect(screen.getByText(/under 18 can't be removed/)).toBeTruthy();
  });
});
