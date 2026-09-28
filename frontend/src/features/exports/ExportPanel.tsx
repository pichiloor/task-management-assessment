import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import type { ExportJob } from "../../api/endpoints";
import { useApi } from "../auth/auth-context";
import type { TaskFilters } from "../tasks/use-task-filters";
import { saveBlob } from "./save-blob";

const POLL_MS = 1500;

type Props = {
  filters: TaskFilters;
  disabled: boolean;
};

/** Requests a CSV of the tasks matching the current filters. The file is
 * built by the Celery worker: the panel polls the job until it finishes,
 * then downloads it with the bearer token. */
export function ExportPanel({ filters, disabled }: Props) {
  const api = useApi();
  const queryClient = useQueryClient();
  const [exportId, setExportId] = useState<number | null>(null);

  const start = useMutation({
    mutationFn: () => api.requestExport({ ...filters }),
    onSuccess: (job) => {
      // Seeds the job query with the accepted (pending) job, so polling
      // keeps going even if a status request fails along the way.
      queryClient.setQueryData(["export", job.id], job);
      setExportId(job.id);
    },
  });

  const job = useQuery({
    queryKey: ["export", exportId],
    queryFn: () => api.getExport(exportId!),
    enabled: exportId !== null,
    refetchInterval: (query) =>
      query.state.data?.status === "pending" ? POLL_MS : false,
  });

  const download = useMutation({
    mutationFn: async (done: ExportJob) => {
      const blob = await api.downloadExport(done.download_url!);
      saveBlob(blob, `tasks-export-${done.id}.csv`);
    },
  });

  const current = job.data;
  const running = start.isPending || current?.status === "pending";
  // A failed poll is only worth showing once the job has stopped polling.
  const error = start.error ?? (running ? null : job.error) ?? download.error;

  return (
    <section className="export-panel" aria-label="CSV export">
      <button
        type="button"
        className="button"
        disabled={disabled || running}
        onClick={() => {
          download.reset();
          start.mutate();
        }}
      >
        {running ? "Preparing CSV…" : "Export CSV"}
      </button>
      <span className="muted small">Uses the filters above.</span>
      <div aria-live="polite" className="export-status">
        {current?.status === "completed" && (
          <>
            <span>
              Ready: {current.row_count} {current.row_count === 1 ? "row" : "rows"}.
            </span>
            <button
              type="button"
              className="button link"
              disabled={download.isPending}
              onClick={() => download.mutate(current)}
            >
              {download.isPending ? "Downloading…" : "Download"}
            </button>
          </>
        )}
        {current?.status === "failed" && (
          <span className="error">The export failed. Try again.</span>
        )}
        {error && <span className="error">{error.message}</span>}
      </div>
    </section>
  );
}
