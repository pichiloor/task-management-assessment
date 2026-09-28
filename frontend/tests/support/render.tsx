import { QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { StrictMode } from "react";
import { MemoryRouter } from "react-router-dom";
import { App } from "../../src/App";
import { ToastProvider } from "../../src/components/toast/ToastProvider";
import { AuthProvider } from "../../src/features/auth/AuthProvider";
import { createQueryClient } from "../../src/query-client";

export function renderApp(path = "/") {
  const queryClient = createQueryClient();
  queryClient.setDefaultOptions({
    queries: { ...queryClient.getDefaultOptions().queries, retry: false },
  });
  // StrictMode as in main.tsx: effects run, clean up and run again.
  return render(
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={[path]}>
          <ToastProvider>
            <AuthProvider>
              <App />
            </AuthProvider>
          </ToastProvider>
        </MemoryRouter>
      </QueryClientProvider>
    </StrictMode>,
  );
}
