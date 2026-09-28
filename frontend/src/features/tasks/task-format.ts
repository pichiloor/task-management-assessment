import type { Task, TaskStatus } from "../../api/endpoints";

export const STATUS_LABELS: Record<TaskStatus, string> = {
  pending: "Pending",
  in_progress: "In progress",
  completed: "Completed",
};

export const STATUSES = Object.keys(STATUS_LABELS) as TaskStatus[];

export function isTaskStatus(value: string | null): value is TaskStatus {
  return value !== null && value in STATUS_LABELS;
}

/** Today as YYYY-MM-DD in the user's own time zone. */
export function todayIso(now: Date = new Date()): string {
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${now.getFullYear()}-${month}-${day}`;
}

/** Due dates are calendar dates, not instants: parsed as local dates so they
 * never shift a day because of the time zone. */
export function formatDate(iso: string): string {
  const [year, month, day] = iso.split("-").map(Number);
  return new Date(year, month - 1, day).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

export function isOverdue(task: Task, today: string = todayIso()): boolean {
  return (
    task.status !== "completed" && task.due_date !== null && task.due_date < today
  );
}
