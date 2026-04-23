/**
 * Read a cookie value by name from document.cookie.
 */
export function getCookie(name: string): string | null {
  const match = document.cookie.match(new RegExp('(^| )' + name + '=([^;]+)'));
  return match ? decodeURIComponent(match[2]) : null;
}

function randomToken(): string {
  const bytes = new Uint8Array(32);
  if (globalThis.crypto?.getRandomValues) {
    globalThis.crypto.getRandomValues(bytes);
  } else {
    for (let i = 0; i < bytes.length; i += 1) {
      bytes[i] = Math.floor(Math.random() * 256);
    }
  }
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
}

/**
 * Ensure a JS-readable double-submit CSRF cookie exists for protected APIs.
 * The thin policy adapter validates this cookie against X-XSRF-TOKEN before
 * forwarding unsafe methods to Oathkeeper.
 */
export function ensureXsrfCookie(): string {
  const existing = getCookie('XSRF-TOKEN');
  if (existing) {
    return existing;
  }
  const token = randomToken();
  document.cookie = `XSRF-TOKEN=${encodeURIComponent(token)}; Path=/; SameSite=Lax`;
  return token;
}

/**
 * Kratos keeps the authoritative session in an HttpOnly cookie. This helper is
 * kept for legacy call sites and only reports whether the session cookie name is
 * visible in document.cookie, which usually means "false" for HttpOnly cookies.
 */
export function isLoggedInCookie(): boolean {
  return getCookie('ory_kratos_session') !== null;
}
