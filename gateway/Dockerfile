FROM nginx:1.27-alpine

# Remove default nginx config
RUN rm /etc/nginx/conf.d/default.conf

# Copy CORS snippet
COPY snippets/cors.conf /etc/nginx/snippets/cors.conf

# Copy gateway config
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Create log directory
RUN mkdir -p /var/log/nginx

EXPOSE 80

HEALTHCHECK --interval=15s --timeout=5s --start-period=5s --retries=3 \
    CMD wget -qO- http://localhost:80/gateway/health || exit 1
