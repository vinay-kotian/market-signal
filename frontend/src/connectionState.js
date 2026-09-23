export function authenticationStatus(connection, error) {
  if (error) return 'ERROR';
  return connection?.auth_status ?? 'NOT_CONNECTED';
}

export function initialPage(pathname) {
  const page = pathname.replace(/^\//, '').replace(/\/$/, '');
  return ['dashboard', 'levels', 'trades', 'report', 'backtest', 'connection', 'settings'].includes(page) ? page : 'dashboard';
}
