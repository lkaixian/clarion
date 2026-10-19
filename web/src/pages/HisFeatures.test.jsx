import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

vi.mock("../components/Layout", () => ({ default: ({ children }) => <div>{children}</div> }));
vi.mock("../api/client", () => ({
  listPatientOrders: vi.fn(), createOrder: vi.fn(), completeOrder: vi.fn(), cancelOrder: vi.fn(), listDrugs: vi.fn(),
  listOrders: vi.fn(),
  listForms: vi.fn(), listFormResponses: vi.fn(), submitFormResponse: vi.fn(), createForm: vi.fn(), deactivateForm: vi.fn(),
  listSuppliers: vi.fn(), createSupplier: vi.fn(), listPurchaseOrders: vi.fn(), createPurchaseOrder: vi.fn(),
  placePurchaseOrder: vi.fn(), cancelPurchaseOrder: vi.fn(), receivePurchaseOrder: vi.fn(), getPharmacyInventory: vi.fn(),
  getCurrentUser: vi.fn(),
  errorMessage: (e, fb) => e?.response?.data?.detail || fb,
}));

import * as api from "../api/client";
import PatientOrders from "../components/PatientOrders";
import PatientForms, { toFieldValue } from "../components/PatientForms";
import FormsAdmin, { toFields, keyFromLabel } from "./FormsAdmin";
import Purchasing from "./Purchasing";
import Orders from "./Orders";

afterEach(() => { cleanup(); vi.clearAllMocks(); });

const asUser = (role, id = "u1") => api.getCurrentUser.mockReturnValue({ id, role, full_name: "Someone" });
const order = (over = {}) => ({
  id: "o1", patient_id: "p1", patient_name: "Pat Ient", order_type: "drug", description: "Paracetamol", quantity: 20,
  status: "ordered", ordered_by: "u1", ordered_by_name: "Doc", created_at: "2026-10-12T03:00:00Z", is_stat: false, ...over,
});

