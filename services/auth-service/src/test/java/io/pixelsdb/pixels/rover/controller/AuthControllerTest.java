package io.pixelsdb.pixels.rover.controller;

import com.fasterxml.jackson.databind.ObjectMapper;
import io.pixelsdb.pixels.rover.config.security.CookieHelper;
import io.pixelsdb.pixels.rover.exception.ServiceException;
import io.pixelsdb.pixels.rover.rest.request.LoginRequest;
import io.pixelsdb.pixels.rover.rest.request.RegisterRequest;
import io.pixelsdb.pixels.rover.rest.response.AccessTokenResponse;
import io.pixelsdb.pixels.rover.rest.response.CaptchaResponse;
import io.pixelsdb.pixels.rover.rest.response.TokenResponse;
import io.pixelsdb.pixels.rover.rest.response.UserInfoResponse;
import io.pixelsdb.pixels.rover.service.AuthSessionService;
import io.pixelsdb.pixels.rover.service.SysLoginService;
import io.pixelsdb.pixels.rover.service.UserService;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.http.MediaType;
import org.springframework.security.core.userdetails.UserDetailsService;
import org.springframework.test.web.servlet.MockMvc;

import java.util.Map;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doNothing;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * Controller-layer integration tests for {@link AuthController}.
 *
 * <p>User-facing endpoints now consume identity from the gateway-injected
 * {@code X-Auth-User-Id} header (see {@code backend.md §3.1} / §3.4). Tests exercise the
 * controller directly with {@code addFilters = false}; gateway identity validation
 * (including 500 + {@code GATEWAY_IDENTITY_MISSING}) is covered in
 * {@link io.pixelsdb.pixels.rover.config.security.IdentityHeaderValidationFilterTest}.</p>
 */
@WebMvcTest(AuthController.class)
@AutoConfigureMockMvc(addFilters = false)
class AuthControllerTest
{
    private static final String USER_ID_HEADER = "X-Auth-User-Id";
    private static final String SESSION_ID_HEADER = "X-Auth-Session-Id";

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private ObjectMapper objectMapper;

    @MockBean
    private SysLoginService sysLoginService;

    @MockBean
    private UserService userService;

    @MockBean
    private CookieHelper cookieHelper;

    // Required by SecurityConfig but not used in these tests.
    @MockBean
    private UserDetailsService userDetailsService;

    @MockBean
    private AuthSessionService authSessionService;

    // ---------------------------------------------------------------
    // POST /api/v1/auth/login
    // ---------------------------------------------------------------

    @Test
    void loginShouldWriteCookiesOnSuccess() throws Exception
    {
        LoginRequest request = new LoginRequest();
        request.setUsername("alice@example.com");
        request.setPassword("secret");

        TokenResponse tokenResponse = new TokenResponse("access-token", "refresh-token", "session-1");
        when(sysLoginService.login(any(LoginRequest.class), any(), any())).thenReturn(tokenResponse);

        mockMvc.perform(post("/api/v1/auth/login")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(request)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(200))
                .andExpect(jsonPath("$.message").value("Login success"))
                .andExpect(jsonPath("$.data").doesNotExist());

        verify(cookieHelper).writeTokenCookies(any(), eq("access-token"), eq("refresh-token"));
    }

