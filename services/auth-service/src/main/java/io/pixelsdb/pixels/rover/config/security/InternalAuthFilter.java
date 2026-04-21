package io.pixelsdb.pixels.rover.config.security;

import com.fasterxml.jackson.databind.ObjectMapper;
import io.pixelsdb.pixels.rover.config.common.ApiResponse;
import io.pixelsdb.pixels.rover.constant.ErrorCode;
import io.pixelsdb.pixels.rover.constant.HttpStatus;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.util.StringUtils;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;

/**
 * Guards internal-only routes used by the API gateway.
 */
public class InternalAuthFilter extends OncePerRequestFilter
{
    public static final String INTERNAL_AUTH_HEADER = "X-Internal-Auth";
    private static final String INTROSPECTION_PATH = "/api/internal/auth/introspect";

    private final String sharedSecret;
    private final ObjectMapper objectMapper = new ObjectMapper();

    public InternalAuthFilter(String sharedSecret)
    {
        this.sharedSecret = sharedSecret;
    }

    @Override
    protected boolean shouldNotFilter(HttpServletRequest request)
    {
        return !INTROSPECTION_PATH.equals(request.getRequestURI());
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request,
                                    HttpServletResponse response,
                                    FilterChain filterChain) throws ServletException, IOException
    {
        String provided = request.getHeader(INTERNAL_AUTH_HEADER);
        if (!StringUtils.hasText(sharedSecret) || !sharedSecret.equals(provided))
        {
            response.setStatus(HttpStatus.UNAUTHORIZED);
            response.setContentType("application/json;charset=UTF-8");
            response.getWriter().write(objectMapper.writeValueAsString(
                    ApiResponse.error(ErrorCode.AUTHENTICATION_REQUIRED, "Internal authentication failed")
            ));
            return;
        }

        filterChain.doFilter(request, response);
    }
}
