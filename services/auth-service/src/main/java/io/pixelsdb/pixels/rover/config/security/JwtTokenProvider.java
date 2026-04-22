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

import com.fasterxml.jackson.databind.ObjectMapper;
import io.jsonwebtoken.Claims;
import io.jsonwebtoken.ExpiredJwtException;
import io.jsonwebtoken.IncorrectClaimException;
import io.jsonwebtoken.JwtBuilder;
import io.jsonwebtoken.JwtParserBuilder;
import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.MalformedJwtException;
import io.jsonwebtoken.MissingClaimException;
import io.jsonwebtoken.UnsupportedJwtException;
import io.jsonwebtoken.io.Decoders;
import io.jsonwebtoken.security.Keys;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.security.core.Authentication;
import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;

import javax.crypto.SecretKey;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.DirectoryStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.security.KeyFactory;
import java.security.PrivateKey;
import java.security.PublicKey;
import java.security.interfaces.RSAPrivateKey;
import java.security.spec.PKCS8EncodedKeySpec;
import java.security.spec.X509EncodedKeySpec;
import java.util.Base64;
import java.util.Collections;
import java.util.Date;
import java.util.HashMap;
import java.util.Map;

/**
 * JWT token provider for generating, parsing, and validating JWT tokens.
 *
 * Supports phased migration from HS256 to RS256 with kid-based key lookup.
 */
@Component
public class JwtTokenProvider
{
    private static final Logger log = LoggerFactory.getLogger(JwtTokenProvider.class);
    private static final String TOKEN_TYPE_CLAIM = "type";
    private static final String USER_ID_CLAIM = "uid";
    private static final String SESSION_ID_CLAIM = "sid";
    private static final String TOKEN_ID_CLAIM = "jti";
    private static final String KEY_ID_HEADER = "kid";
    private static final String ACCESS_TOKEN_TYPE = "access";
    private static final String REFRESH_TOKEN_TYPE = "refresh";
    private static final String HS256 = "HS256";
    private static final String RS256 = "RS256";
    private static final ObjectMapper OBJECT_MAPPER = new ObjectMapper();

    private final SecretKey secretKey;
    private final PrivateKey privateKey;
    private final Map<String, PublicKey> publicKeys;
    private final String algorithm;
    private final String issuer;
    private final String activeKid;
    private final long accessTokenExpirationMs;
    private final long refreshTokenExpirationMs;

    public JwtTokenProvider(
            @Value("${jwt.secret:cGl4ZWxzZGItcm92ZXItand0LXNlY3JldC1rZXktMjAyNC1taW5pbXVtLTI1Ni1iaXRz}") String secret,
            @Value("${jwt.algorithm:HS256}") String algorithm,
            @Value("${jwt.issuer:pixels-rover-auth-service}") String issuer,
            @Value("${jwt.active-kid:default-hmac}") String activeKid,
            @Value("${jwt.private-key-pem:}") String privateKeyPem,
            @Value("${jwt.private-key-path:}") String privateKeyPath,
            @Value("${jwt.public-key-pem:}") String publicKeyPem,
            @Value("${jwt.public-key-path:}") String publicKeyPath,
            @Value("${jwt.public-keys-directory:}") String publicKeysDirectory,
            @Value("${jwt.access-token-expiration-ms:3600000}") long accessTokenExpirationMs,
            @Value("${jwt.refresh-token-expiration-ms:604800000}") long refreshTokenExpirationMs)
    {
        this.secretKey = StringUtils.hasText(secret)
                ? Keys.hmacShaKeyFor(Decoders.BASE64.decode(secret))
                : null;
        this.algorithm = StringUtils.hasText(algorithm) ? algorithm : HS256;
        this.issuer = issuer;
        this.activeKid = StringUtils.hasText(activeKid) ? activeKid : "default-hmac";
        String resolvedPrivateKeyPem = readConfigValue(privateKeyPem, privateKeyPath);
        String resolvedPublicKeyPem = readConfigValue(publicKeyPem, publicKeyPath);
        this.privateKey = parsePrivateKey(resolvedPrivateKeyPem);
        // Multi-key support now comes from enumerating `<kid>-public.pem` files under the
        // auth-service-local directory (see docs/design/jwt-rotation.md §1.2 and the stage-C
        // of docs/runbooks/jwt-rotation-drill.md). The legacy "merged JSON of public keys"
        // artifact was consumed by the former /api/v1/auth/jwks endpoint, which has been
        // retired; keeping any fallback here would re-invite external-distribution thinking.
        this.publicKeys = Collections.unmodifiableMap(
                loadPublicKeys(resolvedPublicKeyPem, publicKeysDirectory, this.activeKid));
        this.accessTokenExpirationMs = accessTokenExpirationMs;
        this.refreshTokenExpirationMs = refreshTokenExpirationMs;
    }

