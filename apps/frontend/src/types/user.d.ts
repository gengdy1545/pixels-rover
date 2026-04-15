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

export interface TokenResponse {
  accessToken: string;
  refreshToken: string;
  sessionId?: string;
}

export interface AccessTokenResponse {
  accessToken: string;
  refreshToken?: string;
  sessionId?: string;
}

export interface CaptchaResponse {
  captchaKey: string;
  captchaImage: string;
}
