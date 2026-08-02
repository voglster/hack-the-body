import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "../api/client";
import type { CoachThread, CoachTurn } from "../api/types";
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

function threadWithTurn(turn: CoachTurn): CoachThread {
  return {
    id: "tid1",
    started_at: "2026-05-10T12:00:00Z",
    last_activity_at: "2026-05-10T12:00:00Z",
    surface: "web",
    turns: [turn],
  };
}

describe("CoachChatPanel", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders the first coach turn from the active thread", async () => {
    render(wrap(<CoachChatPanel />));
    expect(await screen.findByText(/sleep solid/i)).toBeTruthy();
  });

  it("resolves {{anchor}} placeholders in a coach turn", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.setSystemTime(new Date("2026-05-19T21:15:00-05:00"));
    vi.mocked(api.coachThreadActive).mockResolvedValueOnce(
      threadWithTurn({
        role: "coach",
        text: "Lights out at {{lights_out}}.",
        ts: "2026-05-10T12:00:00Z",
        anchors: { lights_out: "2026-05-19T22:00:00-05:00" },
      }),
    );
    render(wrap(<CoachChatPanel />));
    expect(await screen.findByText(/in 45m/)).toBeTruthy();
  });
});
