import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { TaskCreate, TaskUpdate } from "../../api/endpoints";
import { useApi } from "../auth/auth-context";

/** Every change refetches the task lists, so the page, totals and filters
 * always reflect what the server has. */
export function useTaskMutations() {
  const api = useApi();
  const queryClient = useQueryClient();
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["tasks"] });

  return {
    create: useMutation({
      mutationFn: (body: TaskCreate) => api.createTask(body),
      onSuccess: refresh,
    }),
    update: useMutation({
      mutationFn: ({ id, body }: { id: number; body: TaskUpdate }) =>
        api.updateTask(id, body),
      onSuccess: refresh,
    }),
    remove: useMutation({
      mutationFn: (id: number) => api.deleteTask(id),
      onSuccess: refresh,
    }),
  };
}
