export class ApiError extends Error {
  constructor(public status: number, public detail: string) {
    super(detail);
  }
}

export type TokenGetter = () => Promise<string | null>;

/** One request with the session token attached; a non-2xx answer becomes an ApiError. */
async function send(path: string, getToken: TokenGetter, init: RequestInit): Promise<Response> {
  const token = await getToken();
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const response = await fetch(path, { ...init, headers });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      /* not json */
    }
    throw new ApiError(response.status, detail);
  }
  return response;
}

export async function apiFetch<T>(path: string, getToken: TokenGetter, init: RequestInit = {}): Promise<T> {
  const response = await send(path, getToken, init);
  return (await response.json()) as T;
}

/** For endpoints that answer with bytes rather than JSON, such as a rendered page image. */
export async function apiFetchBlob(path: string, getToken: TokenGetter, init: RequestInit = {}): Promise<Blob> {
  const response = await send(path, getToken, init);
  return await response.blob();
}
