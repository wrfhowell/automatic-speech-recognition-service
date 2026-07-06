import { describe, expect, it } from "vitest";
import { formatSeconds } from "./format";

describe("formatSeconds", () => {
  it("renders one decimal with an s suffix", () => {
    expect(formatSeconds(8.44)).toBe("8.4 s");
    expect(formatSeconds(15)).toBe("15.0 s");
  });

  it("renders an em dash when the value is absent", () => {
    expect(formatSeconds(null)).toBe("—");
    expect(formatSeconds(undefined)).toBe("—");
  });
});
