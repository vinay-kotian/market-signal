export async function request(path, options = {}) {
  const { responseType = 'json', ...fetchOptions } = options;
  const response = await fetch(`/api${path}`, {
    ...fetchOptions,
    headers: { 'Content-Type': 'application/json', ...options.headers },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail = typeof body.detail === 'string' ? body.detail
      : Array.isArray(body.detail) ? body.detail.map(error => error.msg).join('; ')
      : `Request failed (${response.status})`;
    throw new Error(detail);
  }
  if (responseType === 'blob') return response.blob();
  return response.status === 204 ? null : response.json();
}
