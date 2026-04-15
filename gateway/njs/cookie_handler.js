/**
 * Pixels Rover — NJS Cookie Handler
 *
 * Intercepts auth-service JSON responses and injects HttpOnly cookies
 * at the gateway layer, so Java Auth Service remains a pure API.
 *
 * Handles:
 *   - POST /api/v1/auth/login    → inject token cookies
 *   - POST /api/v1/auth/refresh  → inject token cookies
 *   - POST /api/v1/auth/logout   → clear token cookies
 *   - POST /api/v1/auth/logout-all → clear token cookies
 *
 * Cookie configuration is read from nginx variables set via env.
 */

/**
 * Generate a UUID v4 string for CSRF tokens.
 */
function generateUUID() {
    // NJS supports crypto module since 0.7.0
    var bytes = require('crypto').randomBytes(16);
    bytes[6] = (bytes[6] & 0x0f) | 0x40; // version 4
    bytes[8] = (bytes[8] & 0x3f) | 0x80; // variant 1
    var hex = bytes.toString('hex');
    return hex.substr(0, 8) + '-' + hex.substr(8, 4) + '-' +
           hex.substr(12, 4) + '-' + hex.substr(16, 4) + '-' +
           hex.substr(20, 12);
}

/**
 * Build a Set-Cookie header value.
 *
 * @param {string} name       - Cookie name
 * @param {string} value      - Cookie value (empty string to clear)
 * @param {string} path       - Cookie path
 * @param {number} maxAge     - Max-Age in seconds (0 to clear)
 * @param {boolean} httpOnly  - Whether the cookie is HttpOnly
 * @param {Object} r          - NJS request object (for reading config vars)
 * @returns {string} Set-Cookie header value
 */
function buildSetCookie(name, value, path, maxAge, httpOnly, r) {
    var secure = r.variables.cookie_secure === 'true';
    var sameSite = r.variables.cookie_samesite || 'Lax';
    var domain = r.variables.cookie_domain || '';

    var parts = [name + '=' + value];
    parts.push('Path=' + path);
    parts.push('Max-Age=' + maxAge);
    parts.push('SameSite=' + sameSite);
    if (httpOnly) {
        parts.push('HttpOnly');
    }
    if (secure) {
        parts.push('Secure');
    }
    if (domain) {
        parts.push('Domain=' + domain);
    }
    return parts.join('; ');
}

/**
 * Inject token cookies from the upstream JSON response body.
 * Called by js_body_filter for login and refresh endpoints.
 *
 * Expected upstream response body (ApiResponse wrapper):
 *   { "code": 200, "data": { "accessToken": "...", "refreshToken": "..." }, ... }
 */
function injectTokenCookies(r, data, flags) {
    // Accumulate response body chunks
    if (!r.variables.response_body) {
        r.variables.response_body = '';
    }
    r.variables.response_body += data;

    if (!flags.last) {
        // Not the last chunk yet — don't emit anything
        r.sendBuffer('', {last: false});
        return;
    }

    var body = r.variables.response_body;

    try {
        var json = JSON.parse(body);

        // Only inject cookies for successful responses
        if (json.code === 200 && json.data) {
            var accessToken = json.data.accessToken;
            var refreshToken = json.data.refreshToken;

            var accessMaxAge = parseInt(r.variables.access_token_max_age) || 3600;
            var refreshMaxAge = parseInt(r.variables.refresh_token_max_age) || 604800;

            // Initialize Set-Cookie array once
            r.headersOut['Set-Cookie'] = r.headersOut['Set-Cookie'] || [];

            if (accessToken) {
                // access_token — HttpOnly
                r.headersOut['Set-Cookie'].push(
                    buildSetCookie('access_token', accessToken, '/', accessMaxAge, true, r)
                );

                // XSRF-TOKEN — non-HttpOnly, readable by JavaScript
                r.headersOut['Set-Cookie'].push(
                    buildSetCookie('XSRF-TOKEN', generateUUID(), '/', accessMaxAge, false, r)
                );

                // logged_in — non-HttpOnly, UI state indicator
                r.headersOut['Set-Cookie'].push(
                    buildSetCookie('logged_in', 'true', '/', refreshMaxAge, false, r)
                );
            }

            if (refreshToken) {
                // refresh_token — HttpOnly, restricted path
                r.headersOut['Set-Cookie'].push(
                    buildSetCookie('refresh_token', refreshToken, '/api/v1/auth/refresh', refreshMaxAge, true, r)
                );
            }
        }
    } catch (e) {
        r.error('cookie_handler: failed to parse response body: ' + e.message);
    }

    // Send the original body through unchanged
    r.sendBuffer(body, {last: true});
}

