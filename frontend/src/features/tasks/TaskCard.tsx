import type { Task, TaskStatus } from "../../api/endpoints";
import { CheckIcon, PencilIcon, TrashIcon } from "../../components/icons";
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
  const completed = task.status === "completed";
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
        <div className="icon-actions">
          {/* Toggle: completes the task, or reopens it as pending. */}
          <button
            type="button"
            className={`icon-action check${completed ? " done" : ""}`}
            aria-pressed={completed}
            aria-label={completed ? "Mark as not completed" : "Mark as completed"}
            title={completed ? "Mark as not completed" : "Mark as completed"}
            disabled={busy}
            onClick={() => onStatusChange(task, completed ? "pending" : "completed")}
          >
            <CheckIcon />
          </button>
          {isCreator && (
            <>
              <button
                type="button"
                className="icon-action"
                aria-label="Edit"
                title="Edit"
                onClick={() => onEdit(task)}
              >
                <PencilIcon />
              </button>
              <button
                type="button"
                className="icon-action danger"
                aria-label="Delete"
                title="Delete"
                onClick={() => onDelete(task)}
              >
                <TrashIcon />
              </button>
            </>
          )}
        </div>
      </footer>
    </article>
  );
}
