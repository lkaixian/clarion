import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

vi.mock("../components/Layout", () => ({ default: ({ children }) => <div>{children}</div> }));
vi.mock("../api/client", async (orig) => ({ ...(await orig()), listDrugs: vi.fn(), addMedication: vi.fn() }));

import * as api from "../api/client";
import { RecordModal, tagWritePrompt } from "./PatientDetail";

const open = (kind = "medication") =>
  render(<RecordModal kind={kind} mode="add" initial={{ patientId: "p1" }} onClose={() => {}} onSaved={() => {}} />);
const nameInput = () => screen.getByLabelText(/Drug name/);

afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe("medication drug-name suggestions", () => {
  it("fills a datalist from the drug master after 3 characters, and keeps free text", async () => {
    api.listDrugs.mockResolvedValue([
      { drug_code: "D1", drug_generic_name: "Lamivudine 150mg tablet", trade_name: "Zeffix", dosage_form: "tablet" },
    ]);
    open();
    const input = nameInput();
    expect(input.getAttribute("list")).toBe("drug-hints");
    fireEvent.change(input, { target: { value: "la" } });
    await new Promise((r) => setTimeout(r, 400));
    expect(api.listDrugs).not.toHaveBeenCalled(); // under 3 characters
    fireEvent.change(input, { target: { value: "lami" } });
    await waitFor(() => expect(api.listDrugs).toHaveBeenCalledWith({ q: "lami", limit: 8 }));
    await waitFor(() => expect(document.querySelector("#drug-hints option")?.value).toBe("Lamivudine 150mg tablet"));
    fireEvent.change(input, { target: { value: "Some unlisted herbal tonic" } });
    expect(input.value).toBe("Some unlisted herbal tonic");
  });

  it("does not block entry when the catalogue is unreachable", async () => {
    api.listDrugs.mockRejectedValue(new Error("down"));
    open();
    fireEvent.change(nameInput(), { target: { value: "para" } });
    await waitFor(() => expect(api.listDrugs).toHaveBeenCalled());
    await new Promise((r) => setTimeout(r, 50));
    expect(document.querySelectorAll("#drug-hints option").length).toBe(0);
    expect(screen.queryByText(/Failed|Could not/)).toBeNull();
  });

  it("is not used for other record kinds", async () => {
    open("allergy");
    fireEvent.change(screen.getByLabelText(/Allergen/), { target: { value: "penicillin" } });
    await new Promise((r) => setTimeout(r, 400));
    expect(api.listDrugs).not.toHaveBeenCalled();
    expect(document.querySelector("#drug-hints")).toBeNull();
  });
});

describe("NFC tag write prompt", () => {
  it("offers only the encrypted blob, never plaintext", () => {
    const p = tagWritePrompt({
      tag_blob: "C1.1.abc", tag_text: "BT:O+|AL:Penicillin(severe)", tag_blob_truncated: false,
      tag_security: { warning: null },
    });
    expect(p.blob).toBe("C1.1.abc");
    expect(p.message).toMatch(/ENCRYPTED/);
    expect(p.message).not.toMatch(/plaintext/i);
  });

  it("flags truncation and the missing read counter", () => {
    const p = tagWritePrompt({ tag_blob: "C1.1.abc", tag_blob_truncated: true, tag_security: { warning: "no counter" } });
    expect(p.message).toMatch(/truncated/);
    expect(p.message).toMatch(/no counter/);
  });

  it("says there is nothing to write when no blob was produced", () => {
    const p = tagWritePrompt({ tag_blob: null, tag_text: "BT:O+" });
    expect(p.blob).toBeNull();
    expect(p.message).toMatch(/nothing to write/);
    expect(p.message).toMatch(/old record/);
  });

  it("tells staff to use a larger tag when the data exists but nothing fit", () => {
    const p = tagWritePrompt({ tag_blob: null, tag_blob_truncated: true });
    expect(p.blob).toBeNull();
    expect(p.message).toMatch(/larger tag/);
    expect(p.message).not.toMatch(/no emergency data/);
  });
});
