const LOCAL_NO_AUTH_HOSTS = new Set(['localhost', '127.0.0.1', '::1']);
const LOCAL_NO_AUTH_PORT = '4173';
const LOCAL_TOKEN = 'offline_4173';

const LOCAL_USER = {
  name: 'EVA Local User',
  email: 'local@eva.ai',
  role: 'user',
  provider: 'local-preview',
};

export const isLocalNoAuthEnabled = () => (
  typeof window !== 'undefined' &&
  LOCAL_NO_AUTH_HOSTS.has(window.location.hostname) &&
  window.location.port === LOCAL_NO_AUTH_PORT
);

export const ensureLocalAuth = () => {
  if (!isLocalNoAuthEnabled()) return false;

  localStorage.setItem('aria_token', LOCAL_TOKEN);
  localStorage.setItem('aria_user', JSON.stringify(LOCAL_USER));
  return true;
};
