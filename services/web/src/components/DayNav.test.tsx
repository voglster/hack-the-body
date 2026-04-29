import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { DayNav } from "./DayNav";
import { shiftLocalISO, todayLocalISO } from "../lib/tz";

describe("DayNav", () => {
  it("shows 'Today' label and disables forward chevron when on today", () => {
    render(<DayNav day={todayLocalISO()} onChange={vi.fn()} />);
    expect(screen.getByText("Today")).toBeTruthy();
    expect((screen.getByLabelText("next day") as HTMLButtonElement).disabled).toBe(true);
    expect(screen.queryByRole("button", { name: "jump to today" })).toBeNull();
  });

  it("calls onChange with previous day when ◀ clicked", () => {
    const today = todayLocalISO();
    const onChange = vi.fn();
    render(<DayNav day={today} onChange={onChange} />);
    fireEvent.click(screen.getByLabelText("previous day"));
    expect(onChange).toHaveBeenCalledWith(shiftLocalISO(today, -1));
  });

  it("disables ◀ at the 30-day floor", () => {
    const floor = shiftLocalISO(todayLocalISO(), -30);
    render(<DayNav day={floor} onChange={vi.fn()} />);
    expect((screen.getByLabelText("previous day") as HTMLButtonElement).disabled).toBe(true);
  });

  it("shows the today jump button on past days and uses it", () => {
    const today = todayLocalISO();
    const yesterday = shiftLocalISO(today, -1);
    const onChange = vi.fn();
    render(<DayNav day={yesterday} onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: "jump to today" }));
    expect(onChange).toHaveBeenCalledWith(today);
  });
});
