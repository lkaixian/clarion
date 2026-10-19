import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

vi.mock("../components/Layout", () => ({ default: ({ children }) => <div>{children}</div> }));
vi.mock("../api/client", () => ({
  importChargeMasterFile: vi.fn(), getChargeMasterTemplate: vi.fn(),
  getCurrentUser: vi.fn(() => ({ role: "admin" })),
}));

import * as api from "../api/client";
import { ChargeMasterImport } from "./Billing";

afterEach(() => { cleanup(); vi.clearAllMocks(); });

const file = () => new File(["x"], "cm.xlsx");
const pick = () => fireEvent.change(screen.getByLabelText("Import from Excel"), { target: { files: [file()] } });
const ok = { would_add: 2, skipped_duplicates: 1, error_count: 0, errors: [], added: 0,
  preview: [{ row: 2, name: "Consult", category: "consultation", unit_price_cents: 3000 }] };

describe("Charge master import", () => {
  it("previews first, then commits the same file only on confirm", async () => {
    api.importChargeMasterFile.mockResolvedValueOnce(ok).mockResolvedValueOnce({ ...ok, added: 2 });
    const onDone = vi.fn();
    render(<ChargeMasterImport onDone={onDone} />);
    pick();
    expect(await screen.findByText(/2 new item\(s\), 1 duplicate/)).toBeTruthy();
    expect(api.importChargeMasterFile.mock.calls[0][1]).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Add 2 items" }));
    await waitFor(() => expect(onDone).toHaveBeenCalledWith(2));
    expect(api.importChargeMasterFile.mock.calls[1][1]).toBe(false);
  });

  it("lists row errors and offers no add button", async () => {
    api.importChargeMasterFile.mockResolvedValue({ ...ok, would_add: 1, error_count: 1,
      errors: [{ row: 4, message: "price must be a number" }] });
    render(<ChargeMasterImport onDone={() => {}} />);
    pick();
    expect(await screen.findByText(/Row 4: price must be a number/)).toBeTruthy();
    expect(screen.getByText(/Nothing was added/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /^Add \d/ })).toBeNull();
  });

  it("shows the server message for an unreadable file", async () => {
    api.importChargeMasterFile.mockRejectedValue({ response: { data: { detail: "This is not an .xlsx file." } } });
    render(<ChargeMasterImport onDone={() => {}} />);
    pick();
    expect((await screen.findByRole("alert")).textContent).toMatch(/not an \.xlsx/);
  });
});
