import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";

// In-site replacements for window.confirm / window.alert, plus short status toasts.
//   const { confirm, notify, toast } = useDialog();
//   if (await confirm({ title, body, confirmLabel })) ...

interface DialogOptions {
  title: string;
  body?: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  tone?: "default" | "warning";
}
interface DialogApi {
  confirm: (o: DialogOptions) => Promise<boolean>;
  notify: (o: DialogOptions) => Promise<void>;
  toast: (text: string, tone?: "info" | "success" | "error") => void;
}

const Ctx = createContext<DialogApi | null>(null);

export function useDialog(): DialogApi {
  const api = useContext(Ctx);
  if (!api) throw new Error("useDialog must be used inside <DialogProvider>");
  return api;
}

interface Open extends DialogOptions { kind: "confirm" | "notify"; resolve: (ok: boolean) => void; }
interface Toast { id: number; text: string; tone: "info" | "success" | "error"; }

export function DialogProvider({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState<Open | null>(null);
  const [toasts, setToasts] = useState<Toast[]>([]);

  const confirm = useCallback((o: DialogOptions) =>
    new Promise<boolean>((resolve) => setOpen({ ...o, kind: "confirm", resolve })), []);
  const notify = useCallback((o: DialogOptions) =>
    new Promise<void>((resolve) => setOpen({ ...o, kind: "notify", resolve: () => resolve() })), []);
  const toast = useCallback((text: string, tone: Toast["tone"] = "info") => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, text, tone }]);
    window.setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 7000);
  }, []);

  const close = (ok: boolean) => { open?.resolve(ok); setOpen(null); };

  return (
    <Ctx.Provider value={{ confirm, notify, toast }}>
      {children}
      {open && <DialogBox o={open} onClose={close} />}
      <div className="toasts" role="status" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={`toast toast-${t.tone}`}>
            <span>{t.text}</span>
            <button className="toast-x" aria-label="Dismiss" onClick={() => setToasts((all) => all.filter((x) => x.id !== t.id))}>×</button>
          </div>
        ))}
      </div>
    </Ctx.Provider>
  );
}

function DialogBox({ o, onClose }: { o: Open; onClose: (ok: boolean) => void }) {
  const primary = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    primary.current?.focus();
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(false); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <>
      <div className="dialog-scrim" onClick={() => onClose(false)} />
      <div className={`dialog${o.tone === "warning" ? " dialog-warning" : ""}`} role="alertdialog" aria-modal="true" aria-labelledby="dialog-title">
        <h2 id="dialog-title">{o.title}</h2>
        {o.body && <div className="dialog-body">{o.body}</div>}
        <div className="dialog-actions">
          {o.kind === "confirm" && (
            <button className="btn-ghost" onClick={() => onClose(false)}>{o.cancelLabel ?? "Cancel"}</button>
          )}
          <button ref={primary} className="btn" onClick={() => onClose(true)}>
            {o.confirmLabel ?? (o.kind === "confirm" ? "Continue" : "OK")}
          </button>
        </div>
      </div>
    </>
  );
}
