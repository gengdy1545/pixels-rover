import React, { useState, useEffect } from 'react';
import { Form, Input, Button, message } from 'antd';
import { UserOutlined, MailOutlined, LockOutlined, BankOutlined } from '@ant-design/icons';
import { useNavigate, Link } from 'react-router-dom';
import { authApi } from '../../services/authApi';
import '../Login/index.css';

const Register: React.FC = () => {
  const [loading, setLoading] = useState(false);
  const [captchaImage, setCaptchaImage] = useState('');
  const [captchaKey, setCaptchaKey] = useState('');
  const navigate = useNavigate();

  const loadCaptcha = async () => {
    try {
      const response = await authApi.getCaptcha();
      const data = response.data.data;
      setCaptchaImage(data.captchaImage);
      setCaptchaKey(data.captchaKey);
    } catch {
      message.error('Failed to load captcha');
    }
  };

  useEffect(() => {
    loadCaptcha();
  }, []);

  const onFinish = async (values: {
    name: string;
    email: string;
    affiliation: string;
    password: string;
    captcha: string;
  }) => {
    setLoading(true);
    try {
      await authApi.register({
        name: values.name,
        email: values.email,
        affiliation: values.affiliation,
        password: values.password,
        captcha: values.captcha,
        captchaKey,
      });
      message.success('Registration successful! Please sign in.');
      navigate('/login');
    } catch (error: unknown) {
      const err = error as Error;
      message.error(err.message || 'Registration failed');
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
          <Form name="register" onFinish={onFinish} autoComplete="off" size="large">
            <Form.Item
              name="name"
              rules={[{ required: true, message: 'Please input your name' }]}
            >
              <Input prefix={<UserOutlined />} placeholder="your name" />
            </Form.Item>

            <Form.Item
              name="email"
              rules={[
                { required: true, message: 'Please input your email' },
                { type: 'email', message: 'Please enter a valid email' },
              ]}
            >
              <Input prefix={<MailOutlined />} placeholder="email" />
            </Form.Item>

            <Form.Item
              name="affiliation"
              rules={[{ required: true, message: 'Please input your affiliation' }]}
            >
              <Input prefix={<BankOutlined />} placeholder="your affiliation" />
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
                Sign Up
              </Button>
            </Form.Item>
          </Form>

          <div className="login-footer-link">
            <Link to="/login">already have an account</Link>
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

export default Register;