    @Test
    void loginShouldReturn400WhenUsernameIsBlank() throws Exception
    {
        LoginRequest request = new LoginRequest();
        request.setUsername("");
        request.setPassword("secret");

        mockMvc.perform(post("/api/v1/auth/login")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(request)))
                .andExpect(status().isBadRequest());
    }

    @Test
    void loginShouldReturn400WhenPasswordIsBlank() throws Exception
    {
        LoginRequest request = new LoginRequest();
        request.setUsername("alice@example.com");
        request.setPassword("");

        mockMvc.perform(post("/api/v1/auth/login")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(request)))
                .andExpect(status().isBadRequest());
    }

    // ---------------------------------------------------------------
    // POST /api/v1/auth/register
    // ---------------------------------------------------------------

    @Test
    void registerShouldReturnSuccessOnValidRequest() throws Exception
    {
        RegisterRequest request = new RegisterRequest();
        request.setName("Alice");
        request.setEmail("alice@example.com");
        request.setAffiliation("PixelsDB");
        request.setPassword("secret123");
        request.setCaptcha("ABCD");
        request.setCaptchaKey("key-1");

        doNothing().when(sysLoginService).verifyCaptcha("key-1", "ABCD");
        doNothing().when(userService).register(any(RegisterRequest.class));

        mockMvc.perform(post("/api/v1/auth/register")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(request)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(200))
                .andExpect(jsonPath("$.message").value("Registration successful"));
    }

    @Test
    void registerShouldFailWhenCaptchaIsWrong() throws Exception
    {
        RegisterRequest request = new RegisterRequest();
        request.setName("Alice");
        request.setEmail("alice@example.com");
        request.setAffiliation("PixelsDB");
        request.setPassword("secret123");
        request.setCaptcha("WRONG");
        request.setCaptchaKey("key-1");

        doThrow(new ServiceException("Verification code error"))
                .when(sysLoginService).verifyCaptcha("key-1", "WRONG");

        mockMvc.perform(post("/api/v1/auth/register")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(request)))
                .andExpect(status().is5xxServerError());
    }

    @Test
    void registerShouldReturn400WhenEmailIsInvalid() throws Exception
    {
        RegisterRequest request = new RegisterRequest();
        request.setName("Alice");
        request.setEmail("not-an-email");
        request.setAffiliation("PixelsDB");
        request.setPassword("secret123");

        mockMvc.perform(post("/api/v1/auth/register")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(request)))
                .andExpect(status().isBadRequest());
    }

    // ---------------------------------------------------------------
    // GET /api/v1/auth/captcha
    // ---------------------------------------------------------------

    @Test
    void getCaptchaShouldReturnCaptchaData() throws Exception
    {
        CaptchaResponse captchaResponse = new CaptchaResponse("key-1", "data:image/png;base64,abc");
        when(sysLoginService.generateCaptcha()).thenReturn(captchaResponse);

        mockMvc.perform(get("/api/v1/auth/captcha"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(200))
                .andExpect(jsonPath("$.data.captchaKey").value("key-1"))
                .andExpect(jsonPath("$.data.captchaImage").value("data:image/png;base64,abc"));
    }

    // ---------------------------------------------------------------
    // POST /api/v1/auth/refresh
    // ---------------------------------------------------------------

    @Test
    void refreshShouldWriteNewCookiesFromCookie() throws Exception
    {
        AccessTokenResponse accessTokenResponse =
                new AccessTokenResponse("new-access", "new-refresh", "session-1");
        when(sysLoginService.refreshToken(eq("cookie-refresh-token"), any(), any()))
                .thenReturn(accessTokenResponse);
        when(cookieHelper.resolveRefreshToken(any())).thenReturn("cookie-refresh-token");

        mockMvc.perform(post("/api/v1/auth/refresh")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(200))
                .andExpect(jsonPath("$.message").value("Token refreshed"))
                .andExpect(jsonPath("$.data").doesNotExist());

        verify(cookieHelper).writeTokenCookies(any(), eq("new-access"), eq("new-refresh"));
    }

    @Test
    void refreshShouldIgnoreRequestBodyWhenCookieExists() throws Exception
    {
        AccessTokenResponse accessTokenResponse =
                new AccessTokenResponse("cookie-access", "cookie-refresh", "session-1");
        when(cookieHelper.resolveRefreshToken(any())).thenReturn("cookie-refresh-token");
        when(sysLoginService.refreshToken(eq("cookie-refresh-token"), any(), any()))
                .thenReturn(accessTokenResponse);

        mockMvc.perform(post("/api/v1/auth/refresh")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(Map.of("refreshToken", "stale-body-token"))))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.message").value("Token refreshed"))
                .andExpect(jsonPath("$.data").doesNotExist());

        verify(cookieHelper).writeTokenCookies(any(), eq("cookie-access"), eq("cookie-refresh"));
    }

    @Test
    void refreshShouldReturnErrorWhenNoRefreshToken() throws Exception
    {
        when(cookieHelper.resolveRefreshToken(any())).thenReturn(null);

        mockMvc.perform(post("/api/v1/auth/refresh")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(Map.of("refreshToken", "body-token-is-ignored"))))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(40000))
                .andExpect(jsonPath("$.message").value("Refresh token is required"));
    }

    // ---------------------------------------------------------------
    // GET /api/v1/auth/me
    // ---------------------------------------------------------------

    @Test
    void meShouldReturnUserInfoFromGatewayHeader() throws Exception
    {
        UserInfoResponse userInfo = new UserInfoResponse(1L, "Alice", "alice@example.com", "PixelsDB");
        when(userService.getUserInfoById(1L)).thenReturn(userInfo);

        mockMvc.perform(get("/api/v1/auth/me").header(USER_ID_HEADER, "1"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(200))
                .andExpect(jsonPath("$.data.email").value("alice@example.com"))
                .andExpect(jsonPath("$.data.name").value("Alice"));
    }

    // ---------------------------------------------------------------
    // GET /api/v1/auth/user-info
    // ---------------------------------------------------------------

    @Test
    void getUserInfoShouldReadIdentityFromHeader() throws Exception
    {
        UserInfoResponse userInfo = new UserInfoResponse(1L, "Alice", "alice@example.com", "PixelsDB");
        when(userService.getUserInfoById(1L)).thenReturn(userInfo);

        mockMvc.perform(get("/api/v1/auth/user-info").header(USER_ID_HEADER, "1"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(200))
                .andExpect(jsonPath("$.data.email").value("alice@example.com"));
    }

    // ---------------------------------------------------------------
    // POST /api/v1/auth/logout
    // ---------------------------------------------------------------

    @Test
    void logoutShouldRevokeGatewaySessionAndClearCookies() throws Exception
    {
        doNothing().when(sysLoginService).revokeSessionById(eq(1L), eq("session-1"));

        mockMvc.perform(post("/api/v1/auth/logout")
                        .header(USER_ID_HEADER, "1")
                        .header(SESSION_ID_HEADER, "session-1"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(200))
                .andExpect(jsonPath("$.message").value("Logged out"));

        verify(sysLoginService).revokeSessionById(eq(1L), eq("session-1"));
        verify(cookieHelper).clearTokenCookies(any());
    }

    @Test
    void logoutAllShouldRevokeAllSessionsAndClearCookies() throws Exception
    {
        doNothing().when(sysLoginService).revokeAllSessionsById(1L);

        mockMvc.perform(post("/api/v1/auth/logout-all").header(USER_ID_HEADER, "1"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(200))
                .andExpect(jsonPath("$.message").value("Logged out from all sessions"));

        verify(sysLoginService).revokeAllSessionsById(1L);
        verify(cookieHelper).clearTokenCookies(any());
    }

    @Test
    void revokeCurrentSessionShouldClearCookies() throws Exception
    {
        doNothing().when(sysLoginService).revokeSessionById(eq(1L), eq("session-1"));

        mockMvc.perform(delete("/api/v1/auth/sessions/session-1")
                        .header(USER_ID_HEADER, "1")
                        .header(SESSION_ID_HEADER, "session-1"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.message").value("Current session revoked"));

        verify(cookieHelper).clearTokenCookies(any());
    }
}
