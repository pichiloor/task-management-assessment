import type { Task, TaskPage } from "../../src/api/endpoints";

export const ANA = { id: 1, email: "ana@example.com", name: "Ana Torres" };
export const BRUNO = { id: 2, name: "Bruno Díaz" };

export function task(overrides: Partial<Task> = {}): Task {
  return {
    id: 10,
    title: "Write the report",
    description: "",
    status: "pending",
    creator_id: ANA.id,
    assignee_id: null,
    due_date: null,
    completed_at: null,
    created_at: "2026-09-01T12:00:00Z",
    updated_at: "2026-09-01T12:00:00Z",
    ...overrides,
  };
}

export function page(items: Task[], overrides: Partial<TaskPage> = {}): TaskPage {
  return { items, total: items.length, page: 1, page_size: 10, pages: 1, ...overrides };
}
