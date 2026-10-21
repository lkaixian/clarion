import { beforeEach, describe, expect, it, vi } from "vitest";

const inst = vi.hoisted(() => ({ interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } }, post: vi.fn(), request: vi.fn() }));
vi.mock("axios", () => ({ default: { create: () => inst, post: vi.fn() } }));

import axios from "axios";
import { switchProfile } from "./client";

const handler = inst.interceptors.response.use.mock.calls[0][1]; // registered once, at import

beforeEach(() => localStorage.clear());

describe("profile session", () => {
  it("switchProfile stores the new token and user", async () => {
    inst.post.mockResolvedValue({ data: { access_token: "t2", user: { patient_id: "p2", acting_for: true } } });
    await switchProfile("p2");
    expect(inst.post).toHaveBeenCalledWith("/profiles/switch", { patient_id: "p2" });
    expect(localStorage.getItem("mb_token")).toBe("t2");
    expect(JSON.parse(localStorage.getItem("mb_user")).acting_for).toBe(true);
  });

  it("refresh sends act_as while acting", async () => {
    localStorage.setItem("mb_user", JSON.stringify({ patient_id: "p2", acting_for: true }));
    axios.post.mockResolvedValue({ data: { access_token: "t3", user: { patient_id: "p2", acting_for: true } } });
    inst.request.mockResolvedValue({});
    await handler({ response: { status: 401 }, config: { url: "/x", headers: {} } });
    expect(axios.post.mock.calls[0][1]).toEqual({ act_as: "p2" });
  });

  it("replaces the user after refresh and reloads home with a notice when acting was refused", async () => {
    localStorage.setItem("mb_user", JSON.stringify({ patient_id: "p2", acting_for: true }));
    axios.post.mockResolvedValue({ data: { access_token: "t4", user: { patient_id: "p1", acting_for: false } } });
    inst.request.mockResolvedValue({});
    const loc = window.location;
    delete window.location;
    window.location = { pathname: "/x", href: "" };
    try {
      await handler({ response: { status: 401 }, config: { url: "/x", headers: {} } });
      expect(JSON.parse(localStorage.getItem("mb_user")).patient_id).toBe("p1");
      expect(window.location.href).toBe("/patients/p1");
      expect(sessionStorage.getItem("mb_notice")).toMatch(/no longer acting/);
    } finally { window.location = loc; sessionStorage.clear(); }
  });

  it("falls back to the home profile (not login) when the link was removed", async () => {
    localStorage.setItem("mb_user", JSON.stringify({ patient_id: "p2", acting_for: true, home_patient_id: "p1" }));
    inst.post.mockResolvedValue({ data: { access_token: "home", user: { patient_id: "p1", acting_for: false } } });
    const loc = window.location;
    delete window.location;
    window.location = { pathname: "/x", href: "" };
    try {
      await expect(handler({ response: { status: 403, data: { detail: "You can no longer act for this profile" } }, config: { url: "/x", headers: {} } })).rejects.toBeDefined();
      expect(inst.post).toHaveBeenCalledWith("/profiles/switch", { patient_id: "p1" });
      expect(localStorage.getItem("mb_token")).toBe("home");
      expect(window.location.href).toBe("/patients/p1");
      expect(sessionStorage.getItem("mb_notice")).toMatch(/no longer act/);
    } finally { window.location = loc; sessionStorage.clear(); }
  });
});
