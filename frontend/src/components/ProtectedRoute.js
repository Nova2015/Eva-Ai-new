import React from 'react';
import { Navigate } from 'react-router-dom';
import { ensureLocalAuth } from '../localAuth';

export default function ProtectedRoute({ children, adminOnly = false }) {
  if (ensureLocalAuth()) return children;

  const user = JSON.parse(localStorage.getItem('aria_user') || '{}');
  const role = (user.role || 'user').toLowerCase();
  const isAdmin = role === 'admin';

  if (adminOnly && !isAdmin) {
    return <Navigate to="/chat" replace />;
  }

  return children;
}
