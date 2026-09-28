import type { TaskStatus } from "../../api/endpoints";
import { Field } from "../../components/Field";
import { STATUSES, STATUS_LABELS } from "./task-format";
import type { TaskFilters } from "./use-task-filters";

type Props = {
  filters: TaskFilters;
  onChange: (filters: TaskFilters) => void;
};

export function FilterBar({ filters, onChange }: Props) {
  const invalidRange =
    filters.due_from !== undefined &&
    filters.due_to !== undefined &&
    filters.due_from > filters.due_to;
  const active = Boolean(filters.status || filters.due_from || filters.due_to);

  return (
    <section className="filters" aria-label="Filters">
      <Field label="Status">
        {(id) => (
          <select
            id={id}
            value={filters.status ?? ""}
            onChange={(e) =>
              onChange({
                ...filters,
                status: (e.target.value || undefined) as TaskStatus | undefined,
              })
            }
          >
            <option value="">All</option>
            {STATUSES.map((status) => (
              <option key={status} value={status}>
                {STATUS_LABELS[status]}
              </option>
            ))}
          </select>
        )}
      </Field>
      <Field label="Due from">
        {(id) => (
          <input
            id={id}
            type="date"
            value={filters.due_from ?? ""}
            max={filters.due_to}
            onChange={(e) =>
              onChange({ ...filters, due_from: e.target.value || undefined })
            }
          />
        )}
      </Field>
      <Field label="Due to">
        {(id) => (
          <input
            id={id}
            type="date"
            value={filters.due_to ?? ""}
            min={filters.due_from}
            onChange={(e) =>
              onChange({ ...filters, due_to: e.target.value || undefined })
            }
          />
        )}
      </Field>
      {active && (
        <button type="button" className="button link" onClick={() => onChange({})}>
          Clear filters
        </button>
      )}
      {invalidRange && (
        <p className="error" role="alert">
          “Due from” must not be after “Due to”.
        </p>
      )}
    </section>
  );
}
