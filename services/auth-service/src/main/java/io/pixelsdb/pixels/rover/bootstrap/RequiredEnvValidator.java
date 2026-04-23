/*
 * Copyright 2023 PixelsDB.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 */
package io.pixelsdb.pixels.rover.bootstrap;

import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.SignatureAlgorithm;
import org.springframework.boot.context.event.ApplicationEnvironmentPreparedEvent;
import org.springframework.context.ApplicationListener;
import org.springframework.core.env.ConfigurableEnvironment;
import org.yaml.snakeyaml.Yaml;

import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.KeyFactory;
import java.security.PrivateKey;
import java.security.PublicKey;
import java.security.interfaces.RSAPrivateKey;
import java.security.interfaces.RSAPublicKey;
import java.security.spec.PKCS8EncodedKeySpec;
import java.security.spec.X509EncodedKeySpec;
import java.util.ArrayList;
import java.util.Base64;
import java.util.Date;
import java.util.List;
import java.util.Map;

/**
 * §14 hard-validation of required environment variables.
 *
 * <p>Runs as an {@link ApplicationListener} on
 * {@link ApplicationEnvironmentPreparedEvent} so it fires BEFORE any
 * {@code @Component} is instantiated (notably {@code JwtTokenProvider},
 * which would otherwise silently fall back to an empty-secret HS256
 * signer). On any violation we print one FATAL line per failure, then
 * call {@code System.exit(1)}. The container restart policy in
 * docker-compose.yml catches the exit so operators see the failure
 * loudly.</p>
 *
 * <p>Registration path is intentionally narrow — {@code main()} in
 * {@link io.pixelsdb.pixels.rover.PixelsRoverApplication} attaches this
 * listener via {@code SpringApplication.addListeners}. Spring's test
 * infrastructure ({@code @SpringBootTest} / {@code @WebMvcTest})
 * bypasses the production main method, so test contexts are unaffected
 * and can continue to rely on the empty-default placeholders in
 * {@code application.properties}. This is the same split the SSOT
 * config/required-env.yaml header documents.</p>
 *
 * <p>Shape lives entirely in {@code config/required-env.yaml} under
 * {@code services.auth-service}; this class does NOT hardcode any var
 * names, enums, or forbidden placeholders. Cross-reference with
 * {@code scripts/check-contracts.py} which asserts the five consumers
 * of the YAML are always in lockstep.</p>
 *
 * <p>Additional responsibility layered on top of the generic DSL: when
 * {@code JWT_ALGORITHM=RS256}, this validator performs a
 * sign→verify self-test with the configured PEM pair before admitting
 * the boot. A broken keypair (wrong public for the private, corrupted
 * PEM, etc.) is caught here rather than at the first login request.</p>
 */
public class RequiredEnvValidator implements ApplicationListener<ApplicationEnvironmentPreparedEvent>
{
    private static final String SERVICE_NAME = "auth-service";

    /** Default path inside the container where {@code config/required-env.yaml} is bind-mounted. */
    private static final String DEFAULT_YAML_PATH = "/app/config/required-env.yaml";

