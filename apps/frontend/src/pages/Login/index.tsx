import React, { useState, useEffect } from 'react';
import { Form, Input, Button, message } from 'antd';
import { MailOutlined, LockOutlined } from '@ant-design/icons';
import { useNavigate, Link } from 'react-router-dom';
import { authApi } from '../../api';
import { useAuthStore } from '../../stores/authStore';
import './index.css';

const Login: React.FC = () => {
  const [loading, setLoading] = useState(false);
  const [captchaImage, setCaptchaImage] = useState('');
  const [captchaKey, setCaptchaKey] = useState('');
  const navigate = useNavigate();
  const checkAuth = useAuthStore((state) => state.checkAuth);

  const loadCaptcha = async () => {
    try {
      const data = await authApi.getCaptcha();
      setCaptchaImage(data.captchaImage);
      setCaptchaKey(data.captchaKey);
    } catch {
      message.error('Failed to load captcha');
    }
  };

  useEffect(() => {
    loadCaptcha();
  }, []);

  const onFinish = async (values: { username: string; password: string; captcha: string }) => {
    setLoading(true);
    try {
      await authApi.login({
        username: values.username,
        password: values.password,
        captcha: values.captcha,
        captchaKey,
      });
      // Tokens are set as HttpOnly cookies by the server.
      // Verify login state and load user info.
      await checkAuth();
      message.success('Login successful');
      navigate('/home');
    } catch (error: unknown) {
      const err = error as Error;
      message.error(err.message || 'Login failed');
      loadCaptcha();
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="login-wrapper" style={{ backgroundImage: 'url(/images/login-bg2.jpg)' }}>
      <div className="login-container">
        <div className="login-center">
          <div className="login-title">
            <img src="/images/logo-sidebar.png" alt="PixelsDB" />
          </div>
          <Form name="login" onFinish={onFinish} autoComplete="off" size="large">
            <Form.Item
              name="username"
              rules={[
                { required: true, message: 'Please input your email' },
                { type: 'email', message: 'Please enter a valid email' },
              ]}
            >
              <Input prefix={<MailOutlined />} placeholder="username (email)" />
            </Form.Item>

            <Form.Item
              name="password"
              rules={[{ required: true, message: 'Please input your password' }]}
            >
              <Input.Password prefix={<LockOutlined />} placeholder="password" />
            </Form.Item>

            <Form.Item name="captcha" rules={[{ required: true, message: 'Please input verification code' }]}>
              <div className="captcha-row">
                <Input placeholder="verification code" maxLength={5} className="captcha-input" />
                <img
                  src={captchaImage}
                  alt="captcha"
                  className="captcha-image"
                  onClick={loadCaptcha}
                  title="Click to change verification code"
                />
              </div>
            </Form.Item>

            <Form.Item>
              <Button type="primary" htmlType="submit" loading={loading} block>
                Sign In
              </Button>
            </Form.Item>
          </Form>

          <div className="login-footer-link">
            <Link to="/register">don't have an account</Link>
          </div>

          <hr />
          <footer className="login-footer">
            <p>Copyright © 2023 <a href="https://github.com/pixelsdb/pixels">PixelsDB</a>. All right reserved</p>
          </footer>
        </div>
      </div>
    </div>
  );
};

export default Login;
