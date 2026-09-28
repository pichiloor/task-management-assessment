import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ANA, BRUNO, page, task } from "./support/data";
import { fakeApi, json } from "./support/fake-api";
import { renderApp } from "./support/render";

const TOKEN_KEY = "task-management.token";

afterEach(() => vi.unstubAllGlobals());

function loggedIn() {
  sessionStorage.setItem(TOKEN_KEY, "token-ana");
}

const common = {
  "GET /api/v1/users/me": () => json(ANA),
  "GET /api/v1/users": () => json([{ id: ANA.id, name: ANA.name }, BRUNO]),
};

describe("login", () => {
  it("logs in with the form and shows the user's tasks", async () => {
    const { calls } = fakeApi({
      ...common,
      "POST /api/v1/auth/token": () => json({ access_token: "token-ana", token_type: "bearer" }),
      "GET /api/v1/tasks": () => json(page([task()])),
    });
    const user = userEvent.setup();
    renderApp("/");

    await user.type(await screen.findByLabelText("Email"), "ana@example.com");
    await user.type(screen.getByLabelText("Password"), "demo-password-2026");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("article", { name: "Write the report" })).toBeInTheDocument();
    expect(calls.find((c) => c.path === "/api/v1/auth/token")?.body).toEqual({
      username: "ana@example.com",
      password: "demo-password-2026", // pragma: allowlist secret
    });
    expect(calls.find((c) => c.path === "/api/v1/tasks")?.auth).toBe("Bearer token-ana");
    expect(sessionStorage.getItem(TOKEN_KEY)).toBe("token-ana");
  });

  it("shows a clear message for wrong credentials", async () => {
    fakeApi({
      "POST /api/v1/auth/token": () => json({ detail: "Invalid credentials", code: "invalid_credentials" }, 401),
    });
    const user = userEvent.setup();
    renderApp("/login");

    await user.type(screen.getByLabelText("Email"), "ana@example.com");
    await user.type(screen.getByLabelText("Password"), "nope");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Wrong email or password.");
  });

  it("returns to the login page when the token is rejected", async () => {
    loggedIn();
    fakeApi({ "GET /api/v1/users/me": () => json({ detail: "Invalid or expired token", code: "invalid_token" }, 401) });
    renderApp("/");

    expect(await screen.findByRole("button", { name: "Sign in" })).toBeInTheDocument();
    expect(sessionStorage.getItem(TOKEN_KEY)).toBeNull();
  });
});

