/*
 * Copyright 2024 PixelsDB.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */
package io.pixelsdb.pixels.rover.config.security;

import io.pixelsdb.pixels.rover.mapper.UserRepository;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.annotation.Order;
import org.springframework.security.authentication.AuthenticationManager;
import org.springframework.security.authentication.AuthenticationProvider;
import org.springframework.security.authentication.dao.DaoAuthenticationProvider;
import org.springframework.security.config.annotation.authentication.configuration.AuthenticationConfiguration;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configuration.EnableWebSecurity;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.core.userdetails.UserDetailsService;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.authentication.UsernamePasswordAuthenticationFilter;
import org.springframework.security.web.util.matcher.AntPathRequestMatcher;

/**
 * Security configuration split along auth-service's two-faceted identity ({@code backend.md §3.4}):
 *
 * <ul>
 *     <li>{@code internalApiChain} — guards {@code /api/internal/**} with the shared-secret
 *         {@link InternalAuthFilter}. JWT decoding lives only here and in service-layer domain
 *         logic (refresh / logout), never on the user-facing chain.</li>
 *     <li>{@code publicAndUserChain} — handles public entry points
 *         ({@code /api/v1/auth/login} / {@code /register} / {@code /captcha} / {@code /refresh})
 *         and user-facing endpoints ({@code /me} / {@code /logout} / {@code /sessions*}).
 *         User-facing endpoints consume identity exclusively from gateway-injected
 *         {@code X-Auth-User-Id} / {@code X-Auth-Session-Id} headers via
 *         {@link IdentityHeaderValidationFilter}; no filter on this chain decodes JWTs.</li>
 * </ul>
 *
 * <p>CORS and global 401/403 entry points are intentionally not configured here: per
 * {@code backend.md §11} / {@code gateway.md §6.4} both are gateway's responsibility.</p>
 */
@Configuration
@EnableWebSecurity
public class SecurityConfig
{
    private final String internalIntrospectionSecret;

    public SecurityConfig(@Value("${internal.introspection.secret:}") String internalIntrospectionSecret)
    {
        this.internalIntrospectionSecret = internalIntrospectionSecret;
    }

