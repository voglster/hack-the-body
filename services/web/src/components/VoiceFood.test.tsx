import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { VoiceFood } from "./VoiceFood";

// `useVoiceRecorder` is mocked with a *real* `useState` inside the mock
// factory, not a plain mutated object. A plain object mutated between
// clicks (`mockRecorder.state = "recording"`) is not React state — mutating
// it triggers no re-render, so the component would keep rendering the idle
// button and the "Stop" button would never appear, making the test
// vacuously pass or hang. Driving `state` through a real hook means
// clicking "record" genuinely flips the rendered UI to the recording view,
// and clicking "stop" genuinely flips it back — exercising the same render
// path a real browser session would.
vi.mock("../hooks/useVoiceRecorder", () => ({
  useVoiceRecorder: () => {
    const [state, setState] = useState<"idle" | "recording">("idle");
    return {
      state,
      seconds: 0,
      start: () => { setState("recording"); },
      stop: async () => {
        setState("idle");
        return new Blob(["x"], { type: "audio/wav" });
      },
    };
  },
}));

vi.mock("../api/client", () => ({
  api: {
    logVoiceFood: vi.fn().mockResolvedValue({
      transcript: "two scrambled eggs and toast",
      items: [
        { name: "Scrambled Eggs", servings: 2, calories: 150 },
        { name: "Toast", servings: 1, calories: 80 },
      ],
      logged_entry_ids: ["e1", "e2"],
      count: 2,
    }),
    deleteEntry: vi.fn().mockResolvedValue(undefined),
  },
}));

async function speakAMeal() {
  fireEvent.click(screen.getByRole("button", { name: /record|speak/i }));
  const stopButton = await screen.findByRole("button", { name: /stop|done/i });
  fireEvent.click(stopButton);
}

describe("VoiceFood", () => {
  it("shows the transcript and every parsed item after a dictation", async () => {
    const { api } = await import("../api/client");
    render(<VoiceFood onLogged={vi.fn()} />);

    await speakAMeal();

    await waitFor(() => expect(api.logVoiceFood).toHaveBeenCalled());
    expect(await screen.findByText(/two scrambled eggs and toast/i)).toBeTruthy();
    expect(screen.getByText(/Scrambled Eggs/)).toBeTruthy();
    expect(screen.getByText(/Toast/)).toBeTruthy();
  });

  it("undoes by deleting every entry it wrote, not just the first", async () => {
    const { api } = await import("../api/client");
    render(<VoiceFood onLogged={vi.fn()} />);

    await speakAMeal();

    const undo = await screen.findByRole("button", { name: /undo/i });
    fireEvent.click(undo);

    await waitFor(() => {
      expect(api.deleteEntry).toHaveBeenCalledWith("e1");
      expect(api.deleteEntry).toHaveBeenCalledWith("e2");
    });
    expect(api.deleteEntry).toHaveBeenCalledTimes(2);
  });
});
