import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, buildUrl, request } from "../src/api/http";
import { json } from "./support/fake-api";

afterEach(() => vi.unstubAllGlobals());

function respondWith(response: Response | Error) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => {
      if (response instanceof Error) throw response;
      return response;
    }),
  );
}

async function failure(): Promise<ApiError> {
  try {
    await request("/api/v1/tasks");
  } catch (error) {
    if (error instanceof ApiError) return error;
  }
  throw new Error("expected an ApiError");
}

describe("buildUrl", () => {
  it("drops empty and missing query values", () => {
    expect(
      buildUrl("/api/v1/tasks", { status: "pending", due_from: "", due_to: undefined, page: 2, x: null }),
    ).toBe("/api/v1/tasks?status=pending&page=2");
    expect(buildUrl("/api/v1/tasks", {})).toBe("/api/v1/tasks");
  });
});

describe("request errors", () => {
  it("keeps the backend's message and code", async () => {
    respondWith(json({ detail: "Task not found", code: "task_not_found" }, 404));
    const error = await failure();
    expect(error).toMatchObject({ status: 404, message: "Task not found", code: "task_not_found" });
  });

  it("joins FastAPI validation messages", async () => {
    respondWith(json({ detail: [{ msg: "Field required" }, { msg: "Too long" }] }, 422));
    expect((await failure()).message).toBe("Field required; Too long");
  });

  it("tells the user when to retry after a 429", async () => {
    respondWith(json({ detail: "Too many requests", code: "rate_limited" }, 429, { "Retry-After": "30" }));
    const error = await failure();
    expect(error.code).toBe("rate_limited");
    expect(error.message).toBe("Too many requests. Try again in 30 s.");
  });

  it("survives a non-JSON error page", async () => {
    respondWith(new Response("<html>Bad gateway</html>", { status: 502 }));
    expect((await failure()).message).toBe("The server had a problem. Try again.");
  });

  it("reports a network failure as status 0", async () => {
    respondWith(new TypeError("Failed to fetch"));
    expect((await failure()).status).toBe(0);
  });

  it("returns undefined for 204", async () => {
    respondWith(new Response(null, { status: 204 }));
    await expect(request("/api/v1/tasks/1")).resolves.toBeUndefined();
  });
});
