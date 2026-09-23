export function authenticationStatus(connection, error) {
  if (error) return 'ERROR';
  return connection?.auth_status ?? 'NOT_CONNECTED';
}

export function initialPage(pathname) {
  const page = pathname.replace(/^\//, '').replace(/\/$/, '');
  if (page === 'connection') return 'settings';
  return ['dashboard', 'levels', 'trades', 'report', 'backtest', 'settings'].includes(page) ? page : 'dashboard';
}
