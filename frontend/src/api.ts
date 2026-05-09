function getCookie(name: string): string | null {
  const all = document.cookie ? document.cookie.split('; ') : [];
  for (const item of all) {
    const [k, ...rest] = item.split('=');
    if (k === name) return decodeURIComponent(rest.join('='));
  }
  return null;
}

export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers || {});
  headers.set('Accept', 'application/json');
  if (init.body && !(init.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json');
  }

  const method = (init.method || 'GET').toUpperCase();
  if (method !== 'GET') {
    const csrf = getCookie('liveu_csrf');
    if (csrf) headers.set('X-CSRF-Token', csrf);
  }

  const res = await fetch(path, {
    ...init,
    headers,
    credentials: 'include',
  });

  if (!res.ok) {
    let message = `Request failed (${res.status})`;
    try {
      const data = await res.json();
      if (data?.detail) message = data.detail;
    } catch {
      // If response body can't be parsed, check for content length mismatch
      if (res.status === 0 || res.headers.get('content-length') === null) {
        message = `Server connection error: ${res.url}`;
      }
    }
    throw new Error(message);
  }
  const data = await res.json();
  return data as T;
}

export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes)) return '-';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let value = bytes;
  let idx = 0;
  while (value >= 1024 && idx < units.length - 1) {
    value /= 1024;
    idx += 1;
  }
  return `${value.toFixed(1)} ${units[idx]}`;
}
