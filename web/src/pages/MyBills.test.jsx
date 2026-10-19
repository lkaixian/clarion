import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

vi.mock("../components/Layout", () => ({ default: ({ children }) => <div>{children}</div> }));
vi.mock("../api/client", () => ({
  getMyBills: vi.fn(), getMyPaymentHistory: vi.fn(), createPaymentIntent: vi.fn(), simulatePayment: vi.fn(),
  cancelPaymentIntent: vi.fn(), getReceipt: vi.fn(), getReceiptPdf: vi.fn(), emailReceipt: vi.fn(),
  errorMessage: (e, fb) => e?.response?.data?.detail || fb,
}));

import * as api from "../api/client";
import MyBills from "./MyBills";

const bill = (over = {}) => ({
  id: "b1", facility_name: "Hospital A", finalized_at: "2026-10-01T02:00:00Z", total_cents: 5000, paid_cents: 0,
  claimed_pending_cents: 0, amount_due_cents: 5000, patient_due_cents: 5000,
  items: [{ description: "Consult", quantity: 1, amount_cents: 5000 }], payments: [], pending_intent: null, ...over,
});
const intent = (over = {}) => ({ id: "i1", bill_id: "b1", amount_cents: 5000, status: "pending", simulated: true, ...over });
const receipt = { receipt_no: "AB12CD34", payment_id: "pay1", facility_name: "Hospital A", received_at: "2026-10-12T03:00:00Z",
  patient_full_name: "Pat Ient", amount_cents: 5000, method: "online", reference_no: "MOCK-1", refunded_cents: 0,
  bill_balance_after_cents: 0, bill_total_cents: 5000, voided: false, items: [{ description: "Consult", quantity: 1, amount_cents: 5000 }] };

afterEach(() => { cleanup(); vi.clearAllMocks(); });

function setup(bills = [bill()], history = []) {
  api.getMyBills.mockResolvedValue(bills);
  api.getMyPaymentHistory.mockResolvedValue(history);
  return render(<MyBills />);
}

