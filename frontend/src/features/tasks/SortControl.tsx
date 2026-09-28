import type { TaskSort } from "../../api/endpoints";

type Field = "due_date" | "created_at";
type Direction = "asc" | "desc";

const OPTIONS: {
  field: Field;
  label: string;
  /** Direction used when the option is first selected. */
  first: Direction;
  asc: string;
  desc: string;
}[] = [
  {
    field: "due_date",
    label: "Due date",
    first: "asc",
    asc: "earliest first",
    desc: "latest first",
  },
  {
    field: "created_at",
    label: "Created",
    first: "desc",
    asc: "oldest first",
    desc: "newest first",
  },
];

function toSort(field: Field, direction: Direction): TaskSort {
  return (direction === "desc" ? `-${field}` : field) as TaskSort;
}

type Props = {
  sort: TaskSort;
  onChange: (sort: TaskSort) => void;
};

/** Two toggle buttons: choosing one sorts by it in its natural direction
 * (soonest due, newest created); pressing the active one again reverses it. */
export function SortControl({ sort, onChange }: Props) {
  const activeField = sort.replace(/^-/, "") as Field;
  const activeDirection: Direction = sort.startsWith("-") ? "desc" : "asc";

  return (
    <div className="sort-control" role="group" aria-label="Sort tasks">
      <span className="muted small" aria-hidden="true">
        Sort:
      </span>
      <div className="segmented">
        {OPTIONS.map((option) => {
          const active = option.field === activeField;
          const direction = active ? activeDirection : option.first;
          const reversed: Direction = direction === "asc" ? "desc" : "asc";
          const label = option.label.toLowerCase();
          return (
            <button
              key={option.field}
              type="button"
              className={`sort-button${active ? " active" : ""}`}
              aria-pressed={active}
              title={
                active
                  ? `Sorted by ${label}, ${option[direction]}. Click to reverse.`
                  : `Sort by ${label}, ${option[option.first]}`
              }
              onClick={() =>
                onChange(toSort(option.field, active ? reversed : option.first))
              }
            >
              {option.label}
              {active && (
                <>
                  <span aria-hidden="true">{direction === "asc" ? " ↑" : " ↓"}</span>
                  <span className="visually-hidden">, {option[direction]}</span>
                </>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}
