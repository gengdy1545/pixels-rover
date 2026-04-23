/**
 * User-facing identity shape projected from Ory Kratos `/sessions/whoami`.
 *
 * owning-service: kratos
 * source-of-truth: Ory Kratos public API session response, mapped in
 *   frontend/src/features/auth/services/authApi.ts.
 */
export interface UserInfo {
  id: string;
  name: string;
  email: string;
  affiliation: string;
}
