import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { HabitsCard } from "./HabitsCard";

vi.mock("../api/client", () => ({
  api: {
    habitsToday: vi.fn().mockResolvedValue([
      { id: "h1", name: "make the bed", kind: "manual", status: "unknown", source: "manual" },
      { id: "h2", name: "bed by 10", kind: "auto", status: "done", source: "auto", resolver: "bed_by_10" },
    ]),
    habitCreate: vi.fn(),
    habitMarkStatus: vi.fn(),
  },
}));

function wrap(node: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{node}</QueryClientProvider>;
}

describe("HabitsCard", () => {
  it("lists today's habits with status indicators", async () => {
    render(wrap(<HabitsCard />));
    expect(await screen.findByText(/make the bed/i)).toBeTruthy();
    expect(screen.getByText(/bed by 10/i)).toBeTruthy();
  });
});
