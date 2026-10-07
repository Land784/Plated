import { describe, expect, it } from "vitest";

import { OTP_INPUT_MAX_LENGTH, normalizeOtpCode } from "@/lib/plated/otp";

describe("email code", () => {
  it("accepts the project's 8-digit codes, with or without spaces", () => {
    expect(normalizeOtpCode("12345678")).toBe("12345678");
    expect(normalizeOtpCode(" 1234 5678 ")).toBe("12345678");
  });

  it("accepts 6 to 10 digits only", () => {
    expect(normalizeOtpCode("123456")).toBe("123456");
    expect(normalizeOtpCode("1234567890")).toBe("1234567890");
    expect(normalizeOtpCode("12345")).toBeNull();
    expect(normalizeOtpCode("12345678901")).toBeNull();
    expect(normalizeOtpCode("1234-5678")).toBeNull();
    expect(normalizeOtpCode("")).toBeNull();
  });

  it("leaves room in the field for a spaced-out 10-digit code", () => {
    expect(OTP_INPUT_MAX_LENGTH).toBeGreaterThanOrEqual("12345 67890".length);
  });
});