    public String generateAccessToken(Authentication authentication)
    {
        return generateToken(authentication.getName(), extractUserId(authentication), accessTokenExpirationMs, ACCESS_TOKEN_TYPE);
    }

    public String generateAccessToken(String username, Long userId)
    {
        return generateToken(username, userId, accessTokenExpirationMs, ACCESS_TOKEN_TYPE);
    }

    public String generateAccessToken(String username, Long userId, String sessionId)
    {
        return generateToken(username, userId, accessTokenExpirationMs, ACCESS_TOKEN_TYPE, sessionId, null);
    }

    public String generateRefreshToken(Authentication authentication)
    {
        return generateToken(authentication.getName(), extractUserId(authentication), refreshTokenExpirationMs, REFRESH_TOKEN_TYPE);
    }

    public String generateRefreshToken(String username, Long userId)
    {
        return generateToken(username, userId, refreshTokenExpirationMs, REFRESH_TOKEN_TYPE);
    }

    public String generateRefreshToken(String username, Long userId, String sessionId, String tokenId)
    {
        return generateToken(username, userId, refreshTokenExpirationMs, REFRESH_TOKEN_TYPE, sessionId, tokenId);
    }

    private String generateToken(String subject, Long userId, long expirationMs, String tokenType)
    {
        return generateToken(subject, userId, expirationMs, tokenType, null, null);
    }

    private String generateToken(String subject, Long userId, long expirationMs, String tokenType,
                                 String sessionId, String tokenId)
    {
        Date now = new Date();
        Date expiryDate = new Date(now.getTime() + expirationMs);

        JwtBuilder builder = Jwts.builder()
                .header()
                .add(KEY_ID_HEADER, activeKid)
                .and()
                .issuer(issuer)
                .subject(subject)
                .claim(TOKEN_TYPE_CLAIM, tokenType)
                .issuedAt(now)
                .expiration(expiryDate);

        if (userId != null)
        {
            builder.claim(USER_ID_CLAIM, userId);
        }
        if (StringUtils.hasText(sessionId))
        {
            builder.claim(SESSION_ID_CLAIM, sessionId);
        }
        if (StringUtils.hasText(tokenId))
        {
            builder.id(tokenId);
        }

        return sign(builder).compact();
    }

    public String getUsernameFromToken(String token)
    {
        return parseClaims(token).getSubject();
    }

    public String getTokenType(String token)
    {
        return parseClaims(token).get(TOKEN_TYPE_CLAIM, String.class);
    }

    public Long getUserIdFromToken(String token)
    {
        Number userId = parseClaims(token).get(USER_ID_CLAIM, Number.class);
        return userId == null ? null : userId.longValue();
    }

    public String getSessionIdFromToken(String token)
    {
        return parseClaims(token).get(SESSION_ID_CLAIM, String.class);
    }

    public String getTokenIdFromToken(String token)
    {
        return parseClaims(token).getId();
    }

    public Date getExpirationFromToken(String token)
    {
        return parseClaims(token).getExpiration();
    }

    public Date getIssuedAtFromToken(String token)
    {
        return parseClaims(token).getIssuedAt();
    }