    @Override
    public void onApplicationEvent(ApplicationEnvironmentPreparedEvent event)
    {
        ConfigurableEnvironment env = event.getEnvironment();
        // Explicit opt-out for tests that do touch main() (none today, but keeps
        // the escape hatch obvious). Production compose must NEVER set this.
        if (Boolean.parseBoolean(env.getProperty("app.required-env.skip", "false")))
        {
            return;
        }
        String yamlPath = env.getProperty("app.required-env.path", DEFAULT_YAML_PATH);

        List<Map<String, Object>> entries;
        try
        {
            entries = loadServiceEntries(yamlPath, SERVICE_NAME);
        }
        catch (IOException | IllegalStateException exc)
        {
            fatal("could not load required-env SSOT at " + yamlPath + ": " + exc.getMessage());
            fatal("check docker-compose.yml bind-mount for /app/config/required-env.yaml");
            System.exit(2);
            return;
        }

        List<String> failures = new ArrayList<>();
        for (Map<String, Object> entry : entries)
        {
            validateEntry(entry, env, failures);
        }

        // RS256-specific supplementary contract: sign→verify self-test.
        // Only runs if the DSL-level validation above passed for the four
        // RS256 fields; otherwise the operator sees a flood of overlapping
        // errors that obscure the root cause.
        if ("RS256".equals(env.getProperty("JWT_ALGORITHM")) && failures.isEmpty())
        {
            try
            {
                rsaSignVerifySelfTest(
                        env.getProperty("JWT_PRIVATE_KEY_PATH"),
                        env.getProperty("JWT_PUBLIC_KEY_PATH"));
            }
            catch (Exception exc)
            {
                failures.add(
                        "RS256 sign→verify self-test failed with "
                                + "JWT_PRIVATE_KEY_PATH / JWT_PUBLIC_KEY_PATH: "
                                + exc.getMessage()
                                + " — public key does not verify tokens signed by "
                                + "the private key. Re-provision the pair "
                                + "(docs/runbooks/jwt-key-provisioning.md).");
            }
        }

        if (!failures.isEmpty())
        {
            for (String f : failures)
            {
                fatal(f);
            }
            fatal(failures.size() + " env var violation(s); refusing to boot. "
                    + "See config/required-env.yaml for the authoritative shape.");
            System.exit(1);
        }
    }

    // ---------------------------------------------------------------

    @SuppressWarnings("unchecked")
    private static List<Map<String, Object>> loadServiceEntries(String yamlPath, String service)
            throws IOException
    {
        Yaml yaml = new Yaml();
        try (InputStream in = Files.newInputStream(Path.of(yamlPath)))
        {
            Map<String, Object> doc = yaml.load(in);
            if (doc == null)
            {
                throw new IllegalStateException("YAML document is empty");
            }
            Map<String, Object> services = (Map<String, Object>) doc.get("services");
            if (services == null)
            {
                throw new IllegalStateException("top-level `services:` key missing");
            }
            Object list = services.get(service);
            if (!(list instanceof List))
            {
                throw new IllegalStateException("services." + service + " is missing or not a list");
            }
            return (List<Map<String, Object>>) list;
        }
    }

    @SuppressWarnings("unchecked")
    private static void validateEntry(Map<String, Object> entry,
                                      ConfigurableEnvironment env,
                                      List<String> failures)
    {
        String name = (String) entry.get("name");
        String value = env.getProperty(name, "");

        boolean required = Boolean.TRUE.equals(entry.get("required"));
        String requiredWhen = (String) entry.get("required_when");
        String forbiddenWhen = (String) entry.get("forbidden_when");

        Boolean otherMatches = null;
        String clause = requiredWhen != null ? requiredWhen : forbiddenWhen;
        if (clause != null)
        {
            int eq = clause.indexOf('=');
            if (eq < 0)
            {
                failures.add(name + ": malformed required_when/forbidden_when clause `"
                        + clause + "` — expected OTHER=value");
                return;
            }
            String otherName = clause.substring(0, eq);
            String expected = clause.substring(eq + 1);
            String otherValue = env.getProperty(otherName, "");
            otherMatches = otherValue.equals(expected);
        }

        boolean isRequired = required
                || (requiredWhen != null && Boolean.TRUE.equals(otherMatches));
        boolean isForbidden = forbiddenWhen != null && Boolean.TRUE.equals(otherMatches);

        if (isForbidden && !value.isEmpty())
        {
            failures.add(name + " MUST be unset because " + forbiddenWhen
                    + " (mutually exclusive group); got value of length "
                    + value.length() + ".");
            return;
        }

        if (value.isEmpty())
        {
            if (isRequired)
            {
                String why = required ? "unconditional" : "because " + requiredWhen;
                failures.add(name + " is required (" + why + ") but is empty or unset. "
                        + "See config/required-env.yaml for description.");
            }
            return;
        }

        List<String> enumValues = (List<String>) entry.get("enum");
        if (enumValues != null && !enumValues.contains(value))
        {
            failures.add(name + "=`" + value + "` is not in allowed enum " + enumValues
                    + " (strict string match).");
        }

        List<String> forbiddenValues = (List<String>) entry.get("forbidden_values");
        if (forbiddenValues != null)
        {
            for (String bad : forbiddenValues)
            {
                if (value.equals(bad))
                {
                    failures.add(name + "=`" + value + "` matches forbidden placeholder `"
                            + bad + "`; refusing to boot.");
                }
            }
        }

        Object minBytesObj = entry.get("min_utf8_bytes");
        if (minBytesObj instanceof Integer)
        {
            int min = (Integer) minBytesObj;
            int actual = value.getBytes(StandardCharsets.UTF_8).length;
            if (actual < min)
            {
                failures.add(name + " is " + actual + " UTF-8 bytes, below minimum "
                        + min + ".");
            }
        }

        if (Boolean.TRUE.equals(entry.get("file_must_exist")))
        {
            Path p = Path.of(value);
            if (!Files.isRegularFile(p))
            {
                failures.add(name + "=`" + value + "` is not a regular file "
                        + "(validator runs AFTER bind-mount; check compose volume "
                        + "and host-side provisioning — "
                        + "docs/runbooks/jwt-key-provisioning.md).");
            }
            else if (!Files.isReadable(p))
            {
                failures.add(name + "=`" + value + "` is not readable by the JVM process.");
            }
        }
    }

