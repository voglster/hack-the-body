import { describe, expect, it } from "vitest";

import { downsampleTo16k, encodeWav, MAX_RECORDING_SECONDS } from "./wav";

describe("downsampleTo16k", () => {
  it("halves a 32k input", () => {
    const out = downsampleTo16k(new Float32Array(3200), 32000);
    expect(out.length).toBe(1600);
  });

  it("passes 16k through untouched", () => {
    const input = new Float32Array([0.5, -0.5]);
    expect(Array.from(downsampleTo16k(input, 16000))).toEqual([0.5, -0.5]);
  });
});

describe("encodeWav", () => {
  it("writes a RIFF/WAVE header", async () => {
    const blob = encodeWav(new Float32Array([0, 0.5]), 16000);
    const bytes = new Uint8Array(await blob.arrayBuffer());
    const tag = String.fromCharCode(...bytes.slice(0, 4));
    const fmt = String.fromCharCode(...bytes.slice(8, 12));
    expect(tag).toBe("RIFF");
    expect(fmt).toBe("WAVE");
  });

  it("emits 16-bit samples after the 44-byte header", async () => {
    const blob = encodeWav(new Float32Array([0, 0.5, -0.5]), 16000);
    expect(blob.size).toBe(44 + 3 * 2);
  });

  it("clamps out-of-range samples instead of wrapping", async () => {
    const blob = encodeWav(new Float32Array([2.0, -2.0]), 16000);
    const view = new DataView(await blob.arrayBuffer());
    expect(view.getInt16(44, true)).toBe(32767);
    expect(view.getInt16(46, true)).toBe(-32768);
  });
});

describe("MAX_RECORDING_SECONDS", () => {
  it("is one minute", () => {
    expect(MAX_RECORDING_SECONDS).toBe(60);
  });
});
