import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

vi.mock("../components/Layout", () => ({ default: ({ children }) => <div>{children}</div> }));
vi.mock("../api/client", async (orig) => ({
  ...(await orig()), getNotifications: vi.fn(), markNotificationRead: vi.fn().mockResolvedValue({}), markAllNotificationsRead: vi.fn(),
}));
import * as api from "../api/client";
import Inbox from "./Inbox";

afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe("Inbox links", () => {
  it("an https link is an external Open in Maps link, not an in-app route", async () => {
    api.getNotifications.mockResolvedValue([
      { id: 1, title: "Card scanned", body: "near KL", link: "https://maps.google.com/?q=3.1,101.6", read_at: null, created_at: "2026-10-22T10:00:00Z" },
      { id: 2, title: "Result", body: "", link: "/patients/5", read_at: "x", created_at: "2026-10-22T09:00:00Z" },
    ]);
    render(<MemoryRouter><Inbox /></MemoryRouter>);
    const a = await screen.findByRole("link", { name: /Open in Maps/ });
    expect(a.getAttribute("href")).toBe("https://maps.google.com/?q=3.1,101.6");
    expect(a.getAttribute("target")).toBe("_blank");
    expect(a.getAttribute("rel")).toBe("noopener noreferrer");
    expect(screen.getAllByRole("link")).toHaveLength(1);
    fireEvent.click(a);
    expect(api.markNotificationRead).toHaveBeenCalledWith(1);
  });
});
