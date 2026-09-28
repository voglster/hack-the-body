import { renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useReloadOnDeploy } from "./useReloadOnDeploy";

afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

describe("useReloadOnDeploy", () => {
  it("reloads once the build id changes", async () => {
    vi.useFakeTimers();
    const builds = ["aaa", "aaa", "bbb"];
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(
      new Response(JSON.stringify({ build: builds.shift() })))));
    const reload = vi.fn();
    vi.stubGlobal("location", { ...window.location, reload });
    renderHook(() => useReloadOnDeploy(true));
    await vi.advanceTimersByTimeAsync(3 * 60_000);
    expect(reload).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(3 * 60_000);
    expect(reload).toHaveBeenCalledOnce();
  });
});
