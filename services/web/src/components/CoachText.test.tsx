import "@testing-library/jest-dom";
import { render, screen, act } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CoachText } from "./CoachText";

describe("CoachText", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-05-19T21:15:00-05:00"));
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders text with a single anchor as 'clock (in Nm)'", () => {
    render(
      <CoachText
        text="Lights out at {{lights_out}} keeps the streak."
        anchors={{ lights_out: "2026-05-19T22:00:00-05:00" }}
      />,
    );
    expect(screen.getByText(/Lights out at/)).toBeInTheDocument();
    expect(screen.getByText(/in 45m/)).toBeInTheDocument();
  });

  it("ticks the relative chip after time passes", () => {
    render(
      <CoachText
        text="At {{x}}"
        anchors={{ x: "2026-05-19T22:00:00-05:00" }}
      />,
    );
    expect(screen.getByText(/in 45m/)).toBeInTheDocument();
    act(() => { vi.advanceTimersByTime(60_000); });
    expect(screen.getByText(/in 44m/)).toBeInTheDocument();
  });

  it("renders 'Nm ago' when anchor is in the past", () => {
    render(
      <CoachText
        text="Was at {{x}}"
        anchors={{ x: "2026-05-19T21:10:00-05:00" }}
      />,
    );
    expect(screen.getByText(/5m ago/)).toBeInTheDocument();
  });

  it("renders plain text when no anchors provided", () => {
    render(<CoachText text="No times here" anchors={null} />);
    expect(screen.getByText("No times here")).toBeInTheDocument();
  });

  it("leaves unmatched placeholders as literal text", () => {
    render(<CoachText text="Hello {{nope}}" anchors={{}} />);
    expect(screen.getByText(/\{\{nope\}\}/)).toBeInTheDocument();
  });
});