/**
 * Inject cookie-clearing headers for logout endpoints.
 * Called by js_header_filter for logout and logout-all endpoints.
 */
function clearTokenCookies(r) {
    // Only clear cookies for successful responses
    var status = r.status;
    if (status >= 200 && status < 300) {
        r.headersOut['Set-Cookie'] = r.headersOut['Set-Cookie'] || [];

        // access_token — HttpOnly (matches write)
        r.headersOut['Set-Cookie'].push(
            buildSetCookie('access_token', '', '/', 0, true, r)
        );

        // XSRF-TOKEN — non-HttpOnly (matches write)
        r.headersOut['Set-Cookie'].push(
            buildSetCookie('XSRF-TOKEN', '', '/', 0, false, r)
        );

        // logged_in — non-HttpOnly (matches write)
        r.headersOut['Set-Cookie'].push(
            buildSetCookie('logged_in', '', '/', 0, false, r)
        );

        // refresh_token — HttpOnly, restricted path (matches write)
        r.headersOut['Set-Cookie'].push(
            buildSetCookie('refresh_token', '', '/api/v1/auth/refresh', 0, true, r)
        );
    }
}

/**
 * Verify CSRF token for state-changing requests.
 * Compares the XSRF-TOKEN cookie with the X-XSRF-TOKEN header (double-submit pattern).
 *
 * Called by js_set to produce a variable used in nginx `if` conditions.
 * Returns "1" if CSRF is valid or not required, "0" if invalid.
 */
function verifyCsrf(r) {
    var method = r.method;

    // Safe methods don't need CSRF verification
    if (method === 'GET' || method === 'HEAD' || method === 'OPTIONS') {
        return '1';
    }

    // Auth public endpoints are exempt from CSRF
    var uri = r.uri;
    if (uri === '/api/v1/auth/login' ||
        uri === '/api/v1/auth/register' ||
        uri === '/api/v1/auth/captcha' ||
        uri === '/api/v1/auth/refresh') {
        return '1';
    }

    // Extract XSRF-TOKEN from cookies
    var cookieHeader = r.headersIn['Cookie'] || '';
    var csrfCookie = '';
    var pairs = cookieHeader.split(';');
    for (var i = 0; i < pairs.length; i++) {
        var pair = pairs[i].trim();
        if (pair.indexOf('XSRF-TOKEN=') === 0) {
            csrfCookie = pair.substring('XSRF-TOKEN='.length);
            break;
        }
    }

    // Get X-XSRF-TOKEN header
    var csrfHeader = r.headersIn['X-XSRF-TOKEN'] || '';

    // Both must be present and match
    if (csrfCookie && csrfHeader && csrfCookie === csrfHeader) {
        return '1';
    }

    // If no CSRF cookie exists (e.g., non-browser client using Authorization header),
    // allow the request through — the auth_request will still verify the JWT
    if (!csrfCookie && !csrfHeader) {
        return '1';
    }

    return '0';
}

/**
 * Validate the request Origin against the CORS allowed origins whitelist.
 * The whitelist is injected via envsubst from the CORS_ALLOWED_ORIGINS env var.
 *
 * Called by js_set to produce the $cors_origin variable used in cors.conf.
 * Returns the origin if allowed, or empty string if not.
 *
 * Special value '*' allows all origins (development mode).
 */
function validateOrigin(r) {
    var allowedRaw = '${CORS_ALLOWED_ORIGINS}';
    var origin = r.headersIn['Origin'] || '';

    if (!origin) {
        return '';
    }

    // Dev mode: allow all origins
    if (allowedRaw === '*') {
        return origin;
    }

    // Check against whitelist (comma-separated)
    var allowed = allowedRaw.split(',');
    for (var i = 0; i < allowed.length; i++) {
        if (allowed[i].trim() === origin) {
            return origin;
        }
    }

    r.warn('CORS: rejected origin ' + origin + ' (not in whitelist)');
    return '';
}

export default { injectTokenCookies, clearTokenCookies, verifyCsrf, validateOrigin };