    // ---------------------------------------------------------------
    // RS256 keypair self-test
    // ---------------------------------------------------------------

    private static void rsaSignVerifySelfTest(String privatePath, String publicPath) throws Exception
    {
        PrivateKey priv = parsePkcs8Private(privatePath);
        PublicKey pub = parseX509Public(publicPath);
        if (!(priv instanceof RSAPrivateKey) || !(pub instanceof RSAPublicKey))
        {
            throw new IllegalStateException(
                    "configured keys are not RSA (private=" + priv.getAlgorithm()
                            + ", public=" + pub.getAlgorithm() + ")");
        }
        // Round-trip a synthetic token. If the pair is mismatched, parseSignedClaims
        // below throws with a signature-exception — caller catches and reports.
        Date now = new Date();
        Date exp = new Date(now.getTime() + 60_000L);
        String token = Jwts.builder()
                .setSubject("required-env-validator-self-test")
                .setIssuedAt(now)
                .setExpiration(exp)
                .signWith(priv, SignatureAlgorithm.RS256)
                .compact();
        Jwts.parserBuilder()
                .setSigningKey(pub)
                .build()
                .parseClaimsJws(token);
    }

    private static PrivateKey parsePkcs8Private(String path) throws Exception
    {
        byte[] der = decodePem(path, "PRIVATE KEY");
        return KeyFactory.getInstance("RSA").generatePrivate(new PKCS8EncodedKeySpec(der));
    }

    private static PublicKey parseX509Public(String path) throws Exception
    {
        byte[] der = decodePem(path, "PUBLIC KEY");
        return KeyFactory.getInstance("RSA").generatePublic(new X509EncodedKeySpec(der));
    }

    private static byte[] decodePem(String path, String label) throws IOException
    {
        String pem = Files.readString(Path.of(path), StandardCharsets.UTF_8);
        String begin = "-----BEGIN " + label + "-----";
        String end = "-----END " + label + "-----";
        int b = pem.indexOf(begin);
        int e = pem.indexOf(end);
        if (b < 0 || e < 0 || e <= b)
        {
            throw new IOException(path + " is not a valid " + label + " PEM");
        }
        String body = pem.substring(b + begin.length(), e).replaceAll("\\s+", "");
        return Base64.getDecoder().decode(body);
    }

    private static void fatal(String msg)
    {
        System.err.println("FATAL auth-service/required-env: " + msg);
    }
}
