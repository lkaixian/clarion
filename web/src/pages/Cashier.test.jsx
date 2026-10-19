import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";

vi.mock("../components/Layout", () => ({ default: ({ children }) => <div>{children}</div> }));
vi.mock("../api/client", () => ({
  getReconciliation: vi.fn(), getReconciliationPdf: vi.fn(), getOutstanding: vi.fn(), listRefunds: vi.fn(), approveRefund: vi.fn(),
  rejectRefund: vi.fn(), listDeposits: vi.fn(), createDeposit: vi.fn(), applyDeposit: vi.fn(),
  refundDeposit: vi.fn(), listPatients: vi.fn(), listBills: vi.fn(), getCurrentUser: vi.fn(),
  errorMessage: (e, fb) => e?.response?.data?.detail || fb,
}));

import * as api from "../api/client";
import Cashier from "./Cashier";

const rec = {
  collected_cents: 3500, net_cents: 3100, by_method: { cash: { count: 1, total_cents: 1000 }, online: { count: 1, total_cents: 2500 } },
  by_cashier: [{ name: "Cashier One", count: 1, total_cents: 1000 }, { name: "Online payment", count: 1, total_cents: 2500 }],
  voided: { count: 1, total_cents: 700 }, refunds: { count: 1, total_cents: 400 },
  deposits_received: { count: 0, total_cents: 0 }, applied_from_deposits: { count: 2, total_cents: 800 }, deposit_refunds: { count: 1, total_cents: 250 }, online_pending: { count: 1, total_cents: 1500 },
};
const refund = (over = {}) => ({ id: "r1", amount_cents: 2000, reason: "duplicate charge", status: "requested",
  requested_by_name: "Cashier One", requested_at: "2026-10-12T01:00:00Z", ...over });

afterEach(() => { cleanup(); vi.clearAllMocks(); vi.restoreAllMocks(); });

function open(role = "receptionist") {
  api.getCurrentUser.mockReturnValue({ role });
  api.getReconciliation.mockResolvedValue(rec);
  return render(<Cashier />);
}
const tab = (name) => fireEvent.click(screen.getByRole("tab", { name }));

describe("Cashier day close", () => {
  it("shows totals by method and cashier, and flags voids and pending online payments", async () => {
    open();
    expect(await screen.findByText("RM 35.00")).toBeTruthy(); // collected
    expect(screen.getByText("RM 31.00")).toBeTruthy(); // net
    expect(screen.getByText("Cashier One")).toBeTruthy();
    expect(screen.getByText(/Voided: 1 \(RM 7.00\)/)).toBeTruthy();
    expect(screen.getByText(/waiting for the gateway: 1 \(RM 15.00\)/)).toBeTruthy();
    expect(screen.getByText(/Paid from deposits: 2 \(RM 8.00\), not new cash/)).toBeTruthy();
    expect(screen.getByText(/Deposit refunds: 1 \(RM 2.50\), already netted/)).toBeTruthy();
    const arg = api.getReconciliation.mock.calls[0][0];
    expect(arg.day).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    expect(typeof arg.tzOffsetMinutes).toBe("number");
  });

  it("re-queries when the day changes and handles an empty day", async () => {
    open();
    await screen.findByText("RM 35.00");
    api.getReconciliation.mockResolvedValue({ ...rec, collected_cents: 0, net_cents: 0, by_method: {}, by_cashier: [] });
    fireEvent.change(screen.getByLabelText("Day"), { target: { value: "2026-01-02" } });
    expect(await screen.findByText("No payments were taken on this day.")).toBeTruthy();
    expect(api.getReconciliation.mock.calls.at(-1)[0].day).toBe("2026-01-02");
  });

  it("offers 1d to 6 months and asks the server for that many days", async () => {
    open();
    await screen.findByText("RM 35.00");
    fireEvent.change(screen.getByLabelText("Day"), { target: { value: "2026-10-13" } });
    const days = async (name) => {
      fireEvent.click(screen.getByRole("button", { name }));
      await waitFor(() => expect(api.getReconciliation.mock.calls.at(-1)[0].days).toBeGreaterThan(0));
      return api.getReconciliation.mock.calls.at(-1)[0].days;
    };
    expect(await days("7 days")).toBe(7);
    expect(await days("14 days")).toBe(14);
    expect(await days("30 days")).toBe(30);
    expect(await days("3 months")).toBe(92); // starts 2026-07-14
    expect(await days("6 months")).toBe(183); // starts 2026-04-14
    expect(await days("1 day")).toBe(1);
  });

  it("downloads the PDF for the chosen period", async () => {
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    URL.createObjectURL = vi.fn(() => "blob:x");
    URL.revokeObjectURL = vi.fn();
    api.getReconciliationPdf.mockResolvedValue(new Blob(["%PDF"]));
    open();
    await screen.findByText("RM 35.00");
    fireEvent.click(screen.getByRole("button", { name: "7 days" }));
    await waitFor(() => expect(api.getReconciliation.mock.calls.at(-1)[0].days).toBe(7));
    fireEvent.click(screen.getByRole("button", { name: "Download PDF" }));
    await waitFor(() => expect(click).toHaveBeenCalled());
    expect(api.getReconciliationPdf.mock.calls[0][0].days).toBe(7);
  });

  it("shows the server error", async () => {
    api.getCurrentUser.mockReturnValue({ role: "receptionist" });
    api.getReconciliation.mockRejectedValue({ response: { data: { detail: "Requires one of roles" } } });
    render(<Cashier />);
    expect((await screen.findByRole("alert")).textContent).toBe("Requires one of roles");
  });
});

