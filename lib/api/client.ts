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
  // FormData is the exception: the browser has to set its own multipart boundary, so an
  // explicit Content-Type here would make the body unreadable to the server.
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type"))
    headers.set("Content-Type", "application/json");
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

/** For endpoints that answer 204 with no body at all, such as deleting a source. */
export async function apiSend(path: string, getToken: TokenGetter, init: RequestInit = {}): Promise<void> {
  await send(path, getToken, init);
}

/**
 * A multipart upload of one file under the field name the route reads. It goes through the same
 * `send`, so the bearer token, the `detail` unwrapping and `ApiError` are all the ones every other
 * call uses; the Content-Type is left to the browser (see above).
 */
export async function apiUpload<T>(path: string, file: File, getToken: TokenGetter, field = "file"): Promise<T> {
  const body = new FormData();
  body.append(field, file);
  const response = await send(path, getToken, { method: "POST", body });
  return (await response.json()) as T;
}