describe("MyBills", () => {
  it("shows loading, then the amount to pay", async () => {
    setup();
    expect(screen.getByText("Loading...")).toBeTruthy();
    expect(await screen.findByText("Hospital A")).toBeTruthy();
    expect(screen.getAllByText("RM 50.00").length).toBeGreaterThanOrEqual(2); // total and amount to pay
    expect(screen.getByText("to pay")).toBeTruthy();
  });

  it("explains a bill that is paid or waiting on insurance", async () => {
    setup([bill({ id: "paid", paid_cents: 5000, amount_due_cents: 0, patient_due_cents: 0 }),
           bill({ id: "ins", facility_name: "Clinic B", claimed_pending_cents: 5000, patient_due_cents: 0 })]);
    expect(await screen.findByText("paid in full")).toBeTruthy();
    expect(screen.getByText("waiting on your insurer")).toBeTruthy();
    expect(screen.queryByText("Pay now")).toBeNull();
  });

  it("has an empty and an error state", async () => {
    setup([]);
    expect(await screen.findByText("You have no bills.")).toBeTruthy();
    cleanup();
    api.getMyBills.mockRejectedValue({ response: { data: { detail: "Down for maintenance" } } });
    api.getMyPaymentHistory.mockResolvedValue([]);
    render(<MyBills />);
    expect((await screen.findByRole("alert")).textContent).toBe("Down for maintenance");
  });

  it("pays in full through the simulated gateway and shows the receipt", async () => {
    setup();
    api.createPaymentIntent.mockResolvedValue(intent());
    api.simulatePayment.mockResolvedValue({ ...intent(), status: "succeeded", payment_id: "pay1" });
    api.getReceipt.mockResolvedValue(receipt);
    fireEvent.click(await screen.findByText("Pay now"));
    expect(screen.getByLabelText("Amount to pay (RM)").value).toBe("50.00");
    fireEvent.click(screen.getByText("Continue"));
    expect(await screen.findByText(/no real money moves/)).toBeTruthy();
    const [billId, body] = api.createPaymentIntent.mock.calls[0];
    expect(billId).toBe("b1");
    expect(body.amount_cents).toBe(5000);
    expect(typeof body.idempotency_key).toBe("string");
    expect(body.idempotency_key.length).toBeGreaterThanOrEqual(8);
    fireEvent.click(screen.getByText("Approve payment"));
    expect(await screen.findByText("Payment received. Thank you.")).toBeTruthy();
    expect(api.simulatePayment).toHaveBeenCalledWith("i1", "succeeded");
    expect(api.getReceipt).toHaveBeenCalledWith("pay1");
    expect(screen.getByText("Receipt AB12CD34")).toBeTruthy();
    await waitFor(() => expect(api.getMyBills).toHaveBeenCalledTimes(2)); // list refreshed
  });

  it("lets the patient pay part of the bill", async () => {
    setup();
    api.createPaymentIntent.mockResolvedValue(intent({ amount_cents: 2000 }));
    fireEvent.click(await screen.findByText("Pay now"));
    fireEvent.change(screen.getByLabelText("Amount to pay (RM)"), { target: { value: "20" } });
    fireEvent.click(screen.getByText("Continue"));
    await screen.findByText("Approve payment");
    expect(api.createPaymentIntent.mock.calls[0][1].amount_cents).toBe(2000);
  });

  it("refuses bad or too-large amounts before calling the server", async () => {
    setup();
    fireEvent.click(await screen.findByText("Pay now"));
    const input = screen.getByLabelText("Amount to pay (RM)");
    fireEvent.change(input, { target: { value: "abc" } });
    fireEvent.click(screen.getByText("Continue"));
    expect((await screen.findByRole("alert")).textContent).toMatch(/Enter an amount/);
    fireEvent.change(input, { target: { value: "50.01" } });
    fireEvent.click(screen.getByText("Continue"));
    await waitFor(() => expect(screen.getByRole("alert").textContent).toMatch(/most you can pay is RM 50.00/));
    expect(api.createPaymentIntent).not.toHaveBeenCalled();
  });

  it("says nothing was charged when the payment is declined, and allows a retry", async () => {
    setup();
    api.createPaymentIntent.mockResolvedValue(intent());
    api.simulatePayment.mockResolvedValue({ ...intent(), status: "failed", failure_reason: "Declined by simulated bank" });
    fireEvent.click(await screen.findByText("Pay now"));
    fireEvent.click(screen.getByText("Continue"));
    fireEvent.click(await screen.findByText("Decline payment"));
    expect((await screen.findByRole("alert")).textContent).toMatch(/Declined by simulated bank.*not been charged/);
    expect(screen.getByLabelText("Amount to pay (RM)")).toBeTruthy(); // back to the amount step
    expect(api.getReceipt).not.toHaveBeenCalled();
  });

  it("shows a server refusal when starting the payment", async () => {
    setup();
    api.createPaymentIntent.mockRejectedValue({ response: { data: { detail: "A payment for this bill is already in progress" } } });
    fireEvent.click(await screen.findByText("Pay now"));
    fireEvent.click(screen.getByText("Continue"));
    expect((await screen.findByRole("alert")).textContent).toBe("A payment for this bill is already in progress");
  });

  it("cancels an open payment attempt", async () => {
    setup();
    api.createPaymentIntent.mockResolvedValue(intent());
    api.cancelPaymentIntent.mockResolvedValue({});
    fireEvent.click(await screen.findByText("Pay now"));
    fireEvent.click(screen.getByText("Continue"));
    fireEvent.click(await screen.findByText("Cancel payment"));
    await waitFor(() => expect(api.cancelPaymentIntent).toHaveBeenCalledWith("i1"));
    await waitFor(() => expect(screen.queryByText("Approve payment")).toBeNull());
  });

  it("resumes an in-progress payment and opens a past receipt", async () => {
    setup([bill({ pending_intent: intent() })],
          [{ payment_id: "p9", amount_cents: 1000, method: "cash", facility_name: "Hospital A",
             received_at: "2026-09-01T01:00:00Z", receipt_no: "ZZ99" }]);
    api.getReceipt.mockResolvedValue({ ...receipt, receipt_no: "ZZ99", amount_cents: 1000 });
    expect(await screen.findByText("Resume payment")).toBeTruthy();
    fireEvent.click(screen.getByText("Receipt ZZ99"));
    expect(await screen.findByText("Receipt ZZ99", { selector: "h2" })).toBeTruthy();
    expect(api.getReceipt).toHaveBeenCalledWith("p9");
  });
});

describe("receipt PDF and email", () => {
  async function openReceipt() {
    api.getReceipt.mockResolvedValue(receipt);
    setup([bill({ patient_due_cents: 0, amount_due_cents: 0, paid_cents: 5000 })],
          [{ payment_id: "pay1", bill_id: "b1", amount_cents: 5000, method: "online", receipt_no: "AB12CD34",
             facility_name: "Hospital A", received_at: "2026-10-12T03:00:00Z" }]);
    fireEvent.click(await screen.findByRole("button", { name: /Receipt AB12CD34/ }));
    await screen.findByLabelText("Receipt");
  }

  it("downloads the PDF for this payment", async () => {
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    URL.createObjectURL = vi.fn(() => "blob:x"); URL.revokeObjectURL = vi.fn();
    api.getReceiptPdf.mockResolvedValue(new Blob(["%PDF"]));
    await openReceipt();
    fireEvent.click(screen.getByRole("button", { name: "Download PDF" }));
    await waitFor(() => expect(click).toHaveBeenCalled());
    expect(api.getReceiptPdf).toHaveBeenCalledWith("pay1");
    click.mockRestore();
  });

  it("emails the receipt and says where it went", async () => {
    api.emailReceipt.mockResolvedValue({ sent: true, to_masked: "p***@example.com" });
    await openReceipt();
    fireEvent.click(screen.getByRole("button", { name: "Email receipt" }));
    expect(await screen.findByText("Receipt sent to p***@example.com.")).toBeTruthy();
    expect(api.emailReceipt).toHaveBeenCalledWith("pay1");
  });

  it("shows the server's reason when the email cannot be sent", async () => {
    api.emailReceipt.mockRejectedValue({ response: { data: { detail: "This patient has no email address on file" } } });
    await openReceipt();
    fireEvent.click(screen.getByRole("button", { name: "Email receipt" }));
    expect(await screen.findByRole("alert")).toHaveProperty("textContent", "This patient has no email address on file");
  });
});
