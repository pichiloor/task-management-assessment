import type { Task, TaskStatus, TaskUpdate } from "../../api/endpoints";

// Same limits as the backend (app/domain/task.py); the server still checks.
export const TITLE_MAX_LENGTH = 200;
export const DESCRIPTION_MAX_LENGTH = 2000;

export type Values = {
  title: string;
  description: string;
  assignee: string;
  dueDate: string;
  status: TaskStatus;
};

export function initialValues(task?: Task): Values {
  return {
    title: task?.title ?? "",
    description: task?.description ?? "",
    assignee: task?.assignee_id != null ? String(task.assignee_id) : "",
    dueDate: task?.due_date ?? "",
    status: task?.status ?? "pending",
  };
}

/** Only what changed is sent, so a PATCH never overwrites fields the user
 * did not touch. */
export function changedFields(task: Task, values: Values): TaskUpdate {
  const body: TaskUpdate = {};
  const title = values.title.trim();
  const assignee = values.assignee ? Number(values.assignee) : null;
  const due = values.dueDate || null;
  if (title !== task.title) body.title = title;
  if (values.description !== task.description) body.description = values.description;
  if (values.status !== task.status) body.status = values.status;
  if (assignee !== task.assignee_id) body.assignee_id = assignee;
  if (due !== task.due_date) body.due_date = due;
  return body;
}
