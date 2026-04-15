FROM nginx:1.27-alpine

# Install NJS module for response body processing (cookie injection)
RUN apk add --no-cache nginx-mod-http-js

# Remove default nginx config
RUN rm /etc/nginx/conf.d/default.conf

# Copy CORS snippet
COPY snippets/cors.conf /etc/nginx/snippets/cors.conf

# Copy NJS cookie handler script
COPY njs/cookie_handler.js /etc/nginx/njs/cookie_handler.js

# Copy gateway config as template (env vars will be substituted at startup)
COPY nginx.conf /etc/nginx/templates/default.conf.template

# Create log directory
RUN mkdir -p /var/log/nginx

# Entrypoint script: substitute env vars in nginx config, then start nginx
# The official nginx image supports /etc/nginx/templates/*.template with envsubst
# but we need to control which variables are substituted to avoid breaking nginx vars
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

EXPOSE 80

HEALTHCHECK --interval=15s --timeout=5s --start-period=5s --retries=3 \
    CMD wget -qO- http://localhost:80/gateway/health || exit 1

ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["nginx", "-g", "daemon off;"]
