// The mock ASR vendor's audio catalog is demo fixture data, not a real API
// surface — mirrored from /mock-asr/mock-transcripts.js.
export const KNOWN_CHUNKS = [
  "audio-file-1.wav",
  "audio-file-2.wav",
  "audio-file-3.wav",
  "audio-file-4.wav",
  "audio-file-5.wav",
  "audio-file-6.wav",
  "audio-file-7.wav",
  "audio-file-8.wav",
  "audio-file-9.wav",
  "audio-file-10.wav",
] as const;

/** `shouldError: true` in the mock — every ASR call for it returns 500. */
export const POISON_CHUNK = "audio-file-8.wav";
