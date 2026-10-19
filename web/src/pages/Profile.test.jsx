import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

vi.mock("../components/Layout", () => ({ default: ({ children }) => <div>{children}</div> }));
vi.mock("../components/SignaturePad", () => ({ default: () => <div>pad</div> }));
vi.mock("../api/client", () => ({
  getCurrentUser: vi.fn(() => ({ id: "u1", role: "clinician", full_name: "Doc", email: "d@x", has_signature: false })),
  refreshCurrentUser: vi.fn().mockResolvedValue({ id: "u1", role: "clinician", has_signature: true }),
  getMySignatureBlob: vi.fn(), uploadMySignature: vi.fn().mockResolvedValue({}), deleteMySignature: vi.fn(),
  updateMyProfile: vi.fn(), getMyPhotoBlob: vi.fn(), uploadMyPhoto: vi.fn(), deleteMyPhoto: vi.fn(),
}));

import * as api from "../api/client";
import Profile from "./Profile";

afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe("signature upload", () => {
  it("offers a picture upload next to the pad", () => {
    render(<Profile />);
    const input = screen.getByLabelText("Or upload a picture of your signature");
    expect(input.getAttribute("accept")).toContain("image/png");
  });

  it("refuses a file that is not an image, without calling the server", async () => {
    render(<Profile />);
    const input = screen.getByLabelText("Or upload a picture of your signature");
    fireEvent.change(input, { target: { files: [new File(["x"], "sig.pdf", { type: "application/pdf" })] } });
    expect(await screen.findByText("Choose a PNG, JPEG or WebP image.")).toBeTruthy();
    expect(api.uploadMySignature).not.toHaveBeenCalled();
  });

  it("converts a picture to PNG, previews it, and saves it only on Save", async () => {
    const toDataURL = vi.fn(() => "data:image/png;base64,iVBORw0KGgo=");
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({ drawImage: vi.fn() });
    vi.spyOn(HTMLCanvasElement.prototype, "toDataURL").mockImplementation(toDataURL);
    URL.createObjectURL = vi.fn(() => "blob:x");
    URL.revokeObjectURL = vi.fn();
    // jsdom never loads images: fire onload as soon as src is set.
    const realImage = global.Image;
    global.Image = class {
      set src(_v) { this.width = 1200; this.height = 400; setTimeout(() => this.onload && this.onload(), 0); }
    };
    api.uploadMySignature.mockResolvedValue({});
    api.refreshCurrentUser.mockResolvedValue({ id: "u1", role: "clinician", has_signature: true });
    api.getMySignatureBlob.mockResolvedValue("blob:saved");
    try {
      render(<Profile />);
      const input = screen.getByLabelText("Or upload a picture of your signature");
      fireEvent.change(input, { target: { files: [new File(["x"], "sig.jpg", { type: "image/jpeg" })] } });
      expect(await screen.findByAltText("Uploaded signature preview")).toBeTruthy();
      expect(api.uploadMySignature).not.toHaveBeenCalled();
      fireEvent.click(screen.getByRole("button", { name: "Save signature" }));
      await waitFor(() => expect(api.uploadMySignature).toHaveBeenCalledTimes(1));
      expect(api.uploadMySignature.mock.calls[0][0].type).toBe("image/png");
    } finally {
      global.Image = realImage;
    }
  });
});
