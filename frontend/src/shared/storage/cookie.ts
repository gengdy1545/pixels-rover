/**
 * Read a cookie value by name from document.cookie.
 */
export function getCookie(name: string): string | null {
  const match = document.cookie.match(new RegExp('(^| )' + name + '=([^;]+)'));
  return match ? decodeURIComponent(match[2]) : null;
}

/**
 * Check if the user appears to be logged in based on the non-HttpOnly logged_in cookie.
 * This is a UI hint only — the real auth check is done server-side via HttpOnly cookies.
 */
export function isLoggedInCookie(): boolean {
  return getCookie('logged_in') === 'true';
}
