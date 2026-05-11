import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CoachChatPanel } from "./CoachChatPanel";

vi.mock("../api/client", () => ({
  api: {
    coachThreadActive: vi.fn().mockResolvedValue({
      id: "tid1",
      started_at: "2026-05-10T12:00:00Z",
      last_activity_at: "2026-05-10T12:00:00Z",
      surface: "web",
      turns: [
        { role: "coach", text: "Sleep solid.", ts: "2026-05-10T12:00:00Z" },
      ],
    }),
    coachThreadReply: vi.fn(),
  },
}));

function wrap(node: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{node}</QueryClientProvider>;
}

describe("CoachChatPanel", () => {
  it("renders the first coach turn from the active thread", async () => {
    render(wrap(<CoachChatPanel />));
    expect(await screen.findByText(/sleep solid/i)).toBeTruthy();
  });
});
