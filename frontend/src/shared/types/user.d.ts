/**
 * User-facing shapes served by `auth-service` (/me, login, register, captcha).
 *
 * owning-service: auth-service
 * source-of-truth: services/auth-service/openapi.json#/components/schemas/
 *   — UserVO / LoginRequest / RegisterRequest / CaptchaResponse (and the
 *     hand-written payload classes in services/auth-service/src/main/java/
 *     io/pixelsdb/pixels/rover/controller / service /domain that back them).
 *
 * Hand-mirrored per frontend.md §4.6 "手写契约镜像文件的顶部元数据" rule;
 * scripts/check-contracts.py enforces shape alignment for the error-code
 * union but not general field shape — deltas here need a paired backend PR.
 */
export interface UserInfo {
  id: number;
  name: string;
  email: string;
  affiliation: string;
}

export interface LoginRequest {
  username: string;
  password: string;
  captcha: string;
  captchaKey: string;
}

export interface RegisterRequest {
  name: string;
  email: string;
  affiliation: string;
  password: string;
  captcha: string;
  captchaKey: string;
}

export interface CaptchaResponse {
  captchaKey: string;
  captchaImage: string;
}
