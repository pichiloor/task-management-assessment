import { useCallback, useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import type { TaskQuery, TaskSort, TaskStatus } from "../../api/endpoints";
import { isTaskStatus } from "./task-format";

export const PAGE_SIZE = 10;

export type TaskFilters = {
  status?: TaskStatus;
  due_from?: string;
  due_to?: string;
};

const DATE = /^\d{4}-\d{2}-\d{2}$/;

export const DEFAULT_SORT: TaskSort = "due_date";
const SORTS: readonly TaskSort[] = ["due_date", "-due_date", "created_at", "-created_at"];

function isTaskSort(value: string | null): value is TaskSort {
  return SORTS.includes(value as TaskSort);
}

/** Filters and page live in the URL, so a filtered view survives a reload
 * and can be bookmarked or shared. */
export function useTaskFilters() {
  const [params, setParams] = useSearchParams();

  const filters = useMemo<TaskFilters>(() => {
    const status = params.get("status");
    const from = params.get("due_from");
    const to = params.get("due_to");
    return {
      status: isTaskStatus(status) ? status : undefined,
      due_from: from && DATE.test(from) ? from : undefined,
      due_to: to && DATE.test(to) ? to : undefined,
    };
  }, [params]);

  const page = Math.max(1, Number.parseInt(params.get("page") ?? "1", 10) || 1);
  const rawSort = params.get("sort");
  const sort = isTaskSort(rawSort) ? rawSort : DEFAULT_SORT;

  const query = useMemo<TaskQuery>(
    () => ({ ...filters, sort, page, page_size: PAGE_SIZE }),
    [filters, sort, page],
  );

  const setFilters = useCallback(
    (next: TaskFilters) => {
      // A new filter starts again from the first page and keeps the order.
      const search = new URLSearchParams();
      for (const [key, value] of Object.entries(next)) {
        if (value) search.set(key, value);
      }
      if (sort !== DEFAULT_SORT) search.set("sort", sort);
      setParams(search);
    },
    [setParams, sort],
  );

  const setSort = useCallback(
    (next: TaskSort) => {
      // A new order starts again from the first page and keeps the filters.
      setParams((current) => {
        const search = new URLSearchParams(current);
        search.delete("page");
        if (next === DEFAULT_SORT) search.delete("sort");
        else search.set("sort", next);
        return search;
      });
    },
    [setParams],
  );

  const setPage = useCallback(
    (nextPage: number) => {
      setParams((current) => {
        const search = new URLSearchParams(current);
        if (nextPage > 1) search.set("page", String(nextPage));
        else search.delete("page");
        return search;
      });
    },
    [setParams],
  );

  return { filters, sort, page, query, setFilters, setSort, setPage };
}
