import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useNow } from "./useNow";

describe("useNow", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("returns the current date and updates after the interval", () => {
    vi.setSystemTime(new Date("2026-05-19T10:00:00Z"));
    const { result } = renderHook(() => useNow(30_000));
    const t0 = result.current.getTime();
    act(() => {
      vi.advanceTimersByTime(30_000);
    });
    expect(result.current.getTime()).toBeGreaterThan(t0);
  });
});
