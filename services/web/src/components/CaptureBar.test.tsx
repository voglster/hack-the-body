import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { api } from "../api/client";
import { CaptureBar } from "./CaptureBar";

vi.mock("../api/client", () => ({
  api: {
    capture: vi.fn().mockResolvedValue({ id: "c1", status: "pending", input: {}, entry_ids: [] }),
    captureVoice: vi.fn(),
  },
}));

describe("CaptureBar", () => {
  it("Enter captures; Shift+Enter keeps typing a pasted breakdown", async () => {
    const onCaptured = vi.fn();
    render(<CaptureBar device="phone" onCaptured={onCaptured} onError={vi.fn()} />);
    const box = screen.getByPlaceholderText("What did you eat?");
    fireEvent.change(box, { target: { value: "Crepe Shell: 250\n2 Eggs: 150" } });
    fireEvent.keyDown(box, { key: "Enter", shiftKey: true });
    expect(api.capture).not.toHaveBeenCalled();
    fireEvent.keyDown(box, { key: "Enter" });
    await waitFor(() => expect(api.capture).toHaveBeenCalledWith(
      { text: "Crepe Shell: 250\n2 Eggs: 150", device: "phone" }));
    expect(onCaptured).toHaveBeenCalled();
  });

  it("backdates when viewing a past day and hides the mic", async () => {
    render(<CaptureBar device="phone" ts="2026-09-26T17:00:00Z" onCaptured={vi.fn()} onError={vi.fn()} />);
    expect(screen.queryByLabelText("record")).toBeNull();
    const box = screen.getByPlaceholderText("What did you eat?");
    fireEvent.change(box, { target: { value: "burger" } });
    fireEvent.keyDown(box, { key: "Enter" });
    await waitFor(() => expect(api.capture).toHaveBeenLastCalledWith(
      { text: "burger", device: "phone", ts: "2026-09-26T17:00:00Z" }));
  });
});
