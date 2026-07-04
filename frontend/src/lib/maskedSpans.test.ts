import { describe, expect, it } from "vitest";
import { maskLegend, parseMaskedTranscript } from "./maskedSpans";

describe("parseMaskedTranscript", () => {
  it("splits text, mask tokens, and gap markers", () => {
    const segments = parseMaskedTranscript(
      "Patient [NAME] seen on [DATE].\n[chunk 2 unavailable]\nCall [PHONE].",
    );
    expect(segments).toEqual([
      { kind: "text", text: "Patient " },
      { kind: "mask", label: "NAME" },
      { kind: "text", text: " seen on " },
      { kind: "mask", label: "DATE" },
      { kind: "text", text: ".\n" },
      { kind: "gap", chunk: 2 },
      { kind: "text", text: "\nCall " },
      { kind: "mask", label: "PHONE" },
      { kind: "text", text: "." },
    ]);
  });

  it("returns a single text segment when nothing is masked", () => {
    expect(parseMaskedTranscript("plain prose")).toEqual([
      { kind: "text", text: "plain prose" },
    ]);
  });

  it("handles empty input", () => {
    expect(parseMaskedTranscript("")).toEqual([]);
  });

  it("ignores bracketed text that is not a token", () => {
    const segments = parseMaskedTranscript("a [not a mask] b [x] c");
    expect(segments).toEqual([{ kind: "text", text: "a [not a mask] b [x] c" }]);
  });

  it("parses adjacent tokens with no text between", () => {
    expect(parseMaskedTranscript("[NAME][AGE]")).toEqual([
      { kind: "mask", label: "NAME" },
      { kind: "mask", label: "AGE" },
    ]);
  });

  it("parses multi-digit gap ordinals", () => {
    expect(parseMaskedTranscript("[chunk 12 unavailable]")).toEqual([
      { kind: "gap", chunk: 12 },
    ]);
  });
});

describe("maskLegend", () => {
  it("dedupes labels in first-appearance order", () => {
    const segments = parseMaskedTranscript("[DATE] [NAME] [DATE] [MRN]");
    expect(maskLegend(segments)).toEqual(["DATE", "NAME", "MRN"]);
  });
});
