// The one-time code from a sign-in or invite email. Supabase's code length
// is a project setting (6 to 10 digits; this project sends 8), so any
// length in that range is accepted.

export const OTP_MIN_DIGITS = 6;
export const OTP_MAX_DIGITS = 10;

/** Room for the longest code typed with spaces between groups. */
export const OTP_INPUT_MAX_LENGTH = OTP_MAX_DIGITS * 2;

/** The digits of a typed code with spaces removed, or null if it isn't 6 to 10 digits. */
export function normalizeOtpCode(raw: string): string | null {
  const token = raw.replace(/\s/g, "");
  return /^\d+$/.test(token) && token.length >= OTP_MIN_DIGITS && token.length <= OTP_MAX_DIGITS ? token : null;
}
