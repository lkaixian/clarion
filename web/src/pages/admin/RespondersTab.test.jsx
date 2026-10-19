import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

vi.mock("../../api/client", () => ({
  listResponders: vi.fn(),
  createResponder: vi.fn(),
  updateResponderExpiry: vi.fn(),
  revokeResponder: vi.fn(),
}));

import * as api from "../../api/client";
import RespondersTab from "./RespondersTab";

afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe("RespondersTab", () => {
  it("creates a responder with a timezone-qualified expiry and shows the password once", async () => {
    api.listResponders.mockResolvedValue([]);
    api.createResponder.mockResolvedValue({ id: "1", email: "g@x.my", temporary_password: "Temp-Pass-123" });
    render(<RespondersTab />);
    await screen.findByText("No responder accounts yet.");

    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Guard Ali" } });
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "g@x.my" } });
    fireEvent.click(screen.getByRole("button", { name: "Create responder" }));

    await screen.findByText("Temp-Pass-123");
    const body = api.createResponder.mock.calls[0][0];
    expect(body.full_name).toBe("Guard Ali");
    expect(body.expires_at).toMatch(/Z$/); // the server rejects a naive time
    fireEvent.click(screen.getByText("Done, hide it"));
    await waitFor(() => expect(screen.queryByText("Temp-Pass-123")).toBeNull());
  });

  it("labels expired and revoked accounts and only offers Revoke on live ones", async () => {
    const past = new Date(Date.now() - 3600_000).toISOString();
    const future = new Date(Date.now() + 3600_000).toISOString();
    api.listResponders.mockResolvedValue([
      { id: "a", full_name: "Live", email: "a@x.my", active: true, access_expires_at: future },
      { id: "b", full_name: "Old", email: "b@x.my", active: true, access_expires_at: past },
      { id: "c", full_name: "Gone", email: "c@x.my", active: false, access_expires_at: future },
    ]);
    render(<RespondersTab />);
    await screen.findByText(/Live/);
    expect(screen.getByText(/· Expired/)).toBeTruthy();
    expect(screen.getByText(/· Revoked/)).toBeTruthy();
    expect(screen.getAllByRole("button", { name: "Revoke" }).length).toBe(2); // live + expired-but-active
    expect(screen.getByRole("button", { name: "Reinstate for 7 days" })).toBeTruthy();
  });
});
