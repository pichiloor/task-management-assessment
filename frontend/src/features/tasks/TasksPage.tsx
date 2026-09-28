import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import type { Task, TaskStatus } from "../../api/endpoints";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { Pagination } from "../../components/Pagination";
import { useApi, useAuth } from "../auth/auth-context";
import { ExportPanel } from "../exports/ExportPanel";
import { FilterBar } from "./FilterBar";
import { TaskCard } from "./TaskCard";
import { TaskFormDialog } from "./TaskFormDialog";
import { useTaskFilters } from "./use-task-filters";
import { useTaskMutations } from "./use-task-mutations";

type Dialog =
  | { kind: "create" }
  | { kind: "edit"; task: Task }
  | { kind: "delete"; task: Task }
  | null;

export function TasksPage() {
  const api = useApi();
  const { user, logout } = useAuth();
  const { filters, page, query, setFilters, setPage } = useTaskFilters();
  const [dialog, setDialog] = useState<Dialog>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const { update, remove } = useTaskMutations();

  const invalidRange =
    filters.due_from !== undefined &&
    filters.due_to !== undefined &&
    filters.due_from > filters.due_to;

  const tasks = useQuery({
    queryKey: ["tasks", query],
    queryFn: () => api.listTasks(query),
    enabled: !invalidRange,
    // Keeps the current page on screen while the next one loads.
    placeholderData: keepPreviousData,
  });
  const users = useQuery({ queryKey: ["users"], queryFn: () => api.users() });
  const userNames = useMemo(
    () => new Map((users.data ?? []).map((u) => [u.id, u.name])),
    [users.data],
  );

  // Deleting the last task of the last page would leave an empty page.
  const data = tasks.data;
  useEffect(() => {
    if (data && data.items.length === 0 && data.total > 0 && page > data.pages) {
      setPage(data.pages);
    }
  }, [data, page, setPage]);

  function changeStatus(task: Task, status: TaskStatus) {
    setActionError(null);
    update.mutate(
      { id: task.id, body: { status } },
      { onError: (err) => setActionError(err.message) },
    );
  }

  function confirmDelete(task: Task) {
    remove.mutate(task.id, { onSuccess: () => setDialog(null) });
  }

  if (!user) return null;

  return (
    <div className="layout">
      <header className="topbar">
        <h1>Task Manager</h1>
        <div className="topbar-user">
          <span>
            {user.name} <span className="muted">({user.email})</span>
          </span>
          <button type="button" className="button" onClick={logout}>
            Log out
          </button>
        </div>
      </header>

      <main className="content">
        <div className="toolbar">
          <h2>My tasks</h2>
          <button
            type="button"
            className="button primary"
            onClick={() => setDialog({ kind: "create" })}
          >
            + New task
          </button>
        </div>
        <p className="muted">Tasks you created or that are assigned to you.</p>

        <FilterBar filters={filters} onChange={setFilters} />
        {/* Keyed by the filters: a finished export for other filters is not
            offered as if it matched the list on screen. */}
        <ExportPanel
          key={JSON.stringify(filters)}
          filters={filters}
          disabled={invalidRange}
        />

        {actionError && (
          <p className="error" role="alert">
            {actionError}
          </p>
        )}

        {tasks.isPending && !invalidRange && <p className="page-status">Loading tasks…</p>}
        {tasks.isError && (
          <div className="error" role="alert">
            <p>{tasks.error.message}</p>
            <button type="button" className="button" onClick={() => tasks.refetch()}>
              Retry
            </button>
          </div>
        )}
        {data && !invalidRange && (
          <>
            {data.items.length === 0 ? (
              <p className="empty">
                {filters.status || filters.due_from || filters.due_to
                  ? "No tasks match these filters."
                  : "No tasks yet. Create the first one."}
              </p>
            ) : (
              <ul className="task-list" aria-busy={tasks.isFetching}>
                {data.items.map((task) => (
                  <li key={task.id}>
                    <TaskCard
                      task={task}
                      currentUserId={user.id}
                      userNames={userNames}
                      busy={update.isPending && update.variables?.id === task.id}
                      onStatusChange={changeStatus}
                      onEdit={(t) => setDialog({ kind: "edit", task: t })}
                      onDelete={(t) => {
                        remove.reset();
                        setDialog({ kind: "delete", task: t });
                      }}
                    />
                  </li>
                ))}
              </ul>
            )}
            <Pagination
              page={data.page}
              pages={data.pages}
              total={data.total}
              onChange={setPage}
            />
          </>
        )}
      </main>

      {dialog?.kind === "create" && (
        <TaskFormDialog users={users.data ?? []} onClose={() => setDialog(null)} />
      )}
      {dialog?.kind === "edit" && (
        <TaskFormDialog
          task={dialog.task}
          users={users.data ?? []}
          onClose={() => setDialog(null)}
        />
      )}
      {dialog?.kind === "delete" && (
        <ConfirmDialog
          title="Delete task"
          message={`Delete “${dialog.task.title}”? This cannot be undone.`}
          confirmLabel="Delete"
          busy={remove.isPending}
          error={remove.error?.message ?? null}
          onConfirm={() => confirmDelete(dialog.task)}
          onCancel={() => setDialog(null)}
        />
      )}
    </div>
  );
}
