import { QueryClient } from "@tanstack/react-query";
import { ApiError } from "./api/http";

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        refetchOnWindowFocus: false,
        // Retrying a 4xx (bad filter, expired token, rate limit) only repeats
        // the same answer; network and server errors get one more try.
        retry: (failures, error) =>
          failures < 1 && !(error instanceof ApiError && error.status >= 400 && error.status < 500),
      },
    },
  });
}
