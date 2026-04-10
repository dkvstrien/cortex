const BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:5092';

async function get<T>(path: string): Promise<T> {
  const resp = await fetch(`${BASE}${path}`);
  if (!resp.ok) throw new Error(`${resp.status} ${path}`);
  return resp.json();
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  const resp = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!resp.ok) throw new Error(`${resp.status} ${path}`);
  return resp.json();
}

export const api = {
  sessions: {
    list: (status?: string) =>
      get<import('./types').Session[]>(
        `/api/sessions${status && status !== 'all' ? `?status=${status}` : ''}`
      ),
    get: (id: string) => get<import('./types').Session>(`/api/sessions/${id}`),
    transcript: (id: string) =>
      get<{ session_id: string; chunks: import('./types').Chunk[] }>(
        `/api/sessions/${id}/transcript`
      ),
    pushVikunja: (id: string) =>
      post<{ task_id: number; task_url: string }>(`/api/sessions/${id}/vikunja`),
  },
  memories: {
    list: (type?: string) =>
      get<import('./types').Memory[]>(
        `/api/memories${type ? `?type=${type}` : ''}`
      ),
  },
};
