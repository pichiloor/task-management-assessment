import type { Task, TaskStatus } from "../../api/endpoints";
import {
  STATUSES,
  STATUS_LABELS,
  formatDate,
  formatInstant,
  isOverdue,
} from "./task-format";

type Props = {
  task: Task;
  currentUserId: number;
  userNames: Map<number, string>;
  busy: boolean;
  onStatusChange: (task: Task, status: TaskStatus) => void;
  onEdit: (task: Task) => void;
  onDelete: (task: Task) => void;
};

/** The backend decides permissions; the card only hides what would be
 * refused: the creator edits and deletes, the assignee changes the status. */
export function TaskCard({
  task,
  currentUserId,
  userNames,
  busy,
  onStatusChange,
  onEdit,
  onDelete,
}: Props) {
  const isCreator = task.creator_id === currentUserId;
  const overdue = isOverdue(task);
  const nameOf = (id: number) =>
    id === currentUserId ? "you" : (userNames.get(id) ?? `user #${id}`);

  return (
    <article className={`task-card status-${task.status}`} aria-label={task.title}>
      <header className="task-card-header">
        <h3>{task.title}</h3>
        <span className={`badge badge-${task.status}`}>
          {STATUS_LABELS[task.status]}
        </span>
      </header>
      {task.description && <p className="task-description">{task.description}</p>}
      <dl className="task-meta">
        <div>
          <dt>Due</dt>
          <dd className={overdue ? "overdue" : undefined}>
            {task.due_date ? formatDate(task.due_date) : "No due date"}
            {overdue && " · overdue"}
          </dd>
        </div>
        <div>
          <dt>Assignee</dt>
          <dd>{task.assignee_id === null ? "Unassigned" : nameOf(task.assignee_id)}</dd>
        </div>
        <div>
          <dt>Created by</dt>
          <dd>
            {nameOf(task.creator_id)} · {formatInstant(task.created_at)}
          </dd>
        </div>
      </dl>
      <footer className="task-actions">
        <label className="inline-field">
          <span className="visually-hidden">Status of {task.title}</span>
          <select
            value={task.status}
            disabled={busy}
            onChange={(e) => onStatusChange(task, e.target.value as TaskStatus)}
          >
            {STATUSES.map((status) => (
              <option key={status} value={status}>
                {STATUS_LABELS[status]}
              </option>
            ))}
          </select>
        </label>
        {task.status !== "completed" && (
          <button
            type="button"
            className="button"
            disabled={busy}
            onClick={() => onStatusChange(task, "completed")}
          >
            Complete
          </button>
        )}
        {isCreator && (
          <>
            <button type="button" className="button" onClick={() => onEdit(task)}>
              Edit
            </button>
            <button
              type="button"
              className="button danger-outline"
              onClick={() => onDelete(task)}
            >
              Delete
            </button>
          </>
        )}
      </footer>
    </article>
  );
}
