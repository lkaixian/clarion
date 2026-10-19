import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, waitFor } from "@testing-library/react";

vi.mock("../api/client", () => ({ listDrugs: vi.fn() }));
import * as api from "../api/client";
import DrugHints, { CatalogueTag } from "./DrugHints";

afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe("DrugHints", () => {
  it("fills the datalist from the drug master once 3 characters are typed", async () => {
    api.listDrugs.mockResolvedValue([{ drug_code: "D1", drug_generic_name: "Paracetamol", trade_name: "Panadol", dosage_form: "Tablet" }]);
    const { container, rerender } = render(<DrugHints id="h" query="pa" />);
    expect(api.listDrugs).not.toHaveBeenCalled();
    rerender(<DrugHints id="h" query="para" />);
    await waitFor(() => expect(container.querySelectorAll("option").length).toBe(1));
    expect(container.querySelector("option").value).toBe("Paracetamol");
  });

  it("shows the catalogue tag only for a linked drug", () => {
    const { container, rerender } = render(<CatalogueTag code="D1" />);
    expect(container.textContent).toBe("Catalogue D1");
    rerender(<CatalogueTag code={null} />);
    expect(container.textContent).toBe("");
  });
});
