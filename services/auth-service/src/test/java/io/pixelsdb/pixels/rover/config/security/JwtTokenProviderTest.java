package io.pixelsdb.pixels.rover.config.security;

import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.io.Decoders;
import io.jsonwebtoken.security.Keys;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import javax.crypto.SecretKey;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.KeyPair;
import java.security.KeyPairGenerator;
import java.util.Base64;
import java.util.Date;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Note: JJWT 0.12 requires a key resolver to call {@code parseSignedClaims(token)} — the
 * zero-arg {@code Jwts.parser().build()} no longer exposes the header alone. Tests that
 * need just the header read it via {@link JwtTokenProvider#getKeyIdFromToken(String)} /
 * {@link JwtTokenProvider#getAlgorithmFromToken(String)} which internally Base64-decode
 * the first segment.
 */

class JwtTokenProviderTest
{
    private static final String SECRET = "cGl4ZWxzZGItcm92ZXItand0LXNlY3JldC1rZXktMjAyNC1taW5pbXVtLTI1Ni1iaXRz";
    private static final String ISSUER = "pixels-rover-auth-service";

    private JwtTokenProvider jwtTokenProvider;

    @BeforeEach
    void setUp()
    {
        jwtTokenProvider = new JwtTokenProvider(
                SECRET,
                "HS256",
                ISSUER,
                "default-hmac",
                "",
                "",
                "",
                "",
                "",
                3600000L,
                604800000L
        );
    }

    @Test
    void accessTokenShouldContainExpectedClaims()
    {
        String token = jwtTokenProvider.generateAccessToken("alice@example.com", 7L, "session-1");

        assertTrue(jwtTokenProvider.validateToken(token));
        assertEquals("alice@example.com", jwtTokenProvider.getUsernameFromToken(token));
        assertEquals(Long.valueOf(7L), jwtTokenProvider.getUserIdFromToken(token));
        assertEquals("access", jwtTokenProvider.getTokenType(token));
        assertEquals("session-1", jwtTokenProvider.getSessionIdFromToken(token));
        assertEquals("default-hmac", jwtTokenProvider.getKeyIdFromToken(token));
    }

    @Test
    void refreshTokenShouldContainRefreshType()
    {
        String token = jwtTokenProvider.generateRefreshToken("alice@example.com", 7L, "session-1", "refresh-1");

        assertTrue(jwtTokenProvider.validateToken(token));
        assertEquals("refresh", jwtTokenProvider.getTokenType(token));
        assertEquals(Long.valueOf(7L), jwtTokenProvider.getUserIdFromToken(token));
        assertEquals("session-1", jwtTokenProvider.getSessionIdFromToken(token));
        assertEquals("refresh-1", jwtTokenProvider.getTokenIdFromToken(token));
    }

    @Test
    void validateTokenShouldRejectTokenWithUnexpectedIssuer()
    {
        SecretKey secretKey = Keys.hmacShaKeyFor(Decoders.BASE64.decode(SECRET));
        Date now = new Date();
        String token = Jwts.builder()
                .header()
                .add("kid", "default-hmac")
                .and()
                .issuer("unexpected-issuer")
                .subject("alice@example.com")
                .claim("uid", 7L)
                .claim("type", "access")
                .issuedAt(now)
                .expiration(new Date(now.getTime() + 3600000L))
                .signWith(secretKey)
                .compact();

        assertFalse(jwtTokenProvider.validateToken(token));
    }

    @Test
    void rs256TokenShouldContainKidAndExpectedClaims() throws Exception
    {
        KeyPairGenerator keyPairGenerator = KeyPairGenerator.getInstance("RSA");
        keyPairGenerator.initialize(2048);
        KeyPair keyPair = keyPairGenerator.generateKeyPair();

        JwtTokenProvider rsaProvider = new JwtTokenProvider(
                SECRET,
                "RS256",
                ISSUER,
                "rsa-key-1",
                toPem("PRIVATE KEY", keyPair.getPrivate().getEncoded()),
                "",
                toPem("PUBLIC KEY", keyPair.getPublic().getEncoded()),
                "",
                "",
                3600000L,
                604800000L
        );

        String token = rsaProvider.generateAccessToken("alice@example.com", 9L);

        assertTrue(rsaProvider.validateToken(token));
        assertEquals("alice@example.com", rsaProvider.getUsernameFromToken(token));
        assertEquals(Long.valueOf(9L), rsaProvider.getUserIdFromToken(token));
        assertEquals("access", rsaProvider.getTokenType(token));
        assertEquals("RS256", rsaProvider.getAlgorithmFromToken(token));
        assertEquals("rsa-key-1", rsaProvider.getKeyIdFromToken(token));
    }

    /**
     * Verifies the directory-enumeration multi-key loader: {@code jwt.public-keys-directory}
     * replaces the retired {@code public-keys-json} artifact (see
     * {@code docs/design/jwt-rotation.md §1.2}). Every {@code <kid>-public.pem} file under the
     * directory must be picked up so a mid-rotation refresh-token signed by the new kid can
     * still be validated alongside tokens from the previous kid.
     */
    @Test
    void rs256ValidationShouldAcceptKeysDiscoveredFromDirectory(@TempDir Path publicKeysDir) throws Exception
    {
        KeyPairGenerator keyPairGenerator = KeyPairGenerator.getInstance("RSA");
        keyPairGenerator.initialize(2048);
        KeyPair oldKeyPair = keyPairGenerator.generateKeyPair();
        KeyPair newKeyPair = keyPairGenerator.generateKeyPair();

        Files.write(publicKeysDir.resolve("rsa-old-public.pem"),
                toPem("PUBLIC KEY", oldKeyPair.getPublic().getEncoded()).getBytes(StandardCharsets.UTF_8));
        Files.write(publicKeysDir.resolve("rsa-new-public.pem"),
                toPem("PUBLIC KEY", newKeyPair.getPublic().getEncoded()).getBytes(StandardCharsets.UTF_8));

        JwtTokenProvider signingProvider = new JwtTokenProvider(
                SECRET,
                "RS256",
                ISSUER,
                "rsa-new",
                toPem("PRIVATE KEY", newKeyPair.getPrivate().getEncoded()),
                "",
                "",
                "",
                publicKeysDir.toString(),
                3600000L,
                604800000L
        );

        String token = signingProvider.generateRefreshToken("alice@example.com", 9L);

        assertTrue(signingProvider.validateToken(token));
        assertEquals("rsa-new", signingProvider.getKeyIdFromToken(token));
    }

    private static String toPem(String label, byte[] keyBytes)
    {
        return "-----BEGIN " + label + "-----\n"
                + Base64.getMimeEncoder(64, "\n".getBytes()).encodeToString(keyBytes)
                + "\n-----END " + label + "-----";
    }
}
