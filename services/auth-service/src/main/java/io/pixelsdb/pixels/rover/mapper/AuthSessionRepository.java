package io.pixelsdb.pixels.rover.mapper;

import io.pixelsdb.pixels.rover.model.AuthSession;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;
import java.util.Optional;

public interface AuthSessionRepository extends JpaRepository<AuthSession, Long>
{
    Optional<AuthSession> findBySessionId(String sessionId);

    List<AuthSession> findAllByUserIdOrderByLastActivityAtDesc(Long userId);
}
