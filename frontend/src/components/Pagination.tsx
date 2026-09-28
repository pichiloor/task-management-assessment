type Props = {
  page: number;
  pages: number;
  total: number;
  onChange: (page: number) => void;
};

export function Pagination({ page, pages, total, onChange }: Props) {
  if (total === 0) return null;
  return (
    <nav className="pagination" aria-label="Pagination">
      <button
        type="button"
        className="button"
        disabled={page <= 1}
        onClick={() => onChange(page - 1)}
      >
        ← Previous
      </button>
      <span>
        Page {page} of {Math.max(pages, 1)} · {total}{" "}
        {total === 1 ? "task" : "tasks"}
      </span>
      <button
        type="button"
        className="button"
        disabled={page >= pages}
        onClick={() => onChange(page + 1)}
      >
        Next →
      </button>
    </nav>
  );
}
