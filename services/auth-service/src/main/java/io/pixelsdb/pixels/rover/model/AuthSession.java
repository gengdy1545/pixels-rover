package io.pixelsdb.pixels.rover.model;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.PrePersist;
import jakarta.persistence.PreUpdate;
import jakarta.persistence.Table;

import java.sql.Timestamp;

@Entity
@Table(name = "auth_session")
public class AuthSession
{
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(nullable = false, unique = true, length = 36)
    private String sessionId;

    @Column(nullable = false)
    private Long userId;

    @Column(nullable = false, length = 128)
    private String userEmail;

    @Column(nullable = false, length = 64)
    private String refreshTokenHash;

    @Column(nullable = false, length = 36)
    private String currentRefreshTokenId;

    @Column(nullable = false)
    private Timestamp refreshTokenExpiresAt;

    @Column(nullable = false)
    private Timestamp lastActivityAt;

    @Column(length = 255)
    private String userAgent;

    @Column(length = 64)
    private String clientIp;

    private Timestamp revokedAt;

    @Column(length = 128)
    private String revokedReason;

    @Column(nullable = false, updatable = false)
    private Timestamp createTime;

    @Column(nullable = false)
    private Timestamp updateTime;

    @PrePersist
    public void onCreate()
    {
        Timestamp now = new Timestamp(System.currentTimeMillis());
        if (createTime == null)
        {
            createTime = now;
        }
        updateTime = now;
        if (lastActivityAt == null)
        {
            lastActivityAt = now;
        }
    }

    @PreUpdate
    public void onUpdate()
    {
        updateTime = new Timestamp(System.currentTimeMillis());
    }

    public Long getId()
    {
        return id;
    }

    public void setId(Long id)
    {
        this.id = id;
    }

    public String getSessionId()
    {
        return sessionId;
    }

    public void setSessionId(String sessionId)
    {
        this.sessionId = sessionId;
    }

    public Long getUserId()
    {
        return userId;
    }

    public void setUserId(Long userId)
    {
        this.userId = userId;
    }

    public String getUserEmail()
    {
        return userEmail;
    }

    public void setUserEmail(String userEmail)
    {
        this.userEmail = userEmail;
    }

    public String getRefreshTokenHash()
    {
        return refreshTokenHash;
    }

    public void setRefreshTokenHash(String refreshTokenHash)
    {
        this.refreshTokenHash = refreshTokenHash;
    }

    public String getCurrentRefreshTokenId()
    {
        return currentRefreshTokenId;
    }

    public void setCurrentRefreshTokenId(String currentRefreshTokenId)
    {
        this.currentRefreshTokenId = currentRefreshTokenId;
    }

    public Timestamp getRefreshTokenExpiresAt()
    {
        return refreshTokenExpiresAt;
    }

    public void setRefreshTokenExpiresAt(Timestamp refreshTokenExpiresAt)
    {
        this.refreshTokenExpiresAt = refreshTokenExpiresAt;
    }

    public Timestamp getLastActivityAt()
    {
        return lastActivityAt;
    }

    public void setLastActivityAt(Timestamp lastActivityAt)
    {
        this.lastActivityAt = lastActivityAt;
    }

    public String getUserAgent()
    {
        return userAgent;
    }

    public void setUserAgent(String userAgent)
    {
        this.userAgent = userAgent;
    }

    public String getClientIp()
    {
        return clientIp;
    }

    public void setClientIp(String clientIp)
    {
        this.clientIp = clientIp;
    }

    public Timestamp getRevokedAt()
    {
        return revokedAt;
    }

    public void setRevokedAt(Timestamp revokedAt)
    {
        this.revokedAt = revokedAt;
    }

    public String getRevokedReason()
    {
        return revokedReason;
    }

    public void setRevokedReason(String revokedReason)
    {
        this.revokedReason = revokedReason;
    }

    public Timestamp getCreateTime()
    {
        return createTime;
    }

    public void setCreateTime(Timestamp createTime)
    {
        this.createTime = createTime;
    }

    public Timestamp getUpdateTime()
    {
        return updateTime;
    }

    public void setUpdateTime(Timestamp updateTime)
    {
        this.updateTime = updateTime;
    }
}
