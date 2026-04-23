/**
 * Browser navigation helpers for auth side effects outside React context.
 */

function currentReturnTo(): string {
  const path = `${window.location.pathname}${window.location.search}${window.location.hash}`;
  return path === '/login' || path === '/register' ? '/home' : path;
}

function absoluteReturnTo(returnTo: string): string {
  return new URL(returnTo, window.location.origin).toString();
}

export function kratosLoginUrl(returnTo = currentReturnTo()): string {
  return `/self-service/login/browser?return_to=${encodeURIComponent(absoluteReturnTo(returnTo))}`;
}

export function kratosRegistrationUrl(returnTo = '/home'): string {
  return `/self-service/registration/browser?return_to=${encodeURIComponent(absoluteReturnTo(returnTo))}`;
}

export function kratosLogoutUrl(returnTo = '/login'): string {
  return `/self-service/logout/browser?return_to=${encodeURIComponent(absoluteReturnTo(returnTo))}`;
}

export function redirectToLogin(returnTo?: string): void {
  window.location.assign(kratosLoginUrl(returnTo));
}

export function redirectToRegistration(returnTo?: string): void {
  window.location.assign(kratosRegistrationUrl(returnTo));
}

export function redirectToLogout(returnTo?: string): void {
  window.location.assign(kratosLogoutUrl(returnTo));
}