describe("PatientOrders", () => {
  it("lists orders and lets the orderer cancel with a reason", async () => {
    asUser("clinician");
    api.listPatientOrders.mockResolvedValue([order()]);
    api.cancelOrder.mockResolvedValue({});
    vi.spyOn(window, "prompt").mockReturnValue("wrong patient");
    render(<PatientOrders patientId="p1" />);
    expect(await screen.findByText("Paracetamol")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(api.cancelOrder).toHaveBeenCalledWith("o1", "wrong patient"));
  });

  it("does not offer to dispense a drug order to a clinician", async () => {
    asUser("clinician");
    api.listPatientOrders.mockResolvedValue([order()]);
    render(<PatientOrders patientId="p1" />);
    await screen.findByText("Paracetamol");
    expect(screen.queryByRole("button", { name: "Dispense" })).toBeNull();
  });

  it("places a new order and reloads", async () => {
    asUser("clinician");
    api.listPatientOrders.mockResolvedValue([]);
    api.listDrugs.mockResolvedValue([]);
    api.createOrder.mockResolvedValue({});
    render(<PatientOrders patientId="p1" />);
    expect(await screen.findByText("No orders at this facility for this patient.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "New order" }));
    fireEvent.change(screen.getByLabelText("What is ordered"), { target: { value: "Amoxicillin" } });
    fireEvent.change(screen.getByLabelText("Quantity"), { target: { value: "10" } });
    fireEvent.click(screen.getByRole("button", { name: "Place order" }));
    await waitFor(() => expect(api.createOrder).toHaveBeenCalled());
    expect(api.createOrder.mock.calls[0][1]).toMatchObject({ order_type: "drug", description: "Amoxicillin", quantity: 10 });
    await waitFor(() => expect(api.listPatientOrders).toHaveBeenCalledTimes(2));
  });

  it("shows the server's reason when ordering fails", async () => {
    asUser("clinician");
    api.listPatientOrders.mockResolvedValue([]);
    api.listDrugs.mockResolvedValue([]);
    api.createOrder.mockRejectedValue({ response: { data: { detail: "Patient not found" } } });
    render(<PatientOrders patientId="p1" />);
    fireEvent.click(await screen.findByRole("button", { name: "New order" }));
    fireEvent.change(screen.getByLabelText("What is ordered"), { target: { value: "FBC" } });
    fireEvent.click(screen.getByRole("button", { name: "Place order" }));
    expect((await screen.findByRole("alert")).textContent).toBe("Patient not found");
  });
});

describe("Orders worklist", () => {
  it("lets a pharmacist dispense a drug order", async () => {
    asUser("pharmacist", "ph1");
    api.listOrders.mockResolvedValue([order()]);
    api.completeOrder.mockResolvedValue({});
    render(<Orders />);
    fireEvent.click(await screen.findByRole("button", { name: "Dispense" }));
    await waitFor(() => expect(api.completeOrder).toHaveBeenCalledWith("o1"));
  });
});

describe("PatientForms", () => {
  const form = { id: "f1", code: "pain", version: 1, name: "Pain assessment", fields: [
    { key: "score", label: "Pain score", type: "number", required: true },
    { key: "radiating", label: "Radiating", type: "boolean" },
  ] };

  it("converts typed values", () => {
    expect(toFieldValue({ type: "number" }, "4.5")).toBe(4.5);
    expect(toFieldValue({ type: "text" }, "")).toBeNull();
    expect(toFieldValue({ type: "boolean" }, true)).toBe(true);
  });

  it("fills in a form and reloads", async () => {
    api.listForms.mockResolvedValue([form]);
    api.listFormResponses.mockResolvedValue([]);
    api.submitFormResponse.mockResolvedValue({});
    render(<PatientForms patientId="p1" />);
    fireEvent.change(await screen.findByLabelText("Fill in a form"), { target: { value: "f1" } });
    fireEvent.change(screen.getByLabelText("Pain score *"), { target: { value: "7" } });
    fireEvent.click(screen.getByRole("button", { name: "Save form" }));
    await waitFor(() => expect(api.submitFormResponse).toHaveBeenCalledWith("p1", "f1", { score: 7 }));
  });

  it("explains when there are no forms", async () => {
    api.listForms.mockResolvedValue([]);
    api.listFormResponses.mockResolvedValue([]);
    render(<PatientForms patientId="p1" />);
    expect(await screen.findByText(/No forms are set up/)).toBeTruthy();
  });
});

describe("FormsAdmin", () => {
  it("derives field keys and builds the payload", () => {
    expect(keyFromLabel("Pain score (0-10)")).toBe("pain_score_0_10");
    expect(keyFromLabel("2nd opinion")).toBe("f_2nd_opinion");
    expect(toFields([{ key: "site", label: "Site", type: "select", required: true, options: "head, chest ," }])).toEqual([
      { key: "site", label: "Site", type: "select", required: true, options: ["head", "chest"] },
    ]);
  });

  it("saves a new form", async () => {
    api.listForms.mockResolvedValue([]);
    api.createForm.mockResolvedValue({});
    render(<FormsAdmin />);
    await screen.findByText(/No forms yet/);
    fireEvent.change(screen.getByLabelText("Form name"), { target: { value: "Pain check" } });
    fireEvent.change(screen.getByLabelText("Field label"), { target: { value: "Pain score" } });
    fireEvent.click(screen.getByRole("button", { name: "Save form" }));
    await waitFor(() => expect(api.createForm).toHaveBeenCalled());
    expect(api.createForm.mock.calls[0][0]).toMatchObject({
      code: "pain-check", name: "Pain check", fields: [{ key: "pain_score", label: "Pain score", type: "text" }],
    });
  });
});

describe("Purchasing", () => {
  const po = (over = {}) => ({
    id: "po1", po_number: "PO-1", status: "ordered", supplier_name: "MedSupply", total_cost: 40, created_at: "2026-10-12T03:00:00Z",
    lines: [{ id: "l1", item_name: "Amoxicillin", quantity: 100, received_quantity: 0 }], ...over,
  });

  it("books a partial receipt", async () => {
    asUser("pharmacist");
    api.listSuppliers.mockResolvedValue([]);
    api.listPurchaseOrders.mockResolvedValue([po()]);
    api.getPharmacyInventory.mockResolvedValue([]);
    api.receivePurchaseOrder.mockResolvedValue({});
    render(<Purchasing />);
    fireEvent.click(await screen.findByRole("button", { name: "Receive goods" }));
    fireEvent.change(screen.getByLabelText("Quantity received for Amoxicillin"), { target: { value: "60" } });
    fireEvent.click(screen.getByRole("button", { name: "Book receipt" }));
    await waitFor(() => expect(api.receivePurchaseOrder).toHaveBeenCalledWith("po1", [
      { line_id: "l1", quantity: 60, batch_number: null, expiry_date: null },
    ]));
  });

  it("only an admin can place a draft", async () => {
    asUser("pharmacist");
    api.listSuppliers.mockResolvedValue([]);
    api.listPurchaseOrders.mockResolvedValue([po({ status: "draft" })]);
    api.getPharmacyInventory.mockResolvedValue([]);
    render(<Purchasing />);
    await screen.findByText(/Waiting for an admin/);
    expect(screen.queryByRole("button", { name: "Place order" })).toBeNull();
    cleanup();
    asUser("admin");
    render(<Purchasing />);
    expect(await screen.findByRole("button", { name: "Place order" })).toBeTruthy();
  });

  it("shows the server's refusal on receive", async () => {
    asUser("pharmacist");
    api.listSuppliers.mockResolvedValue([]);
    api.listPurchaseOrders.mockResolvedValue([po()]);
    api.getPharmacyInventory.mockResolvedValue([]);
    api.receivePurchaseOrder.mockRejectedValue({ response: { data: { detail: "Amoxicillin: only 40 still outstanding" } } });
    render(<Purchasing />);
    fireEvent.click(await screen.findByRole("button", { name: "Receive goods" }));
    fireEvent.change(screen.getByLabelText("Quantity received for Amoxicillin"), { target: { value: "60" } });
    fireEvent.click(screen.getByRole("button", { name: "Book receipt" }));
    expect((await screen.findByRole("alert")).textContent).toBe("Amoxicillin: only 40 still outstanding");
  });
});

describe("FormsAdmin builder GUI", () => {
  it("adds fields by type, reorders them, and shows a live preview", async () => {
    api.listForms.mockResolvedValue([]);
    render(<FormsAdmin />);
    await screen.findByText(/No forms yet/);
    fireEvent.change(screen.getByLabelText("Form name"), { target: { value: "Triage" } });
    fireEvent.change(screen.getByLabelText("Field label"), { target: { value: "Temperature" } });
    fireEvent.click(screen.getByRole("button", { name: "+ Yes / no" }));
    expect(screen.getAllByTestId("builder-field")).toHaveLength(2);
    const labels = screen.getAllByLabelText("Field label");
    fireEvent.change(labels[1], { target: { value: "On oxygen" } });

    const preview = screen.getByLabelText("Preview");
    expect(preview.textContent).toContain("Triage");
    expect(preview.textContent).toContain("Temperature");
    expect(preview.textContent).toContain("On oxygen");
    const order = () => [...preview.querySelectorAll("label")].map((l) => l.textContent);
    expect(order()).toEqual(["Temperature", "On oxygen"]);

    fireEvent.click(screen.getByRole("button", { name: "Move field 2 up" }));
    expect(order()).toEqual(["On oxygen", "Temperature"]);
  });

  it("numbers the key of a repeated label so the form still saves", async () => {
    api.listForms.mockResolvedValue([]);
    api.createForm.mockResolvedValue({});
    render(<FormsAdmin />);
    await screen.findByText(/No forms yet/);
    fireEvent.change(screen.getByLabelText("Form name"), { target: { value: "Dup" } });
    fireEvent.change(screen.getByLabelText("Field label"), { target: { value: "Score" } });
    fireEvent.click(screen.getByRole("button", { name: "+ Text" }));
    fireEvent.change(screen.getAllByLabelText("Field label")[1], { target: { value: "Score" } });
    fireEvent.click(screen.getByRole("button", { name: "Save form" }));
    await waitFor(() => expect(api.createForm).toHaveBeenCalled());
    expect(api.createForm.mock.calls[0][0].fields.map((f) => f.key)).toEqual(["score", "score_2"]);
  });
});
