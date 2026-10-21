import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";

const L = vi.hoisted(() => {
  const chain = () => ({ addTo: vi.fn().mockReturnThis(), bindPopup: vi.fn().mockReturnThis() });
  const map = { fitBounds: vi.fn(), remove: vi.fn() };
  return {
    map,
    api: {
      map: vi.fn(() => map), tileLayer: vi.fn(chain), circle: vi.fn(chain), marker: vi.fn(chain), icon: vi.fn(() => ({})),
    },
  };
});
vi.mock("leaflet", () => ({ default: L.api }));
vi.mock("leaflet/dist/leaflet.css", () => ({}));

import ScanMap, { TILE_URL } from "./ScanMap";

const rows = [
  { id: 2, lat: 3.1, lng: 101.6, accuracy_m: 20.4, tier: "paramedic", actor_facility: "KL Hospital", created_at: "2026-10-22T10:00:00Z" },
  { id: 1, lat: 3.2, lng: 101.7, accuracy_m: null, tier: "public", actor_facility: null, created_at: "2026-10-22T09:00:00Z" },
];
afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe("ScanMap", () => {
  it("renders the empty state without touching Leaflet", () => {
    render(<ScanMap locations={[]} />);
    expect(screen.getByText(/has not been scanned with a shared location/)).toBeTruthy();
    expect(L.api.map).not.toHaveBeenCalled();
  });

  it("lists each row with who, a safe Maps link and the unverified caption", () => {
    render(<ScanMap locations={rows} />);
    expect(screen.getByText(/Paramedic - KL Hospital/)).toBeTruthy();
    expect(screen.getByText(/Public scan/)).toBeTruthy();
    const links = screen.getAllByRole("link", { name: "Open in Maps" });
    expect(links).toHaveLength(2);
    expect(links[0].getAttribute("href")).toBe("https://www.google.com/maps/search/?api=1&query=3.1,101.6");
    expect(links[0].getAttribute("target")).toBe("_blank");
    expect(links[0].getAttribute("rel")).toBe("noopener noreferrer");
    expect(screen.getByText(/not verified/)).toBeTruthy();
    expect(screen.getByText("Latest")).toBeTruthy();
  });

  it("builds one marker per row, a circle only when accuracy is known, and fits bounds", async () => {
    render(<ScanMap locations={rows} />);
    await waitFor(() => expect(L.map.fitBounds).toHaveBeenCalled());
    expect(L.api.tileLayer.mock.calls[0][0]).toBe(TILE_URL);
    expect(L.api.tileLayer.mock.calls[0][1].attribution).toMatch(/OpenStreetMap/);
    expect(L.api.marker).toHaveBeenCalledTimes(2);
    expect(L.api.circle).toHaveBeenCalledTimes(1);
    expect(L.api.marker.mock.calls[0][1].opacity).toBe(1);
  });

  it("falls back to the list when Leaflet fails", async () => {
    L.api.map.mockImplementationOnce(() => { throw new Error("boom"); });
    render(<ScanMap locations={rows} />);
    expect((await screen.findByRole("alert")).textContent).toMatch(/map could not be loaded/);
    expect(screen.getAllByRole("link", { name: "Open in Maps" })).toHaveLength(2);
  });
});
