import React, { useEffect } from 'react';
import { Spin } from 'antd';
import { redirectToLogin } from '../../../../shared/storage/navigation';
import './index.css';

const Login: React.FC = () => {
  useEffect(() => {
    redirectToLogin('/home');
  }, []);

  return (
    <div className="login-wrapper" style={{ backgroundImage: 'url(/images/login-bg2.jpg)' }}>
      <Spin size="large" />
    </div>
  );
};

export default Login;