describe("tasks", () => {
  beforeEach(loggedIn);

  it("shows edit and delete only to the creator", async () => {
    fakeApi({
      ...common,
      "GET /api/v1/tasks": () =>
        json(
          page([
            task({ id: 1, title: "Mine" }),
            task({ id: 2, title: "Assigned to me", creator_id: BRUNO.id, assignee_id: ANA.id }),
          ]),
        ),
    });
    renderApp("/");

    const mine = await screen.findByRole("article", { name: "Mine" });
    const assigned = screen.getByRole("article", { name: "Assigned to me" });
    expect(within(mine).getByRole("button", { name: "Edit" })).toBeInTheDocument();
    expect(within(assigned).queryByRole("button", { name: "Edit" })).toBeNull();
    expect(within(assigned).queryByRole("button", { name: "Delete" })).toBeNull();
    expect(within(assigned).getByText(new RegExp(`^${BRUNO.name} · `))).toBeInTheDocument();
    expect(within(assigned).getByRole("button", { name: "Mark as completed" })).toBeInTheDocument();
  });

  it("the check button completes a task and reopens it", async () => {
    let status: "pending" | "completed" = "pending";
    const { calls } = fakeApi({
      ...common,
      "GET /api/v1/tasks": () => json(page([task({ status })])),
      "PATCH /api/v1/tasks/10": ({ body }) => {
        status = (body as { status: typeof status }).status;
        return json(task({ status }));
      },
    });
    const user = userEvent.setup();
    renderApp("/");

    const card = await screen.findByRole("article", { name: "Write the report" });
    const check = within(card).getByRole("button", { name: "Mark as completed" });
    expect(check).toHaveAttribute("aria-pressed", "false");
    await user.click(check);

    const done = await within(card).findByRole("button", { name: "Mark as not completed" });
    expect(done).toHaveAttribute("aria-pressed", "true");
    expect(within(card).getByRole("combobox")).toHaveValue("completed");
    expect(calls.filter((c) => c.method === "PATCH").map((c) => c.body)).toEqual([
      { status: "completed" },
    ]);

    await user.click(done);
    await within(card).findByRole("button", { name: "Mark as completed" });
    expect(calls.filter((c) => c.method === "PATCH").at(-1)?.body).toEqual({ status: "pending" });
  });

  it("creates a task from the dialog", async () => {
    const { calls } = fakeApi({
      ...common,
      "GET /api/v1/tasks": () => json(page([])),
      "POST /api/v1/tasks": () => json(task({ title: "New one" }), 201),
    });
    const user = userEvent.setup();
    renderApp("/");

    await user.click(await screen.findByRole("button", { name: "+ New task" }));
    const dialog = screen.getByRole("dialog", { name: "New task" });
    await user.click(within(dialog).getByRole("button", { name: "Create task" }));
    expect(within(dialog).getByRole("alert")).toHaveTextContent("Title is required.");

    await user.type(within(dialog).getByLabelText("Title"), "New one");
    await user.selectOptions(within(dialog).getByLabelText("Assignee"), String(BRUNO.id));
    await user.click(within(dialog).getByRole("button", { name: "Create task" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(calls.find((c) => c.method === "POST" && c.path === "/api/v1/tasks")?.body).toEqual({
      title: "New one",
      description: "",
      assignee_id: BRUNO.id,
      due_date: null,
    });
  });

  it("asks for confirmation before deleting", async () => {
    const { calls } = fakeApi({
      ...common,
      "GET /api/v1/tasks": () => json(page([task()])),
      "DELETE /api/v1/tasks/10": () => new Response(null, { status: 204 }),
    });
    const user = userEvent.setup();
    renderApp("/");

    const card = await screen.findByRole("article", { name: "Write the report" });
    await user.click(within(card).getByRole("button", { name: "Delete" }));
    const dialog = screen.getByRole("dialog", { name: "Delete task" });
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(calls.some((c) => c.method === "DELETE")).toBe(false);

    await user.click(within(card).getByRole("button", { name: "Delete" }));
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(calls.some((c) => c.method === "DELETE")).toBe(true));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("sends the filters and page from the URL", async () => {
    const { calls } = fakeApi({
      ...common,
      "GET /api/v1/tasks": () => json(page([task()], { total: 25, page: 2, pages: 3 })),
    });
    const user = userEvent.setup();
    renderApp("/?status=in_progress&due_from=2026-09-01&page=2");

    await screen.findByText(/Page 2 of 3/);
    const first = calls.find((c) => c.path === "/api/v1/tasks");
    expect(first).toBeDefined();
    const url = vi.mocked(fetch).mock.calls.map(([input]) => String(input)).find((u) => u.startsWith("/api/v1/tasks"));
    expect(url).toBe("/api/v1/tasks?status=in_progress&due_from=2026-09-01&sort=due_date&page=2&page_size=10");

    await user.selectOptions(screen.getByLabelText("Status"), "completed");
    await waitFor(() =>
      expect(
        vi.mocked(fetch).mock.calls.map(([input]) => String(input)),
      ).toContain("/api/v1/tasks?status=completed&due_from=2026-09-01&sort=due_date&page=1&page_size=10"),
    );
  });

  it("does not query an inverted date range", async () => {
    fakeApi({ ...common, "GET /api/v1/tasks": () => json(page([])) });
    renderApp("/?due_from=2026-10-10&due_to=2026-10-01");

    expect(await screen.findByRole("alert")).toHaveTextContent("must not be after");
    expect(vi.mocked(fetch).mock.calls.some(([input]) => String(input).startsWith("/api/v1/tasks"))).toBe(false);
  });
});

describe("CSV export", () => {
  beforeEach(loggedIn);

  it("polls the job and downloads the file with the token", async () => {
    let polls = 0;
    const pending = { id: 7, status: "pending", filters: { status: null, due_from: null, due_to: null }, row_count: null, error_code: null, created_at: "2026-09-28T12:00:00Z", finished_at: null, expires_at: null, download_url: null };
    const { calls } = fakeApi({
      ...common,
      "GET /api/v1/tasks": () => json(page([task()])),
      "POST /api/v1/exports": () => json(pending, 202),
      "GET /api/v1/exports/7": () =>
        json(
          ++polls < 2
            ? pending
            : { ...pending, status: "completed", row_count: 3, download_url: "/api/v1/exports/7/download" },
        ),
      "GET /api/v1/exports/7/download": () => new Response("id,title\n", { headers: { "Content-Type": "text/csv" } }),
    });
    const createObjectURL = vi.fn(() => "blob:csv");
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL, revokeObjectURL: vi.fn() }));
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    const user = userEvent.setup();
    renderApp("/?status=pending");

    await user.click(await screen.findByRole("button", { name: "Export CSV" }));
    expect(await screen.findByText(/Ready: 3 rows/, {}, { timeout: 4000 })).toBeInTheDocument();
    expect(calls.find((c) => c.path === "/api/v1/exports")?.body).toEqual({ status: "pending" });

    await user.click(screen.getByRole("button", { name: "Download" }));
    await waitFor(() => expect(click).toHaveBeenCalled());
    expect(createObjectURL).toHaveBeenCalled();
    expect(calls.find((c) => c.path === "/api/v1/exports/7/download")?.auth).toBe("Bearer token-ana");
    click.mockRestore();
  });
});

describe("export polling", () => {
  beforeEach(loggedIn);

  it("keeps polling after a failed status request", async () => {
    let polls = 0;
    const pending = { id: 8, status: "pending", filters: { status: null, due_from: null, due_to: null }, row_count: null, error_code: null, created_at: "2026-09-28T12:00:00Z", finished_at: null, expires_at: null, download_url: null };
    fakeApi({
      ...common,
      "GET /api/v1/tasks": () => json(page([task()])),
      "POST /api/v1/exports": () => json(pending, 202),
      "GET /api/v1/exports/8": () =>
        ++polls === 1
          ? json({ detail: "Too many requests", code: "rate_limited" }, 429, { "Retry-After": "1" })
          : json({ ...pending, status: "completed", row_count: 1, download_url: "/api/v1/exports/8/download" }),
    });
    const user = userEvent.setup();
    renderApp("/");

    await user.click(await screen.findByRole("button", { name: "Export CSV" }));
    expect(await screen.findByText(/Ready: 1 row/, {}, { timeout: 5000 })).toBeInTheDocument();
  });
});

describe("modal", () => {
  beforeEach(loggedIn);

  it("keeps keyboard focus inside the dialog", async () => {
    fakeApi({ ...common, "GET /api/v1/tasks": () => json(page([])) });
    const user = userEvent.setup();
    renderApp("/");

    await user.click(await screen.findByRole("button", { name: "+ New task" }));
    const dialog = screen.getByRole("dialog");
    for (let i = 0; i < 12; i++) {
      await user.tab();
      expect(dialog).toContainElement(document.activeElement as HTMLElement);
    }
    for (let i = 0; i < 3; i++) {
      await user.tab({ shift: true });
      expect(dialog).toContainElement(document.activeElement as HTMLElement);
    }
  });
});

describe("late responses", () => {
  it("a save finishing after its dialog was cancelled does not close a new one", async () => {
    loggedIn();
    let finish: (r: Response) => void = () => {};
    fakeApi({
      ...common,
      "GET /api/v1/tasks": () => json(page([])),
      "POST /api/v1/tasks": () => new Promise<Response>((resolve) => (finish = resolve)),
    });
    const user = userEvent.setup();
    renderApp("/");

    await user.click(await screen.findByRole("button", { name: "+ New task" }));
    await user.type(screen.getByLabelText("Title"), "Slow one");
    await user.click(screen.getByRole("button", { name: "Create task" }));
    await user.click(screen.getByRole("button", { name: "Cancel" }));

    await user.click(screen.getByRole("button", { name: "+ New task" }));
    await user.type(screen.getByLabelText("Title"), "Draft");
    finish(json(task({ title: "Slow one" }), 201));

    await waitFor(() => expect(vi.mocked(fetch).mock.calls.length).toBeGreaterThan(3));
    await new Promise((r) => setTimeout(r, 50));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByLabelText("Title")).toHaveValue("Draft");
  });

  it("a 401 for an old session does not log out the new one", async () => {
    sessionStorage.setItem(TOKEN_KEY, "token-old");
    let rejectOld: (r: Response) => void = () => {};
    fakeApi({
      ...common,
      "POST /api/v1/auth/token": () => json({ access_token: "token-new", token_type: "bearer" }),
      "GET /api/v1/tasks": ({ headers }) =>
        headers.get("Authorization") === "Bearer token-old"
          ? new Promise<Response>((resolve) => (rejectOld = resolve))
          : json(page([task()])),
    });
    const user = userEvent.setup();
    renderApp("/");

    await user.click(await screen.findByRole("button", { name: "Log out" }));
    await user.type(await screen.findByLabelText("Email"), "ana@example.com");
    await user.type(screen.getByLabelText("Password"), "demo-password-2026"); // pragma: allowlist secret
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    await screen.findByRole("article", { name: "Write the report" });

    rejectOld(json({ detail: "Invalid or expired token", code: "invalid_token" }, 401));
    await new Promise((r) => setTimeout(r, 50));
    expect(screen.getByRole("article", { name: "Write the report" })).toBeInTheDocument();
    expect(sessionStorage.getItem(TOKEN_KEY)).toBe("token-new");
  });
});