    public boolean validateToken(String token)
    {
        try
        {
            parseClaims(token);
            return true;
        }
        catch (SecurityException | MalformedJwtException e)
        {
            log.error("Invalid JWT signature: {}", e.getMessage());
        }
        catch (ExpiredJwtException e)
        {
            log.error("JWT token is expired: {}", e.getMessage());
        }
        catch (UnsupportedJwtException e)
        {
            log.error("JWT token is unsupported: {}", e.getMessage());
        }
        catch (IncorrectClaimException | MissingClaimException e)
        {
            // Issuer / required-claim mismatch: the signature may be valid, but the token
            // was not issued by us, so treat it as invalid per backend.md §3.1.
            log.error("JWT claim validation failed: {}", e.getMessage());
        }
        catch (IllegalArgumentException e)
        {
            log.error("JWT claims string is empty: {}", e.getMessage());
        }
        return false;
    }

    public String getAlgorithm()
    {
        return algorithm;
    }

    public String getActiveKid()
    {
        return activeKid;
    }

    /**
     * Returns the {@code kid} header value of the supplied JWT (without performing any
     * signature verification). Intended for diagnostics and testing — production auth
     * decisions must go through {@link #validateToken(String)}.
     */
    public String getKeyIdFromToken(String token)
    {
        return parseTokenHeader(token).getKid();
    }

    /**
     * Returns the {@code alg} header value of the supplied JWT (without verification).
     * See caveats on {@link #getKeyIdFromToken(String)}.
     */
    public String getAlgorithmFromToken(String token)
    {
        return parseTokenHeader(token).getAlg();
    }

    private Claims parseClaims(String token)
    {
        TokenHeader tokenHeader = parseTokenHeader(token);
        JwtParserBuilder parserBuilder = Jwts.parser().requireIssuer(issuer);

        if (RS256.equalsIgnoreCase(tokenHeader.getAlg()))
        {
            PublicKey publicKey = publicKeys.get(tokenHeader.getKid());
            if (publicKey == null)
            {
                throw new MalformedJwtException("Unknown key id: " + tokenHeader.getKid());
            }
            parserBuilder.verifyWith(publicKey);
        }
        else
        {
            if (secretKey == null)
            {
                throw new MalformedJwtException("No HS256 verification key configured");
            }
            parserBuilder.verifyWith(secretKey);
        }

        return parserBuilder.build().parseSignedClaims(token).getPayload();
    }

    private JwtBuilder sign(JwtBuilder builder)
    {
        if (RS256.equalsIgnoreCase(algorithm))
        {
            if (!(privateKey instanceof RSAPrivateKey))
            {
                throw new IllegalStateException("RS256 signing requires jwt.private-key-pem");
            }
            return builder.signWith(privateKey, Jwts.SIG.RS256);
        }

        if (secretKey == null)
        {
            throw new IllegalStateException("HS256 signing requires jwt.secret");
        }
        return builder.signWith(secretKey);
    }

    private static PrivateKey parsePrivateKey(String privateKeyPem)
    {
        if (!StringUtils.hasText(privateKeyPem))
        {
            return null;
        }
        try
        {
            byte[] keyBytes = Base64.getDecoder().decode(stripPem(privateKeyPem));
            return KeyFactory.getInstance("RSA").generatePrivate(new PKCS8EncodedKeySpec(keyBytes));
        }
        catch (Exception e)
        {
            throw new IllegalArgumentException("Failed to parse jwt.private-key-pem", e);
        }
    }

    private static PublicKey parsePublicKey(String publicKeyPem)
    {
        if (!StringUtils.hasText(publicKeyPem))
        {
            return null;
        }
        try
        {
            byte[] keyBytes = Base64.getDecoder().decode(stripPem(publicKeyPem));
            return KeyFactory.getInstance("RSA").generatePublic(new X509EncodedKeySpec(keyBytes));
        }
        catch (Exception e)
        {
            throw new IllegalArgumentException("Failed to parse JWT public key", e);
        }
    }

