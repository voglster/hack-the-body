import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { NudgesCard } from "./NudgesCard";

vi.mock("../api/client", () => ({
  api: {
    fetchNudges: vi.fn(),
    dismissNudge: vi.fn(),
  },
}));

import { api } from "../api/client";

function wrap(ui: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{ui}</QueryClientProvider>;
}

describe("NudgesCard", () => {
  it("renders nothing when no nudges fire", async () => {
    (api.fetchNudges as any).mockResolvedValue({ nudges: [], generated_at: "x" });
    const { container } = render(wrap(<NudgesCard />));
    await waitFor(() => expect(api.fetchNudges).toHaveBeenCalled());
    expect(container.textContent ?? "").toBe("");
  });

  it("renders a row per fired nudge", async () => {
    (api.fetchNudges as any).mockResolvedValue({
      nudges: [
        { id: "vitamins_missing", kind: "vitamin", severity: "warn",
          title: "Vitamins not taken yet", body: "It's past noon.",
          dismissable: true },
        { id: "no_weighin", kind: "weight", severity: "info",
          title: "No weigh-in yet", body: "Step on the scale.",
          dismissable: true },
      ],
      generated_at: "x",
    });
    render(wrap(<NudgesCard />));
    expect(await screen.findByText("Vitamins not taken yet")).toBeTruthy();
    expect(screen.getByText("No weigh-in yet")).toBeTruthy();
  });

  it("dismisses a nudge optimistically", async () => {
    (api.fetchNudges as any).mockResolvedValue({
      nudges: [
        { id: "vitamins_missing", kind: "vitamin", severity: "warn",
          title: "Vitamins not taken yet", body: "x", dismissable: true },
      ],
      generated_at: "x",
    });
    (api.dismissNudge as any).mockResolvedValue({ ok: true });

    render(wrap(<NudgesCard />));
    const row = await screen.findByText("Vitamins not taken yet");
    expect(row).toBeTruthy();
    const dismiss = screen.getByLabelText("dismiss vitamins_missing");
    fireEvent.click(dismiss);
    await waitFor(() =>
      expect(api.dismissNudge).toHaveBeenCalledWith({
        nudge_id: "vitamins_missing", until: "end_of_day",
      }),
    );
  });
});
