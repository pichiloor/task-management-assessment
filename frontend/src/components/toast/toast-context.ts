import { createContext, useContext } from "react";

export type Toast = {
  /** Shows a short success message that closes by itself. */
  success: (message: string) => void;
};

export const ToastContext = createContext<Toast | null>(null);

export function useToast(): Toast {
  const value = useContext(ToastContext);
  if (!value) throw new Error("useToast must be used inside <ToastProvider>");
  return value;
}
