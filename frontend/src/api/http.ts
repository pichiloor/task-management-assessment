/** Error raised for any failed API call. `status` is 0 when the server could
 * not be reached at all. `code` is the backend's machine-readable code
 * (for example `rate_limited` or `task_not_found`) when it sent one. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string | null;

  constructor(status: number, message: string, code: string | null = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

type RequestOptions = {
  method?: string;
  token?: string | null;
  json?: unknown;
  form?: URLSearchParams;
  query?: Record<string, string | number | null | undefined>;
};

/** Relative URL, so the browser calls the same origin nginx serves. */
export function buildUrl(
  path: string,
  query?: RequestOptions["query"],
): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value != null && value !== "") params.set(key, String(value));
  }
  const search = params.toString();
  return search ? `${path}?${search}` : path;
}

/** Fetch with the bearer token and error translation, returning the raw
 * response (used directly for file downloads). */
export async function send(
  path: string,
  options: RequestOptions = {},
): Promise<Response> {
  const headers = new Headers({ Accept: "application/json" });
  if (options.token) headers.set("Authorization", `Bearer ${options.token}`);
  let body: BodyInit | undefined;
  if (options.json !== undefined) {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(options.json);
  } else if (options.form) {
    body = options.form;
  }

  let response: Response;
  try {
    response = await fetch(buildUrl(path, options.query), {
      method: options.method ?? "GET",
      headers,
      body,
    });
  } catch {
    throw new ApiError(0, "Cannot reach the server. Check your connection.");
  }
  if (!response.ok) throw await toApiError(response);
  return response;
}

/** Same as `send`, parsing the JSON body (or `undefined` for 204). */
export async function request<T>(
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const response = await send(path, options);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

async function toApiError(response: Response): Promise<ApiError> {
  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    // Not JSON (for example an HTML error page from the proxy).
  }
  const { detail, code } = (payload ?? {}) as {
    detail?: unknown;
    code?: unknown;
  };
  let message = defaultMessage(response.status);
  if (typeof detail === "string") {
    message = detail;
  } else if (Array.isArray(detail) && detail.length > 0) {
    // FastAPI request validation: [{loc, msg, type}, ...]
    message = detail
      .map((item: { msg?: unknown }) => String(item.msg ?? "Invalid value"))
      .join("; ");
  }
  if (response.status === 429) {
    const retry = response.headers.get("Retry-After");
    message = retry
      ? `Too many requests. Try again in ${retry} s.`
      : "Too many requests. Try again shortly.";
  }
  return new ApiError(
    response.status,
    message,
    typeof code === "string" ? code : null,
  );
}

function defaultMessage(status: number): string {
  if (status >= 500) return "The server had a problem. Try again.";
  return `Request failed (${status}).`;
}
