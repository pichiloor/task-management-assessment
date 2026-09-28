import { describe, expect, it } from "vitest";
import { changedFields, initialValues } from "../src/features/tasks/task-form";
import { formatDate, isOverdue, todayIso } from "../src/features/tasks/task-format";
import { task } from "./support/data";

describe("changedFields", () => {
  const original = task({ title: "A", assignee_id: 2, due_date: "2026-10-01" });

  it("is empty when nothing changed", () => {
    expect(changedFields(original, initialValues(original))).toEqual({});
  });

  it("sends only what changed, trimming the title", () => {
    const values = { ...initialValues(original), title: "  B  ", status: "completed" as const };
    expect(changedFields(original, values)).toEqual({ title: "B", status: "completed" });
  });

  it("sends null to clear the assignee and the due date", () => {
    const values = { ...initialValues(original), assignee: "", dueDate: "" };
    expect(changedFields(original, values)).toEqual({ assignee_id: null, due_date: null });
  });
});

describe("dates", () => {
  it("formats a calendar date without shifting the day", () => {
    expect(formatDate("2026-01-01")).toContain("2026");
    expect(formatDate("2026-01-01")).toMatch(/\b1\b/);
  });

  it("builds today from local time", () => {
    expect(todayIso(new Date(2026, 8, 5, 23, 30))).toBe("2026-09-05");
  });

  it("marks only unfinished tasks past their due date as overdue", () => {
    const today = "2026-09-28";
    expect(isOverdue(task({ due_date: "2026-09-27" }), today)).toBe(true);
    expect(isOverdue(task({ due_date: "2026-09-28" }), today)).toBe(false);
    expect(isOverdue(task({ due_date: "2026-09-27", status: "completed" }), today)).toBe(false);
    expect(isOverdue(task({ due_date: null }), today)).toBe(false);
  });
});