describe("Cashier outstanding", () => {
  it("shows ageing buckets and the oldest bills", async () => {
    open();
    api.getOutstanding.mockResolvedValue({
      total_cents: 15000,
      buckets: [{ label: "0-30", count: 1, total_cents: 5000 }, { label: "31-60", count: 0, total_cents: 0 },
                { label: "61-90", count: 0, total_cents: 0 }, { label: "90+", count: 1, total_cents: 10000 }],
      bills: [{ bill_id: "b1", patient_full_name: "Old Debtor", finalized_at: "2026-03-01T00:00:00Z", age_days: 200,
                amount_due_cents: 10000, patient_due_cents: 10000 }],
    });
    tab("Outstanding");
    expect(await screen.findByText("Old Debtor")).toBeTruthy();
    expect(screen.getByText("RM 150.00")).toBeTruthy();
    expect(screen.getByText("200 days")).toBeTruthy();
    expect(screen.getByText("90+ days (1)")).toBeTruthy();
  });

  it("says when nothing is owed", async () => {
    open();
    api.getOutstanding.mockResolvedValue({ total_cents: 0, buckets: [], bills: [] });
    tab("Outstanding");
    expect(await screen.findByText("No unpaid bills.")).toBeTruthy();
  });
});

describe("Cashier refunds", () => {
  it("lets an admin approve with a note and refreshes the list", async () => {
    open("admin");
    api.listRefunds.mockResolvedValue([refund()]);
    api.approveRefund.mockResolvedValue({});
    vi.spyOn(window, "prompt").mockReturnValue("ok per policy");
    tab("Refunds");
    fireEvent.click(await screen.findByText("Approve"));
    await waitFor(() => expect(api.approveRefund).toHaveBeenCalledWith("r1", "ok per policy"));
    expect(await screen.findByText("Refund approved.")).toBeTruthy();
    expect(api.listRefunds.mock.calls.length).toBe(2);
    expect(api.listRefunds.mock.calls[0][0]).toBe("requested");
  });

  it("requires a reason to reject and shows a server refusal (own request)", async () => {
    open("admin");
    api.listRefunds.mockResolvedValue([refund()]);
    api.approveRefund.mockRejectedValue({ response: { data: { detail: "A different admin must approve your own refund request" } } });
    const prompt = vi.spyOn(window, "prompt").mockReturnValue("");
    tab("Refunds");
    fireEvent.click(await screen.findByText("Reject"));
    expect(api.rejectRefund).not.toHaveBeenCalled(); // empty reason: nothing sent
    prompt.mockReturnValue("");
    fireEvent.click(screen.getByText("Approve"));
    expect((await screen.findByText(/different admin must approve/))).toBeTruthy();
  });

  it("hides approve and reject from non-admins", async () => {
    open("receptionist");
    api.listRefunds.mockResolvedValue([refund()]);
    tab("Refunds");
    expect(await screen.findByText("duplicate charge", { exact: false })).toBeTruthy();
    expect(screen.queryByText("Approve")).toBeNull();
    expect(screen.getByText(/Only an admin can approve/)).toBeTruthy();
  });
});

