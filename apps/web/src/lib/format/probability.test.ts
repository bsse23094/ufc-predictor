import { describe, expect, it } from "vitest";

import { formatProbability } from "./probability";

describe("formatProbability", () => {
  it("formats a bounded probability with an explicit percentage", () => {
    expect(formatProbability(0.543)).toBe("54.3%");
  });

  it("rejects values that cannot represent a probability", () => {
    expect(() => formatProbability(1.01)).toThrow(RangeError);
  });
});
