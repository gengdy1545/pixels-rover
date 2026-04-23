import React, { useEffect } from 'react';
import { Spin } from 'antd';
import { redirectToRegistration } from '../../../../shared/storage/navigation';
import '../Login/index.css';

const Register: React.FC = () => {
  useEffect(() => {
    redirectToRegistration('/home');
  }, []);

  return (
    <div className="login-wrapper" style={{ backgroundImage: 'url(/images/login-bg2.jpg)' }}>
      <Spin size="large" />
    </div>
  );
};

export default Register;