describe("sorting", () => {
  beforeEach(loggedIn);

  const taskUrls = () =>
    vi
      .mocked(fetch)
      .mock.calls.map(([input]) => String(input))
      .filter((u) => u.startsWith("/api/v1/tasks?"));

  it("sorts by due date by default and toggles each option's direction", async () => {
    fakeApi({ ...common, "GET /api/v1/tasks": () => json(page([task()], { total: 25, pages: 3 })) });
    const user = userEvent.setup();
    renderApp("/?page=2");

    const due = await screen.findByRole("button", { name: "Due date, earliest first" });
    expect(due).toHaveAttribute("aria-pressed", "true");
    expect(taskUrls()[0]).toContain("sort=due_date");

    await user.click(screen.getByRole("button", { name: "Created" }));
    await waitFor(() => expect(taskUrls().at(-1)).toContain("sort=-created_at&page=1"));
    expect(screen.getByRole("button", { name: "Created, newest first" })).toHaveAttribute("aria-pressed", "true");

    await user.click(screen.getByRole("button", { name: "Created, newest first" }));
    await waitFor(() => expect(taskUrls().at(-1)).toContain("sort=created_at&"));

    await user.click(screen.getByRole("button", { name: "Due date" }));
    await waitFor(() => expect(taskUrls().at(-1)).toContain("sort=due_date&"));
    await user.click(screen.getByRole("button", { name: "Due date, earliest first" }));
    await waitFor(() => expect(taskUrls().at(-1)).toContain("sort=-due_date&"));
  });

  it("keeps the order when a filter changes", async () => {
    fakeApi({ ...common, "GET /api/v1/tasks": () => json(page([task()])) });
    const user = userEvent.setup();
    renderApp("/?sort=-created_at");

    await screen.findByRole("button", { name: "Created, newest first" });
    await user.selectOptions(screen.getByLabelText("Status"), "pending");

    await waitFor(() =>
      expect(taskUrls().at(-1)).toBe("/api/v1/tasks?status=pending&sort=-created_at&page=1&page_size=10"),
    );
  });

  it("ignores an unknown sort in the URL", async () => {
    fakeApi({ ...common, "GET /api/v1/tasks": () => json(page([task()])) });
    renderApp("/?sort=title");

    await screen.findByRole("article", { name: "Write the report" });
    expect(taskUrls()[0]).toContain("sort=due_date");
  });
});

