import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { api } from "../api/client";
import { LogPage } from "./Log";

vi.mock("../api/client", () => ({
  api: {
    captureToday: vi.fn().mockResolvedValue({ captures: [], totals: { calories: 0, protein_g: 0 }, unresolved: 0 }),
    captureInbox: vi.fn().mockResolvedValue([
      { id: "c9", ts: "2026-09-28T12:00:00Z", source: "text", status: "needs_confirm", entry_ids: [],
        input: { text: "premier shake" },
        items: [{ text: "premier shake", status: "ask", candidates: [
          { food_id: "f1", name: "Chocolate Premier", quantity_g: 325 },
          { food_id: "f2", name: "Vanilla Premier", quantity_g: 325 }] }] },
    ]),
    captureContext: vi.fn().mockResolvedValue({
      now_local: "2026-09-28T12:00:00-05:00",
      window: { start: "11:00", end: "19:00", state: "open", minutes_to_change: 420 },
      vitamins_done: true, water_oz: 26, water_goal_oz: 100, meals: ["breakfast"],
      first_food_at: "11:30", last_food_at: "11:30",
      suggestions: [{ kind: "food", food_id: "f2", name: "Vanilla Premier Shake", quantity_g: 325 }],
    }),
    capture: vi.fn().mockResolvedValue({ id: "c1", status: "resolved", input: {}, entry_ids: ["e1"] }),
    confirmCapture: vi.fn().mockResolvedValue({}),
    undoCapture: vi.fn().mockResolvedValue(undefined),
    logWater: vi.fn(),
    markVitaminsTaken: vi.fn(),
    captureVoice: vi.fn(),
  },
}));

function renderLog() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}><MemoryRouter><LogPage /></MemoryRouter></QueryClientProvider>,
  );
}

describe("LogPage", () => {
  it("one tap on a suggestion captures it and offers undo", async () => {
    renderLog();
    fireEvent.click(await screen.findByRole("button", { name: "Vanilla Premier Shake" }));
    await waitFor(() => expect(api.capture).toHaveBeenCalledWith(
      expect.objectContaining({ food_id: "f2", quantity_g: 325 })));
    fireEvent.click(await screen.findByRole("button", { name: "Undo" }));
    await waitFor(() => expect(api.undoCapture).toHaveBeenCalledWith("c1"));
  });

  it("answers an inbox question with one tap", async () => {
    renderLog();
    fireEvent.click(await screen.findByRole("button", { name: "Chocolate Premier" }));
    await waitFor(() => expect(api.confirmCapture).toHaveBeenCalledWith(
      "c9", { item_index: 0, candidate_index: 0 }));
  });

  it("shows the eating window and what's already done", async () => {
    renderLog();
    expect(await screen.findByText(/closes 7pm \(7h 0m left\)/)).toBeTruthy();
    expect(screen.queryByText(/Vitamins/)).toBeNull();
    expect(screen.getByText(/26\/100 oz/)).toBeTruthy();
  });

  it("typed text is captured without waiting on a parse", async () => {
    renderLog();
    const input = screen.getByPlaceholderText("What did you eat?");
    fireEvent.change(input, { target: { value: "coffee" } });
    fireEvent.submit(input.closest("form")!);
    await waitFor(() => expect(api.capture).toHaveBeenCalledWith(
      expect.objectContaining({ text: "coffee" })));
  });
});
