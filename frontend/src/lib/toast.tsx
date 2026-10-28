import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import { LuCircleAlert, LuCircleCheck, LuX } from "react-icons/lu";

type Tone = "success" | "error" | "info";
interface ToastItem {
  id: number;
  tone: Tone;
  text: string;
}
interface ToastApi {
  push: (text: string, tone?: Tone) => void;
}

const ToastContext = createContext<ToastApi>({ push: () => undefined });

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const dismiss = useCallback((id: number) => setItems((xs) => xs.filter((x) => x.id !== id)), []);
  const push = useCallback((text: string, tone: Tone = "success") => {
    const id = Date.now() + Math.random();
    setItems((xs) => [...xs.slice(-3), { id, tone, text }]);
    window.setTimeout(() => dismiss(id), tone === "error" ? 9000 : 5000);
  }, [dismiss]);
  const api = useMemo(() => ({ push }), [push]);
  return (
    <ToastContext.Provider value={api}>
      {children}
      <div className="pointer-events-none fixed right-4 bottom-4 z-50 flex w-[min(92vw,380px)] flex-col gap-2 print:hidden"
        role="status" aria-live="polite">
        {items.map((t) => (
          <div key={t.id}
            className={`pointer-events-auto flex items-start gap-2 rounded-lg border bg-white px-3 py-2.5 text-sm shadow-lg ${
              t.tone === "error" ? "border-red/50" : t.tone === "success" ? "border-green/50" : "border-line"}`}>
            {t.tone === "error" ? <LuCircleAlert className="mt-0.5 shrink-0 text-red-ink" aria-hidden />
              : <LuCircleCheck className={`mt-0.5 shrink-0 ${t.tone === "success" ? "text-green-ink" : "text-blue-ink"}`} aria-hidden />}
            <p className="flex-1 text-ink">{t.text}</p>
            <button type="button" onClick={() => dismiss(t.id)} className="text-muted hover:text-ink" aria-label="Dismiss message">
              <LuX aria-hidden />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export const useToast = () => useContext(ToastContext);
