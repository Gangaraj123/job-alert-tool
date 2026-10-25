/**
 * Shared-password gate.
 *
 * The dashboard exposes a personal job search — which roles you are
 * watching and which you have applied to — so it should not sit open on a
 * public URL. One password, shared between the two people who use it.
 *
 * The session is a signed cookie rather than a server-side session store:
 * there is no user table to look things up in, and a stateless token keeps
 * the whole thing to one env var. Signed with HMAC-SHA256 via Web Crypto so
 * it works unchanged in the Edge runtime, where Node's crypto is absent.
 */
export const SESSION_COOKIE = "ja_session";

/** Long-lived on purpose: "remember this browser" is the whole point. */
export const SESSION_DAYS = 90;

const enc = new TextEncoder();

async function hmac(secret: string, payload: string): Promise<string> {
  const key = await crypto.subtle.importKey(
    "raw",
    enc.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const sig = await crypto.subtle.sign("HMAC", key, enc.encode(payload));
  return Array.from(new Uint8Array(sig))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

/** Compares in constant time, so a wrong value leaks nothing by timing. */
function safeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

export async function createSessionToken(secret: string): Promise<string> {
  const expires = Date.now() + SESSION_DAYS * 86_400_000;
  return `${expires}.${await hmac(secret, String(expires))}`;
}

export async function isValidSession(
  token: string | undefined,
  secret: string,
): Promise<boolean> {
  if (!token) return false;
  const [expires, signature] = token.split(".");
  if (!expires || !signature) return false;
  // Check expiry before the signature so an expired token is cheap to reject.
  if (!Number(expires) || Number(expires) < Date.now()) return false;
  return safeEqual(signature, await hmac(secret, expires));
}

export async function checkPassword(
  attempt: string,
  expected: string,
): Promise<boolean> {
  // Hash both sides first: comparing raw strings of differing length would
  // exit early and leak the password's length.
  const [a, b] = await Promise.all([
    hmac("compare", attempt),
    hmac("compare", expected),
  ]);
  return safeEqual(a, b);
}
