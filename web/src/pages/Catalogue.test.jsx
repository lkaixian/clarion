import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

vi.mock("../components/Layout", () => ({ default: ({ children }) => <div>{children}</div> }));
vi.mock("../api/client", () => ({
  listDrugs: vi.fn(), getDrug: vi.fn(), listFeeSchedules: vi.fn(), listProducts: vi.fn(), getProduct: vi.fn(),
  listReferenceKinds: vi.fn(), getReferenceList: vi.fn(),
  errorMessage: (e, fb) => e?.response?.data?.detail || fb,
}));

import * as api from "../api/client";
import Catalogue from "./Catalogue";

const drug = (n) => ({ drug_code: `D${n}`, drug_generic_name: `Drug ${n}`, trade_name: `Trade ${n}`, dosage_form: "tablet" });

afterEach(cleanup);

describe("Catalogue drugs tab", () => {
  it("shows a loading state, then rows", async () => {
    api.listDrugs.mockResolvedValue([drug(1), drug(2)]);
    render(<Catalogue />);
    expect(screen.getByText("Loading...")).toBeTruthy();
    expect(await screen.findByText("Drug 1")).toBeTruthy();
    expect(screen.getByText("Drug 2")).toBeTruthy();
    expect(api.listDrugs).toHaveBeenCalledWith({ q: "", limit: 26, offset: 0 });
  });

  it("shows an empty state naming the search", async () => {
    api.listDrugs.mockResolvedValue([]);
    render(<Catalogue />);
    fireEvent.change(await screen.findByLabelText("Search drugs"), { target: { value: "zzz" } });
    expect(await screen.findByText(/No drugs match "zzz"/)).toBeTruthy();
    expect(api.listDrugs).toHaveBeenLastCalledWith({ q: "zzz", limit: 26, offset: 0 });
  });

  it("shows the server error, not a blank page", async () => {
    api.listDrugs.mockRejectedValue({ response: { data: { detail: "Staff accounts only" } } });
    render(<Catalogue />);
    expect((await screen.findByRole("alert")).textContent).toBe("Staff accounts only");
  });

  it("enables Next only when a further page exists and pages by 25", async () => {
    api.listDrugs.mockImplementation(({ offset }) =>
      Promise.resolve(Array.from({ length: offset === 0 ? 26 : 3 }, (_, i) => drug(offset + i))));
    render(<Catalogue />);
    await screen.findByText("Drug 0");
    expect(screen.queryByText("Drug 25")).toBeNull(); // the 26th row is only the "has more" probe
    const next = screen.getByText("Next");
    expect(next.disabled).toBe(false);
    expect(screen.getByText("Previous").disabled).toBe(true);
    fireEvent.click(next);
    await waitFor(() => expect(api.listDrugs).toHaveBeenLastCalledWith({ q: "", limit: 26, offset: 25 }));
    await screen.findByText("Drug 25");
    expect(screen.getByText("Next").disabled).toBe(true);
    expect(screen.getByText("Previous").disabled).toBe(false);
  });

  it("expands a row to show resolved prescribing lines", async () => {
    api.listDrugs.mockResolvedValue([drug(1)]);
    api.getDrug.mockResolvedValue({
      ...drug(1), category_name: "ANTIVIRALS", indications: ["HIV infection"], formulary: null,
      prescriptions: [{ drug_dosage: 1, dosage: "tablet", frequency: "Once daily", route: "Oral", drug_duration: null, period: null, instruction: null }],
    });
    render(<Catalogue />);
    const row = await screen.findByRole("button", { name: /Drug 1/ });
    expect(row.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(row);
    expect(await screen.findByText("Once daily")).toBeTruthy();
    expect(screen.getByText("HIV infection")).toBeTruthy();
    expect(api.getDrug).toHaveBeenCalledWith("D1");
    expect(row.getAttribute("aria-expanded")).toBe("true");
    fireEvent.click(row);
    expect(screen.queryByText("Once daily")).toBeNull();
  });

  it("explains a drug with no default lines and surfaces a detail error", async () => {
    api.listDrugs.mockResolvedValue([drug(1), drug(2)]);
    api.getDrug.mockImplementation((c) => c === "D1"
      ? Promise.resolve({ ...drug(1), indications: [], prescriptions: [] })
      : Promise.reject({ response: { data: { detail: "Drug not found" } } }));
    render(<Catalogue />);
    fireEvent.click(await screen.findByRole("button", { name: /Drug 1/ }));
    expect(await screen.findByText(/No default lines recorded/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Drug 2/ }));
    expect(await screen.findByText("Drug not found")).toBeTruthy();
  });
});

