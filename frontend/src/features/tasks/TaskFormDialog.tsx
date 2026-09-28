import { useEffect, useRef, useState, type FormEvent } from "react";
import { Field } from "../../components/Field";
import type { Task, TaskCreate, TaskStatus, UserPublic } from "../../api/endpoints";
import { Modal } from "../../components/Modal";
import { useToast } from "../../components/toast/toast-context";
import { STATUSES, STATUS_LABELS } from "./task-format";
import {
  DESCRIPTION_MAX_LENGTH,
  TITLE_MAX_LENGTH,
  changedFields,
  initialValues,
  type Values,
} from "./task-form";
import { useTaskMutations } from "./use-task-mutations";

type Props = {
  /** Absent to create a new task. */
  task?: Task;
  users: UserPublic[];
  onClose: () => void;
};

export function TaskFormDialog({ task, users, onClose }: Props) {
  const [values, setValues] = useState<Values>(() => initialValues(task));
  const [error, setError] = useState<string | null>(null);
  const { create, update } = useTaskMutations();
  const toast = useToast();
  const saving = create.isPending || update.isPending;
  // A save can finish after this dialog was cancelled; closing then would
  // close whichever dialog is open by that time.
  const open = useRef(true);
  useEffect(() => {
    // Set again on setup: StrictMode runs cleanup and setup once more.
    open.current = true;
    return () => {
      open.current = false;
    };
  }, []);
  const editing = task !== undefined;

  function set<K extends keyof Values>(key: K, value: Values[K]) {
    setValues((current) => ({ ...current, [key]: value }));
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    const title = values.title.trim();
    if (!title) {
      setError("Title is required.");
      return;
    }
    try {
      if (task) {
        const body = changedFields(task, values);
        if (Object.keys(body).length > 0) {
          await update.mutateAsync({ id: task.id, body });
          toast.success("Changes saved");
        }
      } else {
        const body: TaskCreate = {
          title,
          description: values.description,
          assignee_id: values.assignee ? Number(values.assignee) : null,
          due_date: values.dueDate || null,
        };
        await create.mutateAsync(body);
        toast.success(`Task “${title}” created`);
      }
      if (open.current) onClose();
    } catch (err) {
      if (!open.current) return;
      setError(err instanceof Error ? err.message : "Could not save the task.");
    }
  }

  return (
    <Modal title={editing ? "Edit task" : "New task"} onClose={onClose}>
      <form className="task-form" onSubmit={handleSubmit} noValidate>
        {/* Locked while saving: edits made during the request would be
            lost when the dialog closes on success. */}
        <fieldset className="form-fields" disabled={saving}>
          <Field label="Title">
            {(id) => (
              <input
                id={id}
                value={values.title}
                maxLength={TITLE_MAX_LENGTH}
                onChange={(e) => set("title", e.target.value)}
                required
              />
            )}
          </Field>
          <Field label="Description">
            {(id) => (
              <textarea
                id={id}
                rows={4}
                value={values.description}
                maxLength={DESCRIPTION_MAX_LENGTH}
                onChange={(e) => set("description", e.target.value)}
              />
            )}
          </Field>
          <div className="form-row">
            <Field label="Assignee">
              {(id) => (
                <select
                  id={id}
                  value={values.assignee}
                  onChange={(e) => set("assignee", e.target.value)}
                >
                  <option value="">Unassigned</option>
                  {users.map((user) => (
                    <option key={user.id} value={user.id}>
                      {user.name}
                    </option>
                  ))}
                </select>
              )}
            </Field>
            <Field label="Due date">
              {(id) => (
                <input
                  id={id}
                  type="date"
                  value={values.dueDate}
                  onChange={(e) => set("dueDate", e.target.value)}
                />
              )}
            </Field>
            {editing && (
              <Field label="Status">
                {(id) => (
                  <select
                    id={id}
                    value={values.status}
                    onChange={(e) => set("status", e.target.value as TaskStatus)}
                  >
                    {STATUSES.map((status) => (
                      <option key={status} value={status}>
                        {STATUS_LABELS[status]}
                      </option>
                    ))}
                  </select>
                )}
              </Field>
            )}
          </div>
        </fieldset>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <div className="modal-actions">
          <button type="button" className="button" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="button primary" disabled={saving}>
            {saving ? "Saving…" : editing ? "Save changes" : "Create task"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
