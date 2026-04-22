import React, { Suspense, useEffect } from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { Spin } from 'antd';
import { useAuthStore } from '../../stores/authStore';

// Lazy load pages
const Login = React.lazy(() => import('../../pages/Login'));
const Register = React.lazy(() => import('../../pages/Register'));
const Home = React.lazy(() => import('../../pages/Home'));

// Auth guard component
const PrivateRoute: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { isAuthenticated, isLoading, checkAuth } = useAuthStore();

  useEffect(() => {
    if (isLoading) {
      checkAuth();
    }
  }, [isLoading, checkAuth]);

  if (isLoading) {
    return <Loading />;
  }

  return isAuthenticated ? <>{children}</> : <Navigate to="/login" replace />;
};

// Public route: redirect to home if already authenticated
const PublicRoute: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { isAuthenticated, isLoading, checkAuth } = useAuthStore();

  useEffect(() => {
    if (isLoading) {
      checkAuth();
    }
  }, [isLoading, checkAuth]);

  if (isLoading) {
    return <Loading />;
  }

  return isAuthenticated ? <Navigate to="/home" replace /> : <>{children}</>;
};

const Loading = () => (
  <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh' }}>
    <Spin size="large" />
  </div>
);

const AppRouter: React.FC = () => {
  return (
    <Suspense fallback={<Loading />}>
      <Routes>
        <Route path="/login" element={<PublicRoute><Login /></PublicRoute>} />
        <Route path="/register" element={<PublicRoute><Register /></PublicRoute>} />
        <Route path="/home" element={<PrivateRoute><Home /></PrivateRoute>} />
        <Route path="/" element={<Navigate to="/home" replace />} />
        <Route path="*" element={<Navigate to="/home" replace />} />
      </Routes>
    </Suspense>
  );
};

export default AppRouter;