    /**
     * Load verification public keys from the auth-service-local directory and, optionally,
     * the single active key PEM.
     *
     * <p>Directory enumeration rule: every file matching {@code <kid>-public.pem} contributes
     * a verifier keyed by {@code <kid>}. This is deliberately an internal trust contract —
     * see {@code docs/design/jwt-rotation.md §1.2}: JWKS distribution was retired and the
     * auth-service validates tokens against the keys co-located with it (the same ones the
     * jwt-keygen init container produces during rotation drills).</p>
     *
     * <p>The explicit {@code jwt.public-key-pem} / {@code jwt.public-key-path} inputs still
     * win — they guarantee the active kid is always loadable even if the directory layout
     * drifts.</p>
     */
    private static Map<String, PublicKey> loadPublicKeys(String activePublicKeyPem,
                                                         String publicKeysDirectory,
                                                         String activeKid)
    {
        Map<String, PublicKey> result = new HashMap<>();
        if (StringUtils.hasText(publicKeysDirectory))
        {
            Path directory = Paths.get(publicKeysDirectory);
            if (Files.isDirectory(directory))
            {
                try (DirectoryStream<Path> stream = Files.newDirectoryStream(directory, "*-public.pem"))
                {
                    for (Path pemFile : stream)
                    {
                        String fileName = pemFile.getFileName().toString();
                        String kid = fileName.substring(0, fileName.length() - "-public.pem".length());
                        try
                        {
                            String pem = new String(Files.readAllBytes(pemFile), StandardCharsets.UTF_8);
                            PublicKey key = parsePublicKey(pem);
                            if (key != null)
                            {
                                result.put(kid, key);
                            }
                        }
                        catch (IOException | IllegalArgumentException e)
                        {
                            log.warn("Skipping unreadable JWT public key {}: {}", pemFile, e.getMessage());
                        }
                    }
                }
                catch (IOException e)
                {
                    throw new IllegalArgumentException(
                            "Failed to enumerate jwt.public-keys-directory: " + publicKeysDirectory, e);
                }
            }
            else
            {
                log.warn("jwt.public-keys-directory does not exist or is not a directory: {}",
                        publicKeysDirectory);
            }
        }
        if (StringUtils.hasText(activePublicKeyPem))
        {
            PublicKey key = parsePublicKey(activePublicKeyPem);
            if (key != null)
            {
                result.put(activeKid, key);
            }
        }
        return result;
    }

    private static String stripPem(String pem)
    {
        return pem
                .replace("-----BEGIN PRIVATE KEY-----", "")
                .replace("-----END PRIVATE KEY-----", "")
                .replace("-----BEGIN PUBLIC KEY-----", "")
                .replace("-----END PUBLIC KEY-----", "")
                .replaceAll("\\s+", "");
    }

    private static TokenHeader parseTokenHeader(String token)
    {
        try
        {
            String[] parts = token.split("\\.");
            if (parts.length < 2)
            {
                throw new MalformedJwtException("Malformed JWT token");
            }
            String json = new String(Base64.getUrlDecoder().decode(parts[0]));
            return OBJECT_MAPPER.readValue(json, TokenHeader.class);
        }
        catch (MalformedJwtException e)
        {
            throw e;
        }
        catch (Exception e)
        {
            throw new MalformedJwtException("Failed to parse JWT header", e);
        }
    }

    private Long extractUserId(Authentication authentication)
    {
        Object principal = authentication.getPrincipal();
        if (principal instanceof PixelsUserDetails)
        {
            PixelsUserDetails userDetails = (PixelsUserDetails) principal;
            return userDetails.getId();
        }
        return null;
    }

    private static String readConfigValue(String inlineValue, String pathValue)
    {
        if (StringUtils.hasText(inlineValue))
        {
            return inlineValue;
        }
        if (!StringUtils.hasText(pathValue))
        {
            return "";
        }
        try
        {
            return new String(Files.readAllBytes(Path.of(pathValue)), StandardCharsets.UTF_8);
        }
        catch (IOException e)
        {
            throw new IllegalArgumentException("Failed to read JWT config file: " + pathValue, e);
        }
    }

    public static class TokenHeader
    {
        private String alg;
        private String kid;

        public String getAlg()
        {
            return alg;
        }

        public void setAlg(String alg)
        {
            this.alg = alg;
        }

        public String getKid()
        {
            return kid;
        }

        public void setKid(String kid)
        {
            this.kid = kid;
        }
    }
}