describe("Catalogue products and code lists", () => {
  it("shows fee schedule rows with the fee as text and expands without another request", async () => {
    api.listDrugs.mockResolvedValue([]);
    api.listFeeSchedules.mockResolvedValue([{
      fee_code: "70010001", part: "I", header: "1. General practitioner", sub_header: "(a) First visit",
      description: "Consultation only", value: "30-125", value2: "",
    }]);
    render(<Catalogue />);
    fireEvent.click(screen.getByRole("tab", { name: "Fee schedule" }));
    const row = await screen.findByRole("button", { name: /Consultation only/ });
    expect(row.textContent).toContain("30-125");
    fireEvent.click(row);
    expect(await screen.findByText("70010001")).toBeTruthy();
    expect(screen.queryByText("Second value")).toBeNull(); // empty value2 is not rendered
    expect(api.listFeeSchedules).toHaveBeenCalledTimes(1);
  });

  it("lists products and shows units on expand", async () => {
    api.listDrugs.mockResolvedValue([]);
    api.listProducts.mockResolvedValue([{ product_code: "P1", product_name: "Alcohol swab", category_code: "consumable", product_unit_charge: 1.5 }]);
    api.getProduct.mockResolvedValue({
      product_code: "P1", product_name: "Alcohol swab", category_name: "Consumables", product_stocked: 0,
      uoms: [{ unit_code: "box", uom_rate: 100, uom_price: 12, uom_cost: 8, uom_default_price: 1 }],
    });
    render(<Catalogue />);
    fireEvent.click(screen.getByRole("tab", { name: "Products" }));
    expect(screen.getByRole("tab", { name: "Products" }).getAttribute("aria-selected")).toBe("true");
    fireEvent.click(await screen.findByRole("button", { name: /Alcohol swab/ }));
    expect(await screen.findByText("box (default)")).toBeTruthy();
    expect(screen.getByText("Not stocked")).toBeTruthy();
    expect(screen.getByText("12.00")).toBeTruthy();
  });

  it("loads a code list only after one is chosen", async () => {
    api.listDrugs.mockResolvedValue([]);
    api.listReferenceKinds.mockResolvedValue({ states: 14, drug_routes: 40 });
    api.getReferenceList.mockResolvedValue([{ code: "johor", name: "Johor Darul Takzim", parent: null }]);
    render(<Catalogue />);
    fireEvent.click(screen.getByRole("tab", { name: "Code lists" }));
    expect(await screen.findByText("Choose a list to see its codes.")).toBeTruthy();
    expect(api.getReferenceList).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("List"), { target: { value: "states" } });
    expect(await screen.findByText("Johor Darul Takzim")).toBeTruthy();
    expect(api.getReferenceList).toHaveBeenCalledWith("states", { q: "" });
    expect(screen.getByText("drug routes (40)")).toBeTruthy();
  });

  it("reports a failure to load the list of lists", async () => {
    api.listDrugs.mockResolvedValue([]);
    api.listReferenceKinds.mockRejectedValue(new Error("down"));
    render(<Catalogue />);
    fireEvent.click(screen.getByRole("tab", { name: "Code lists" }));
    expect((await screen.findByRole("alert")).textContent).toBe("Could not load the code lists.");
  });
});