describe("notifications", () => {
  beforeEach(loggedIn);

  it("confirms a created task with a notification that can be closed", async () => {
    fakeApi({
      ...common,
      "GET /api/v1/tasks": () => json(page([])),
      "POST /api/v1/tasks": () => json(task({ title: "Buy milk" }), 201),
    });
    const user = userEvent.setup();
    renderApp("/");

    await user.click(await screen.findByRole("button", { name: "+ New task" }));
    await user.type(screen.getByLabelText("Title"), "Buy milk");
    await user.click(screen.getByRole("button", { name: "Create task" }));

    const note = await screen.findByText("Task “Buy milk” created");
    expect(note.closest("[role=status]")).not.toBeNull();
    await user.click(screen.getByRole("button", { name: "Dismiss notification" }));
    await waitFor(() => expect(screen.queryByText("Task “Buy milk” created")).toBeNull());
  });

  it("confirms saved changes and deletions", async () => {
    fakeApi({
      ...common,
      "GET /api/v1/tasks": () => json(page([task()])),
      "PATCH /api/v1/tasks/10": () => json(task({ title: "Renamed" })),
      "DELETE /api/v1/tasks/10": () => new Response(null, { status: 204 }),
    });
    const user = userEvent.setup();
    renderApp("/");

    const card = await screen.findByRole("article", { name: "Write the report" });
    await user.click(within(card).getByRole("button", { name: "Edit" }));
    const title = screen.getByLabelText("Title");
    await user.clear(title);
    await user.type(title, "Renamed");
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    expect(await screen.findByText("Changes saved")).toBeInTheDocument();

    await user.click(within(card).getByRole("button", { name: "Delete" }));
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Delete" }));
    expect(await screen.findByText("Task deleted")).toBeInTheDocument();
  });

  it("does not notify when the save fails", async () => {
    fakeApi({
      ...common,
      "GET /api/v1/tasks": () => json(page([])),
      "POST /api/v1/tasks": () => json({ detail: "Title is required", code: "title_required" }, 422),
    });
    const user = userEvent.setup();
    renderApp("/");

    await user.click(await screen.findByRole("button", { name: "+ New task" }));
    await user.type(screen.getByLabelText("Title"), "x");
    await user.click(screen.getByRole("button", { name: "Create task" }));

    expect(await within(screen.getByRole("dialog")).findByRole("alert")).toHaveTextContent("Title is required");
    expect(screen.queryByText(/created$/)).toBeNull();
  });
});

