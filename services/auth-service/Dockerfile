# ---- Build stage ----
FROM maven:3.9-eclipse-temurin-17 AS builder

WORKDIR /build

# Copy POM first for dependency caching
COPY pom.xml .

# Attempt to resolve dependencies (may partially fail due to parent POM,
# but still caches most downloads).
RUN mvn dependency:go-offline -B || true

# Copy source
COPY src ./src

# Build the application (skip tests for faster image builds)
RUN mvn package -DskipTests -B

# ---- Runtime stage ----
FROM eclipse-temurin:17-jre

WORKDIR /app

COPY --from=builder /build/target/*.jar app.jar

# Default Spring Boot port
EXPOSE 8081

# Health check against the /health endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8081/health || exit 1

ENTRYPOINT ["java", "-jar", "app.jar"]
