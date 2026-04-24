/// <reference types="vite/client" />

// Pixels Rover — frontend build-time env contract.
//
// ``VITE_API_BASE`` (optional) overrides the axios + SSE baseURL so a
// local dev build can target a remote gateway, or a non-browser client
// can point at a different host. Leaving it unset preserves same-origin
// behaviour (the bundle's host becomes the API host). See
// shared/api/client.ts#resolveApiUrl and .env.example.
interface ImportMetaEnv {
  readonly VITE_API_BASE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