describe("late delete", () => {
  beforeEach(loggedIn);

  it("a delete finishing after its dialog was cancelled does not close a new one", async () => {
    let finish: (r: Response) => void = () => {};
    fakeApi({
      ...common,
      "GET /api/v1/tasks": () => json(page([task()])),
      "DELETE /api/v1/tasks/10": () => new Promise<Response>((resolve) => (finish = resolve)),
    });
    const user = userEvent.setup();
    renderApp("/");

    const card = await screen.findByRole("article", { name: "Write the report" });
    await user.click(within(card).getByRole("button", { name: "Delete" }));
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Delete" }));
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Cancel" }));

    await user.click(screen.getByRole("button", { name: "+ New task" }));
    await user.type(screen.getByLabelText("Title"), "Draft");
    finish(new Response(null, { status: 204 }));

    expect(await screen.findByText("Task deleted")).toBeInTheDocument();
    expect(screen.getByRole("dialog", { name: "New task" })).toBeInTheDocument();
    expect(screen.getByLabelText("Title")).toHaveValue("Draft");
  });
});

describe("saving", () => {
  beforeEach(loggedIn);

  it("locks the form while a save is running", async () => {
    let finish: (r: Response) => void = () => {};
    fakeApi({
      ...common,
      "GET /api/v1/tasks": () => json(page([])),
      "POST /api/v1/tasks": () => new Promise<Response>((resolve) => (finish = resolve)),
    });
    const user = userEvent.setup();
    renderApp("/");

    await user.click(await screen.findByRole("button", { name: "+ New task" }));
    await user.type(screen.getByLabelText("Title"), "Initial title");
    await user.click(screen.getByRole("button", { name: "Create task" }));

    expect(screen.getByLabelText("Title")).toBeDisabled();
    expect(screen.getByLabelText("Description")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Saving…" })).toBeDisabled();

    finish(json(task({ title: "Initial title" }), 201));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });
});