describe("Cashier deposits", () => {
  const dep = { id: "d1", patient_id: "p1", patient_full_name: "Pat Ient", amount_cents: 10000, applied_cents: 0, refunded_cents: 0, balance_cents: 10000,
                method: "cash", received_by_name: "Cashier One", received_at: "2026-10-12T01:00:00Z" };
  function deposits(role = "receptionist") {
    open(role);
    api.listPatients.mockResolvedValue([{ id: "p1", full_name: "Pat Ient" }]);
    api.listDeposits.mockResolvedValue([dep]);
    tab("Deposits");
  }

  it("lists deposits with the patient name and records a new one", async () => {
    deposits();
    expect(await screen.findByText(/Pat Ient .* balance RM 100.00/)).toBeTruthy();
    api.createDeposit.mockResolvedValue({});
    await waitFor(() => expect(within(screen.getByLabelText("Patient")).getAllByRole("option").length).toBe(2));
    fireEvent.change(screen.getByLabelText("Patient"), { target: { value: "p1" } });
    fireEvent.change(screen.getByLabelText("Amount (RM)"), { target: { value: "200" } });
    fireEvent.click(screen.getByText("Record deposit"));
    await waitFor(() => expect(api.createDeposit).toHaveBeenCalledWith({
      patient_id: "p1", amount_cents: 20000, method: "cash", reference_no: undefined }));
    expect(await screen.findByText("Deposit recorded.")).toBeTruthy();
  });

  it("falls back to a patient ID field for roles that cannot browse patients", async () => {
    open("receptionist");
    api.listPatients.mockRejectedValue({ response: { status: 403 } });
    api.listDeposits.mockResolvedValue([{ ...dep, patient_full_name: "Pat Ient" }]);
    api.createDeposit.mockResolvedValue({});
    tab("Deposits");
    const field = await screen.findByLabelText("Patient ID (from Reception check-in)");
    expect(field.tagName).toBe("INPUT");
    expect(await screen.findByText(/Pat Ient .* balance RM 100.00/)).toBeTruthy(); // name comes from the API row
    fireEvent.click(screen.getByText("Record deposit"));
    expect(await screen.findByText("Enter the patient ID.")).toBeTruthy();
    fireEvent.change(field, { target: { value: " p-77 " } });
    fireEvent.change(screen.getByLabelText("Amount (RM)"), { target: { value: "50" } });
    fireEvent.click(screen.getByText("Record deposit"));
    await waitFor(() => expect(api.createDeposit).toHaveBeenCalledWith({
      patient_id: "p-77", amount_cents: 5000, method: "cash", reference_no: undefined }));
  });

  it("validates the form before calling the server", async () => {
    deposits();
    await screen.findByText(/balance RM 100.00/);
    fireEvent.click(screen.getByText("Record deposit"));
    expect(await screen.findByText("Choose a patient.")).toBeTruthy();
    await waitFor(() => expect(within(screen.getByLabelText("Patient")).getAllByRole("option").length).toBe(2));
    fireEvent.change(screen.getByLabelText("Patient"), { target: { value: "p1" } });
    fireEvent.change(screen.getByLabelText("Amount (RM)"), { target: { value: "1.234" } });
    fireEvent.click(screen.getByText("Record deposit"));
    expect(await screen.findByText(/Enter an amount in RM/)).toBeTruthy();
    expect(api.createDeposit).not.toHaveBeenCalled();
  });

  it("applies a deposit to the only open bill, capped at the amount due", async () => {
    deposits();
    api.listBills.mockResolvedValue([{ id: "b1", status: "finalized", amount_due_cents: 4000, created_at: "2026-10-01T00:00:00Z" }]);
    api.applyDeposit.mockResolvedValue({});
    fireEvent.click(await screen.findByText("Apply to bill"));
    await waitFor(() => expect(api.applyDeposit).toHaveBeenCalledWith("d1", { bill_id: "b1", amount_cents: 4000 }));
    expect(await screen.findByText("RM 40.00 applied to the bill.")).toBeTruthy();
  });

  it("tells the cashier when the patient has nothing to apply it to", async () => {
    deposits();
    api.listBills.mockResolvedValue([{ id: "b1", status: "voided", amount_due_cents: 4000 }]);
    fireEvent.click(await screen.findByText("Apply to bill"));
    expect(await screen.findByText("This patient has no bill with a balance.")).toBeTruthy();
    expect(api.applyDeposit).not.toHaveBeenCalled();
  });

  it("offers deposit refunds to admins only, after confirmation", async () => {
    deposits("receptionist");
    await screen.findByText(/balance RM 100.00/);
    expect(screen.queryByText("Refund balance")).toBeNull();
    cleanup();
    deposits("admin");
    api.refundDeposit.mockResolvedValue({});
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    fireEvent.click(await screen.findByText("Refund balance"));
    expect(api.refundDeposit).not.toHaveBeenCalled();
    confirm.mockReturnValue(true);
    fireEvent.click(screen.getByText("Refund balance"));
    await waitFor(() => expect(api.refundDeposit).toHaveBeenCalledWith("d1", {}));
  });
});
