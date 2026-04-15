package io.pixelsdb.pixels.rover.rest.response;

import java.sql.Timestamp;

public class UserSessionResponse
{
    private String sessionId;
    private boolean current;
    private String userAgent;
    private String clientIp;
    private Timestamp createTime;
    private Timestamp lastActivityAt;
    private Timestamp refreshTokenExpiresAt;
    private Timestamp revokedAt;
    private String revokedReason;

    public String getSessionId()
    {
        return sessionId;
    }

    public void setSessionId(String sessionId)
    {
        this.sessionId = sessionId;
    }

    public boolean isCurrent()
    {
        return current;
    }

    public void setCurrent(boolean current)
    {
        this.current = current;
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

    public Timestamp getCreateTime()
    {
        return createTime;
    }

    public void setCreateTime(Timestamp createTime)
    {
        this.createTime = createTime;
    }

    public Timestamp getLastActivityAt()
    {
        return lastActivityAt;
    }

    public void setLastActivityAt(Timestamp lastActivityAt)
    {
        this.lastActivityAt = lastActivityAt;
    }

    public Timestamp getRefreshTokenExpiresAt()
    {
        return refreshTokenExpiresAt;
    }

    public void setRefreshTokenExpiresAt(Timestamp refreshTokenExpiresAt)
    {
        this.refreshTokenExpiresAt = refreshTokenExpiresAt;
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
}
