package io.pixelsdb.pixels.rover.rest.response;

public class AuthIntrospectionResponse
{
    private boolean active;
    private String sub;
    private Long userId;
    private String email;
    private String sessionId;
    private Long iat;
    private Long exp;
    private String reason;

    public static AuthIntrospectionResponse inactive(String reason)
    {
        AuthIntrospectionResponse response = new AuthIntrospectionResponse();
        response.setActive(false);
        response.setReason(reason);
        return response;
    }

    public boolean isActive()
    {
        return active;
    }

    public void setActive(boolean active)
    {
        this.active = active;
    }

    public String getSub()
    {
        return sub;
    }

    public void setSub(String sub)
    {
        this.sub = sub;
    }

    public Long getUserId()
    {
        return userId;
    }

    public void setUserId(Long userId)
    {
        this.userId = userId;
    }

    public String getEmail()
    {
        return email;
    }

    public void setEmail(String email)
    {
        this.email = email;
    }

    public String getSessionId()
    {
        return sessionId;
    }

    public void setSessionId(String sessionId)
    {
        this.sessionId = sessionId;
    }

    public Long getIat()
    {
        return iat;
    }

    public void setIat(Long iat)
    {
        this.iat = iat;
    }

    public Long getExp()
    {
        return exp;
    }

    public void setExp(Long exp)
    {
        this.exp = exp;
    }

    public String getReason()
    {
        return reason;
    }

    public void setReason(String reason)
    {
        this.reason = reason;
    }
}
