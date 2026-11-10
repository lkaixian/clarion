import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

vi.mock("../api/client", () => ({
  getMyDirectives: vi.fn(),
  putMyDirective: vi.fn(),
  getPatientDirectives: vi.fn(),
  addPatientDirective: vi.fn(),
  errorMessage: (e, fallback) => e?.response?.data?.detail || fallback,
}));

import * as api from "../api/client";
import CriticalDirectives, { DirectivesBlock } from "./CriticalDirectives";

afterEach(() => { cleanup(); vi.clearAllMocks(); });

const row = { id: "1", kind: "organ_donation", value: "yes", note: null, source: "patient", evidence_ref: null,
  recorded_by_name: "Ann", recorded_by_role: "patient", recorded_by_facility: null, recorded_at: "2026-01-01T10:00:00" };

describe("CriticalDirectives", () => {
  it("patient saves their own declaration without a form number", async () => {
    api.getMyDirectives.mockResolvedValue({ current: [row], history: [row] });
    api.putMyDirective.mockResolvedValue({});
    render(<CriticalDirectives mode="self" />);
    await screen.findByText("patient-declared", { exact: false });
    fireEvent.change(screen.getAllByRole("combobox")[1], { target: { value: "no" } });
    fireEvent.click(screen.getByText("Save"));
    await waitFor(() => expect(api.putMyDirective).toHaveBeenCalledWith("organ_donation", { value: "no", note: null }));
    expect(screen.queryByText("Signed form number")).toBeNull();
  });

  it("staff must enter the form number", async () => {
    api.getPatientDirectives.mockResolvedValue({ current: [], history: [] });
    api.addPatientDirective.mockResolvedValue({});
    render(<CriticalDirectives mode="staff" patientId="p1" />);
    await screen.findByText("Signed form number");
    fireEvent.click(screen.getByText("Save"));
    await screen.findByText("Enter the signed form number.");
    expect(api.addPatientDirective).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("Signed form number"), { target: { value: "F-9" } });
    fireEvent.click(screen.getByText("Save"));
    await waitFor(() => expect(api.addPatientDirective).toHaveBeenCalledWith("p1", { value: "undecided", note: null, kind: "organ_donation", evidence_ref: "F-9" }));
  });

  it("emergency block shows the source label and the not-legal-proof line", () => {
    render(<DirectivesBlock items={[
      { kind: "organ_donation", value: "yes", source: "patient", label: "patient-declared" },
      { kind: "blood_transfusion", value: "no", source: "staff", label: "recorded by staff (form BT-7)" },
    ]} />);
    expect(screen.getByText("patient-declared")).toBeTruthy();
    expect(screen.getByText("recorded by staff (form BT-7)")).toBeTruthy();
    expect(screen.getByText(/not legal proof/)).toBeTruthy();
  });
});
