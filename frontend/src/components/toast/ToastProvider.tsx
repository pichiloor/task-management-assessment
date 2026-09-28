import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { CheckIcon } from "../icons";
import { ToastContext, type Toast } from "./toast-context";

const VISIBLE_MS = 4000;

type Item = { id: number; message: string };

/** Success notifications in the top corner. The region is always in the
 * page and polite, so screen readers announce each message without moving
 * the focus; each one closes after 4 s or with its close button. */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Item[]>([]);
  const nextId = useRef(1);
  const timers = useRef(new Map<number, number>());

  const dismiss = useCallback((id: number) => {
    window.clearTimeout(timers.current.get(id));
    timers.current.delete(id);
    setItems((current) => current.filter((item) => item.id !== id));
  }, []);

  const success = useCallback(
    (message: string) => {
      const id = nextId.current++;
      setItems((current) => [...current, { id, message }]);
      timers.current.set(id, window.setTimeout(() => dismiss(id), VISIBLE_MS));
    },
    [dismiss],
  );

  useEffect(() => {
    const pending = timers.current;
    return () => pending.forEach((timer) => window.clearTimeout(timer));
  }, []);

  const value = useMemo<Toast>(() => ({ success }), [success]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="toast-region" role="status" aria-live="polite">
        {items.map((item) => (
          <div key={item.id} className="toast">
            <span className="toast-icon">
              <CheckIcon />
            </span>
            <span className="toast-message">{item.message}</span>
            <button
              type="button"
              className="toast-close"
              aria-label="Dismiss notification"
              onClick={() => dismiss(item.id)}
            >
              ×
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}
