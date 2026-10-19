import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

vi.mock("../api/client", () => ({
  getConsent: vi.fn(),
  recordConsent: vi.fn(),
  errorMessage: (e, fallback) => e?.response?.data?.detail || fallback,
}));

import * as api from "../api/client";
import SharingConsent from "./SharingConsent";

afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe("SharingConsent", () => {
  it("starts unticked when nothing is on the ledger and records a grant", async () => {
    api.getConsent.mockResolvedValue({ effective: {} });
    api.recordConsent.mockResolvedValue({});
    render(<SharingConsent patientId="p1" />);
    const box = await screen.findByRole("checkbox");
    await waitFor(() => expect(box.disabled).toBe(false));
    expect(box.checked).toBe(false);

    fireEvent.click(box);
    await waitFor(() => expect(box.checked).toBe(true));
    expect(api.recordConsent).toHaveBeenCalledWith("p1", "cross_facility_sharing", true, expect.any(String));
  });

  it("stays ticked-off and shows the server's reason when the role may not record consent", async () => {
    api.getConsent.mockResolvedValue({ effective: { cross_facility_sharing: false } });
    api.recordConsent.mockRejectedValue({ response: { data: { detail: "Not permitted" } } });
    render(<SharingConsent patientId="p1" />);
    const box = await screen.findByRole("checkbox");
    await waitFor(() => expect(box.disabled).toBe(false));
    fireEvent.click(box);
    await screen.findByText("Not permitted");
    expect(box.checked).toBe(false);
  });
});
