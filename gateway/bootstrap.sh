#!/bin/sh
set -eu

admin_api="http://gateway:9180/apisix/admin"

if [ -z "${APISIX_ADMIN_API_KEY:-}" ]; then
  echo "APISIX_ADMIN_API_KEY is required" >&2
  exit 1
fi

put_resource() {
  resource="$1"
  resource_id="$2"
  payload="$3"

  curl -fsS -X PUT \
    -H "X-API-KEY: ${APISIX_ADMIN_API_KEY}" \
    -H "Content-Type: application/json" \
    "${admin_api}/${resource}/${resource_id}" \
    -d "${payload}" >/dev/null
}

wait_for_admin() {
  attempts=0
  until curl -fsS -H "X-API-KEY: ${APISIX_ADMIN_API_KEY}" "${admin_api}/routes" >/dev/null 2>&1
  do
    attempts=$((attempts + 1))
    if [ "${attempts}" -ge 60 ]; then
      echo "APISIX Admin API did not become ready in time" >&2
      exit 1
    fi
    sleep 2
  done
}

wait_for_admin

put_resource upstreams 1 '{
  "name": "auth-service",
  "type": "roundrobin",
  "nodes": {
    "auth-service:8081": 1
  }
}'

put_resource upstreams 2 '{
  "name": "assistant-service",
  "type": "roundrobin",
  "nodes": {
    "assistant-service:8090": 1
  }
}'

put_resource upstreams 3 '{
  "name": "frontend",
  "type": "roundrobin",
  "nodes": {
    "frontend:80": 1
  }
}'

put_resource routes 100 '{
  "name": "gateway-health",
  "priority": 1000,
  "uri": "/gateway/health",
  "methods": ["GET"],
  "plugins": {
    "proxy-rewrite": {
      "uri": "/health"
    }
  },
  "upstream_id": 1
}'

put_resource routes 200 '{
  "name": "auth-login",
  "priority": 950,
  "uri": "/api/v1/auth/login",
  "methods": ["POST", "OPTIONS"],
  "plugins": {
    "gateway-auth": {
      "require_auth": false,
      "csrf_protect": false,
      "introspection_url": "http://auth-service:8081/api/internal/auth/introspect"
    }
  },
  "upstream_id": 1
}'

put_resource routes 210 '{
  "name": "auth-register",
  "priority": 950,
  "uri": "/api/v1/auth/register",
  "methods": ["POST", "OPTIONS"],
  "plugins": {
    "gateway-auth": {
      "require_auth": false,
      "csrf_protect": false,
      "introspection_url": "http://auth-service:8081/api/internal/auth/introspect"
    }
  },
  "upstream_id": 1
}'

put_resource routes 220 '{
  "name": "auth-captcha",
  "priority": 950,
  "uri": "/api/v1/auth/captcha",
  "methods": ["GET", "OPTIONS"],
  "plugins": {
    "gateway-auth": {
      "require_auth": false,
      "csrf_protect": false,
      "introspection_url": "http://auth-service:8081/api/internal/auth/introspect"
    }
  },
  "upstream_id": 1
}'

put_resource routes 240 '{
  "name": "auth-refresh",
  "priority": 940,
  "uri": "/api/v1/auth/refresh",
  "methods": ["POST", "OPTIONS"],
  "plugins": {
    "gateway-auth": {
      "require_auth": false,
      "csrf_protect": true,
      "introspection_url": "http://auth-service:8081/api/internal/auth/introspect"
    }
  },
  "upstream_id": 1
}'

put_resource routes 300 '{
  "name": "auth-protected",
  "priority": 900,
  "uri": "/api/v1/auth/*",
  "plugins": {
    "gateway-auth": {
      "require_auth": true,
      "csrf_protect": true,
      "introspection_url": "http://auth-service:8081/api/internal/auth/introspect"
    }
  },
  "upstream_id": 1
}'

put_resource routes 310 '{
  "name": "analysis-submit",
  "priority": 880,
  "uri": "/api/v1/analysis",
  "methods": ["POST", "OPTIONS"],
  "plugins": {
    "gateway-auth": {
      "require_auth": true,
      "csrf_protect": true,
      "introspection_url": "http://auth-service:8081/api/internal/auth/introspect"
    }
  },
  "upstream_id": 2
}'

put_resource routes 320 '{
  "name": "analysis-detail",
  "priority": 870,
  "uri": "/api/v1/analysis/*",
  "plugins": {
    "gateway-auth": {
      "require_auth": true,
      "csrf_protect": true,
      "introspection_url": "http://auth-service:8081/api/internal/auth/introspect"
    }
  },
  "upstream_id": 2
}'

put_resource routes 330 '{
  "name": "conversations-root",
  "priority": 860,
  "uri": "/api/v1/conversations",
  "methods": ["GET", "POST", "OPTIONS"],
  "plugins": {
    "gateway-auth": {
      "require_auth": true,
      "csrf_protect": true,
      "introspection_url": "http://auth-service:8081/api/internal/auth/introspect"
    }
  },
  "upstream_id": 2
}'

put_resource routes 400 '{
  "name": "conversations-detail",
  "priority": 850,
  "uri": "/api/v1/conversations/*",
  "plugins": {
    "gateway-auth": {
      "require_auth": true,
      "csrf_protect": true,
      "introspection_url": "http://auth-service:8081/api/internal/auth/introspect"
    }
  },
  "upstream_id": 2
}'

put_resource routes 410 '{
  "name": "semantic-protected",
  "priority": 840,
  "uri": "/api/v1/semantic/*",
  "plugins": {
    "gateway-auth": {
      "require_auth": true,
      "csrf_protect": true,
      "introspection_url": "http://auth-service:8081/api/internal/auth/introspect"
    }
  },
  "upstream_id": 2
}'

put_resource routes 420 '{
  "name": "analysis-backends-root",
  "priority": 890,
  "uri": "/api/v1/analysis/backends",
  "methods": ["GET", "OPTIONS"],
  "plugins": {
    "gateway-auth": {
      "require_auth": true,
      "csrf_protect": true,
      "introspection_url": "http://auth-service:8081/api/internal/auth/introspect"
    }
  },
  "upstream_id": 2
}'

put_resource routes 430 '{
  "name": "analysis-backends-detail",
  "priority": 885,
  "uri": "/api/v1/analysis/backends/*",
  "plugins": {
    "gateway-auth": {
      "require_auth": true,
      "csrf_protect": true,
      "introspection_url": "http://auth-service:8081/api/internal/auth/introspect"
    }
  },
  "upstream_id": 2
}'

put_resource routes 900 '{
  "name": "frontend",
  "priority": 1,
  "uri": "/*",
  "upstream_id": 3
}'

echo "APISIX bootstrap completed"
