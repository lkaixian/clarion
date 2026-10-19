import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

vi.mock("../../api/client", () => ({
  getBookingAdminSettings: vi.fn(),
  saveBookingAdminSettings: vi.fn(),
}));

import * as api from "../../api/client";
import OnlineBookingTab from "./OnlineBookingTab";

const CATS = [
  ["general", "General consultation"], ["chronic", "Follow-up and chronic care"], ["vaccination", "Vaccination"],
  ["maternal_child", "Maternal and child health"], ["dental", "Dental"], ["screening", "Health screening"],
  ["mental_health", "Mental health and counselling"], ["physio", "Physiotherapy and rehabilitation"],
];
const settings = () => ({
  facility_name: "Klinik A", display_name: "Klinik A", address: "1 Jalan Satu",
  online_booking_enabled: false, latitude: null, longitude: null,
  services: CATS.map(([category, label]) => ({
    category, label, active: false, slot_minutes: 30, capacity: 1, advance_days: 14, min_notice_minutes: 60,
    hours: category === "general" ? [{ weekday: 0, start: "09:00", end: "12:00" }] : [],
  })),
});

afterEach(() => { cleanup(); vi.clearAllMocks(); });

async function open(s = settings()) {
  api.getBookingAdminSettings.mockResolvedValue(s);
  render(<OnlineBookingTab />);
  await screen.findByText("Hospital location");
}
const saveBtn = () => screen.getByRole("button", { name: "Save online booking settings" });

describe("OnlineBookingTab", () => {
  it("renders all 8 categories and a live slot preview", async () => {
    await open();
    for (const [, label] of CATS) expect(screen.getByRole("heading", { name: label })).toBeTruthy();
    expect(screen.getByTestId("ob-general-preview").textContent).toMatch(/creates 6 slots per week/);
    expect(saveBtn().disabled).toBe(true); // nothing changed yet
  });

  it("sends the edited whole object in the PUT body", async () => {
    await open();
    api.saveBookingAdminSettings.mockImplementation(async (b) => b);
    fireEvent.click(screen.getByLabelText(/Allow patients to book online at this hospital/));
    fireEvent.change(screen.getByLabelText("Latitude"), { target: { value: "1.85" } });
    fireEvent.change(screen.getByLabelText("Longitude"), { target: { value: "102.93" } });
    fireEvent.click(screen.getAllByLabelText(/^Active/)[0]);
    fireEvent.change(screen.getAllByLabelText("People per slot")[0], { target: { value: "3" } });
    fireEvent.change(screen.getByLabelText("General consultation Monday end time"), { target: { value: "13:00" } });
    expect(screen.getByText("Unsaved changes")).toBeTruthy();
    fireEvent.click(saveBtn());
    await waitFor(() => expect(api.saveBookingAdminSettings).toHaveBeenCalledTimes(1));
    const body = api.saveBookingAdminSettings.mock.calls[0][0];
    expect(body.online_booking_enabled).toBe(true);
    expect(body.latitude).toBe(1.85);
    expect(body.longitude).toBe(102.93);
    expect(body.services).toHaveLength(8);
    expect(body.services[0]).toEqual({
      category: "general", label: "General consultation", active: true, slot_minutes: 30, capacity: 3,
      advance_days: 14, min_notice_minutes: 60, hours: [{ weekday: 0, start: "09:00", end: "13:00" }],
    });
    expect(await screen.findByText("Online booking settings saved.")).toBeTruthy();
    expect(screen.queryByText("Unsaved changes")).toBeNull();
  });

  it("copies Monday to weekdays", async () => {
    await open();
    fireEvent.click(screen.getAllByText("Copy Monday to weekdays")[0]);
    expect(screen.getByLabelText("General consultation Friday start time").value).toBe("09:00");
    expect(screen.getByTestId("ob-general-preview").textContent).toMatch(/creates 30 slots per week/);
  });

  it("blocks save when ranges overlap", async () => {
    await open();
    fireEvent.click(screen.getByLabelText("Add time range on Monday for General consultation"));
    fireEvent.change(screen.getAllByLabelText("General consultation Monday start time")[1], { target: { value: "11:00" } });
    expect(screen.getByText("Monday: time ranges overlap.")).toBeTruthy();
    expect(saveBtn().disabled).toBe(true);
    fireEvent.click(saveBtn());
    expect(api.saveBookingAdminSettings).not.toHaveBeenCalled();
  });

  it("rejects a range too short for the slot length and out-of-range latitude", async () => {
    await open();
    fireEvent.change(screen.getAllByLabelText("Slot length")[0], { target: { value: "240" } });
    expect(screen.getByText(/Monday: a 240 minute slot does not fit/)).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Latitude"), { target: { value: "91" } });
    fireEvent.change(screen.getByLabelText("Longitude"), { target: { value: "10" } });
    expect(screen.getByText("Latitude must be between -90 and 90.")).toBeTruthy();
    expect(saveBtn().disabled).toBe(true);
  });

  it("shows the server's validation message", async () => {
    await open();
    api.saveBookingAdminSettings.mockRejectedValue({ response: { data: { detail: "Dental: Monday ranges overlap" } } });
    fireEvent.click(screen.getByLabelText(/Allow patients to book online at this hospital/));
    fireEvent.click(saveBtn());
    expect((await screen.findByRole("alert")).textContent).toBe("Dental: Monday ranges overlap");
    expect(screen.getByText("Unsaved changes")).toBeTruthy();
  });

  it("shows a load error with retry", async () => {
    api.getBookingAdminSettings.mockRejectedValueOnce({ response: { data: { detail: "nope" } } });
    render(<OnlineBookingTab />);
    expect(await screen.findByText("nope")).toBeTruthy();
    api.getBookingAdminSettings.mockResolvedValue(settings());
    fireEvent.click(screen.getByText("Try again"));
    expect(await screen.findByText("Hospital location")).toBeTruthy();
  });

  it("handles a denied geolocation request gracefully", async () => {
    await open();
    Object.defineProperty(navigator, "geolocation", {
      configurable: true,
      value: { getCurrentPosition: (_ok, fail) => fail({ code: 1 }) },
    });
    fireEvent.click(screen.getByText("Use this device's location"));
    expect(screen.getByText(/Location was not shared/)).toBeTruthy();
    expect(screen.getByLabelText("Latitude").value).toBe("");
  });
});
