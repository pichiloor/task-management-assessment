import type { components, paths } from "./generated/schema";
import { request, send } from "./http";

// Every type below comes from the backend's OpenAPI document
// (`npm run gen:api`), so a contract change breaks the build, not the UI.
type Schemas = components["schemas"];
export type Task = Schemas["TaskOut"];
export type TaskPage = Schemas["TaskPage"];
export type TaskCreate = Schemas["TaskCreate"];
export type TaskUpdate = Schemas["TaskUpdate"];
export type TaskStatus = Task["status"];
export type TaskSort = Schemas["TaskSort"];
export type UserPublic = Schemas["UserPublic"];
export type UserProfile = Schemas["UserProfile"];
export type ExportJob = Schemas["ExportOut"];
export type ExportCreate = Schemas["ExportCreate"];
export type TaskQuery = NonNullable<
  paths["/api/v1/tasks"]["get"]["parameters"]["query"]
>;

export async function login(email: string, password: string): Promise<string> {
  const form = new URLSearchParams({ username: email, password });
  const body = await request<Schemas["TokenResponse"]>("/api/v1/auth/token", {
    method: "POST",
    form,
  });
  return body.access_token;
}

/** The authenticated calls, bound to one token. */
export function createApi(token: string) {
  return {
    me: () => request<UserProfile>("/api/v1/users/me", { token }),
    users: () => request<UserPublic[]>("/api/v1/users", { token }),
    listTasks: (query: TaskQuery) =>
      request<TaskPage>("/api/v1/tasks", { token, query }),
    createTask: (body: TaskCreate) =>
      request<Task>("/api/v1/tasks", { method: "POST", token, json: body }),
    updateTask: (id: number, body: TaskUpdate) =>
      request<Task>(`/api/v1/tasks/${id}`, {
        method: "PATCH",
        token,
        json: body,
      }),
    deleteTask: (id: number) =>
      request<void>(`/api/v1/tasks/${id}`, { method: "DELETE", token }),
    requestExport: (body: ExportCreate) =>
      request<ExportJob>("/api/v1/exports", {
        method: "POST",
        token,
        json: body,
      }),
    getExport: (id: number) =>
      request<ExportJob>(`/api/v1/exports/${id}`, { token }),
    /** The CSV needs the Authorization header, so a plain link cannot be
     * used: the file is fetched and handed to the browser as a Blob. */
    downloadExport: async (url: string) => {
      const response = await send(url, { token });
      return response.blob();
    },
  };
}

export type Api = ReturnType<typeof createApi>;