    /**
     * Chain 1 of 2: every {@code /api/internal/**} route is gated by {@link InternalAuthFilter}.
     *
     * <p>HttpSecurity authorization is left as {@code permitAll()} because the filter itself
     * performs the secret check and short-circuits with {@code 500 + INTERNAL_AUTH_FAILED}; adding
     * another {@code authenticated()} layer would only translate shared-secret failures into
     * misleading 401/403 responses.</p>
     */
    @Bean
    @Order(1)
    public SecurityFilterChain internalApiChain(HttpSecurity http) throws Exception
    {
        http
                .securityMatcher(new AntPathRequestMatcher("/api/internal/**"))
                .csrf(csrf -> csrf.disable())
                .sessionManagement(session ->
                        session.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
                .authorizeHttpRequests(auth -> auth.anyRequest().permitAll())
                .formLogin(form -> form.disable())
                .httpBasic(basic -> basic.disable())
                .logout(logout -> logout.disable())
                .addFilterBefore(new InternalAuthFilter(internalIntrospectionSecret),
                        UsernamePasswordAuthenticationFilter.class);

        return http.build();
    }

    /**
     * Chain 2 of 2: public entry points plus user-facing endpoints.
     *
     * <p>Authorization rules:</p>
     * <ul>
     *     <li>{@code permitAll} — {@code /health} + the four public entry points only. Anything
     *         else (notably {@code /me} / {@code /logout*} / {@code /sessions*}) falls through to
     *         {@code authenticated()} and is protected by {@link IdentityHeaderValidationFilter},
     *         which rejects missing/malformed {@code X-Auth-User-Id} with
     *         {@code 500 + GATEWAY_IDENTITY_MISSING} (see {@code backend.md §3.3}).</li>
     * </ul>
     *
     * <p>No JWT filter is mounted on this chain — identity on the user face is read
     * exclusively via {@code @RequestHeader("X-Auth-User-Id")}.</p>
     */
    @Bean
    @Order(2)
    public SecurityFilterChain publicAndUserChain(HttpSecurity http) throws Exception
    {
        http
                .csrf(csrf -> csrf.disable())
                .sessionManagement(session ->
                        session.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
                .authorizeHttpRequests(auth -> auth
                        .requestMatchers(
                                "/health",
                                // /internal/ready is consumed only by the gateway via an
                                // nginx `internal;` location (gateway.md §4.1 / backend.md §7.2).
                                // It carries no X-Auth-* headers because gateway-auth does not run
                                // on internal locations; therefore it MUST bypass
                                // IdentityHeaderValidationFilter rather than 500-ing on missing
                                // identity. External exposure is prevented at the gateway layer,
                                // not here.
                                "/internal/ready",
                                // /metrics exposes Prometheus text-format metrics (default
                                // JVM / process / GC collectors only, per
                                // docs/runbooks/observability-roadmap.md §2.1). The endpoint
                                // is not exposed through apisix.yaml.template, so external
                                // access is blocked at the gateway; Spring-level permitAll
                                // here only enables the in-cluster scrape / smoke-check path.
                                "/metrics",
                                // /openapi.json is the springdoc-served OpenAPI document
                                // (application.properties `springdoc.api-docs.path=/openapi.json`).
                                // External exposure is controlled EXCLUSIVELY at the gateway
                                // (gateway.md §6.7: `/api/v1/auth/openapi.json` route switches
                                // between public / protected fragment profiles based on
                                // GATEWAY_OPENAPI_PUBLIC). From auth-service's perspective the
                                // endpoint must be reachable without X-Auth-* headers so that
                                // BOTH profiles reach the handler — the protected profile's
                                // gateway-auth does not guarantee identity injection for
                                // non-Introspection-required routes either, and making this
                                // endpoint authenticated() here would break the public profile
                                // with a 401 at the Spring layer regardless of the gateway's
                                // intent. Access control is deliberately single-layered here.
                                "/openapi.json",
                                "/api/v1/auth/login",
                                "/api/v1/auth/register",
                                "/api/v1/auth/captcha",
                                "/api/v1/auth/refresh"
                        ).permitAll()
                        // User-facing endpoints (/me, /logout*, /sessions*) must be marked
                        // authenticated so the IdentityHeaderValidationFilter's 500 response is
                        // reached before Spring Security would otherwise short-circuit.
                        .anyRequest().authenticated()
                )
                .formLogin(form -> form.disable())
                .httpBasic(basic -> basic.disable())
                .logout(logout -> logout.disable())
                // Allow requests carrying a valid X-Auth-User-Id to satisfy authenticated()
                // without running any AuthN/AuthZ logic locally; identity trust flows from
                // gateway's introspect cache (see backend.md §3.4). The same filter rejects
                // missing/malformed headers with 500 + GATEWAY_IDENTITY_MISSING.
                .addFilterBefore(new IdentityHeaderValidationFilter(),
                        UsernamePasswordAuthenticationFilter.class);

        return http.build();
    }

    @Bean
    public PasswordEncoder passwordEncoder()
    {
        return new BCryptPasswordEncoder();
    }

    @Bean
    public AuthenticationManager authenticationManager(AuthenticationConfiguration authConfig)
            throws Exception
    {
        return authConfig.getAuthenticationManager();
    }

    @Bean
    public UserDetailsService userDetailsService(UserRepository userRepository)
    {
        return new PixelsUserDetailsService(userRepository);
    }

    @Bean
    public AuthenticationProvider authenticationProvider(UserRepository userRepository)
    {
        DaoAuthenticationProvider daoAuthenticationProvider = new DaoAuthenticationProvider();
        daoAuthenticationProvider.setUserDetailsService(userDetailsService(userRepository));
        daoAuthenticationProvider.setPasswordEncoder(passwordEncoder());
        return daoAuthenticationProvider;
    }
}
