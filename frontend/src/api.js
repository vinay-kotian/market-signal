export async function request(path, options = {}) {
  const response = await fetch(`/api${path}`, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...options.headers },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail = typeof body.detail === 'string' ? body.detail
      : Array.isArray(body.detail) ? body.detail.map(error => error.msg).join('; ')
      : `Request failed (${response.status})`;
    throw new Error(detail);
  }
  return response.status === 204 ? null : response.json();
}
