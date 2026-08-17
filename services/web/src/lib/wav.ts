/**
 * Audio encoding for voice food entry.
 *
 * The browser decodes its own recording and uploads 16 kHz mono PCM, rather
 * than shipping the container up and decoding server-side. That keeps ffmpeg
 * — and ~100 MB — out of the API image, and makes the server leg a
 * pass-through to WhisperLive, which wants exactly this format.
 */

/** How long any recording may run. A dictated meal is a sentence. */
export const MAX_RECORDING_SECONDS = 60;

/** WhisperLive's sample rate. Not negotiable on its side. */
export const TARGET_SAMPLE_RATE = 16000;

/**
 * Nearest-neighbour decimation. Speech at 16 kHz through a Whisper model does
 * not reward a windowed resampler, and this has no dependencies.
 */
export function downsampleTo16k(input: Float32Array, inputRate: number): Float32Array {
  if (inputRate === TARGET_SAMPLE_RATE) return input;
  const ratio = inputRate / TARGET_SAMPLE_RATE;
  const out = new Float32Array(Math.floor(input.length / ratio));
  for (let i = 0; i < out.length; i++) out[i] = input[Math.floor(i * ratio)];
  return out;
}

export function encodeWav(samples: Float32Array, sampleRate: number): Blob {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);
  const ascii = (offset: number, text: string) => {
    for (let i = 0; i < text.length; i++) view.setUint8(offset + i, text.charCodeAt(i));
  };

  ascii(0, "RIFF");
  view.setUint32(4, 36 + samples.length * 2, true);
  ascii(8, "WAVE");
  ascii(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);          // PCM
  view.setUint16(22, 1, true);          // mono
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  ascii(36, "data");
  view.setUint32(40, samples.length * 2, true);

  for (let i = 0; i < samples.length; i++) {
    // Clamp rather than let the cast wrap: a wrapped peak is a click, and a
    // click mid-word is a word the decoder loses.
    const s = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(44 + i * 2, s < 0 ? s * 32768 : s * 32767, true);
  }
  return new Blob([buffer], { type: "audio/wav" });
}
