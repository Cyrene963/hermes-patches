import React, { createContext, useCallback, useContext, useMemo, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { AlertTriangle, CheckCircle2, Info, Loader2, X, XCircle } from 'lucide-react';
import clsx from 'clsx';

export const pageMotion = {
  initial: { opacity: 0, y: 12, filter: 'blur(6px)' },
  animate: { opacity: 1, y: 0, filter: 'blur(0px)' },
  exit: { opacity: 0, y: 8, filter: 'blur(4px)' },
  transition: { duration: 0.22, ease: [0.22, 1, 0.36, 1] },
};

export const panelMotion = {
  initial: { opacity: 0, y: 10, scale: 0.98 },
  animate: { opacity: 1, y: 0, scale: 1 },
  exit: { opacity: 0, y: 8, scale: 0.98 },
  transition: { duration: 0.18, ease: [0.22, 1, 0.36, 1] },
};

export const staggerContainer = {
  animate: { transition: { staggerChildren: 0.035 } },
};

export const staggerItem = {
  initial: { opacity: 0, y: 8 },
  animate: { opacity: 1, y: 0 },
};

const ToastContext = createContext(null);
const ConfirmContext = createContext(null);

const toastIcons = {
  success: CheckCircle2,
  error: XCircle,
  warning: AlertTriangle,
  info: Info,
};

const toastStyles = {
  success: 'border-emerald-400/25 bg-emerald-500/10 text-emerald-100',
  error: 'border-rose-400/25 bg-rose-500/10 text-rose-100',
  warning: 'border-amber-400/25 bg-amber-500/10 text-amber-100',
  info: 'border-indigo-400/25 bg-indigo-500/10 text-indigo-100',
};

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);

  const removeToast = useCallback((id) => {
    setToasts(current => current.filter(toast => toast.id !== id));
  }, []);

  const notify = useCallback((message, options = {}) => {
    const id = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
    const toast = {
      id,
      message,
      type: options.type || 'info',
      title: options.title,
    };
    setToasts(current => [...current.slice(-3), toast]);
    window.setTimeout(() => removeToast(id), options.duration ?? 4200);
    return id;
  }, [removeToast]);

  const value = useMemo(() => ({
    notify,
    success: (message, options) => notify(message, { ...options, type: 'success' }),
    error: (message, options) => notify(message, { ...options, type: 'error' }),
    warning: (message, options) => notify(message, { ...options, type: 'warning' }),
    info: (message, options) => notify(message, { ...options, type: 'info' }),
  }), [notify]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="pointer-events-none fixed right-4 top-4 z-[80] flex w-[min(92vw,420px)] flex-col gap-3" role="status" aria-live="polite">
        <AnimatePresence>
          {toasts.map(toast => {
            const Icon = toastIcons[toast.type] || Info;
            return (
              <motion.div
                key={toast.id}
                layout
                initial={{ opacity: 0, x: 40, scale: 0.96 }}
                animate={{ opacity: 1, x: 0, scale: 1 }}
                exit={{ opacity: 0, x: 40, scale: 0.96 }}
                transition={{ type: 'spring', stiffness: 520, damping: 34 }}
                className={clsx('pointer-events-auto rounded-2xl border p-4 shadow-2xl shadow-black/30 backdrop-blur-2xl', toastStyles[toast.type])}
              >
                <div className="flex gap-3">
                  <Icon className="mt-0.5 h-5 w-5 shrink-0" />
                  <div className="min-w-0 flex-1">
                    {toast.title && <div className="mb-1 text-sm font-semibold text-white">{toast.title}</div>}
                    <div className="text-sm leading-5 text-current/90">{toast.message}</div>
                  </div>
                  <button
                    type="button"
                    onClick={() => removeToast(toast.id)}
                    className="rounded-lg p-1 text-current/60 transition hover:bg-white/10 hover:text-white"
                    aria-label="Dismiss notification"
                  >
                    <X className="h-4 w-4" />
                  </button>
                </div>
              </motion.div>
            );
          })}
        </AnimatePresence>
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error('useToast must be used inside ToastProvider');
  return ctx;
}

export function ConfirmProvider({ children }) {
  const [request, setRequest] = useState(null);

  const confirm = useCallback((options) => new Promise(resolve => {
    setRequest({
      title: options.title || 'Confirm action',
      description: options.description || '',
      details: options.details || [],
      confirmLabel: options.confirmLabel || 'Confirm',
      cancelLabel: options.cancelLabel || 'Cancel',
      variant: options.variant || 'default',
      requireText: options.requireText || '',
      resolve,
    });
  }), []);

  const close = useCallback((result) => {
    setRequest(current => {
      current?.resolve(result);
      return null;
    });
  }, []);

  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      <AnimatePresence>
        {request && <ConfirmDialog request={request} onClose={close} />}
      </AnimatePresence>
    </ConfirmContext.Provider>
  );
}

function ConfirmDialog({ request, onClose }) {
  const [input, setInput] = useState('');
  const dangerous = request.variant === 'danger';
  const canConfirm = !request.requireText || input === request.requireText;

  return (
    <motion.div
      className="fixed inset-0 z-[70] flex items-center justify-center bg-black/60 p-4 backdrop-blur-md"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      onClick={() => onClose(false)}
    >
      <motion.div
        role="dialog"
        aria-modal="true"
        aria-labelledby="confirm-title"
        aria-describedby="confirm-description"
        className="w-full max-w-lg rounded-3xl border border-white/10 bg-slate-950/95 p-6 shadow-2xl shadow-black/50"
        initial={{ opacity: 0, y: 24, scale: 0.96 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={{ opacity: 0, y: 16, scale: 0.96 }}
        transition={{ type: 'spring', stiffness: 420, damping: 32 }}
        onClick={event => event.stopPropagation()}
      >
        <div className="flex items-start gap-4">
          <div className={clsx('flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl border', dangerous ? 'border-rose-400/30 bg-rose-500/10 text-rose-200' : 'border-indigo-400/30 bg-indigo-500/10 text-indigo-200')}>
            <AlertTriangle className="h-5 w-5" />
          </div>
          <div className="min-w-0 flex-1">
            <h2 id="confirm-title" className="text-lg font-semibold text-white">{request.title}</h2>
            {request.description && (
              <p id="confirm-description" className="mt-2 text-sm leading-6 text-slate-300">{request.description}</p>
            )}
          </div>
        </div>

        {request.details?.length > 0 && (
          <div className="mt-5 rounded-2xl border border-white/10 bg-white/[0.04] p-4">
            <div className="space-y-2 text-sm text-slate-300">
              {request.details.map((item, index) => (
                <div key={index} className="flex gap-2">
                  <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-indigo-300/70" />
                  <span>{item}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {request.requireText && (
          <label className="mt-5 block text-sm text-slate-300">
            Type <span className="font-mono text-rose-200">{request.requireText}</span> to continue
            <input
              autoFocus
              value={input}
              onChange={event => setInput(event.target.value)}
              className="mt-2 w-full rounded-xl border border-white/10 bg-slate-900 px-3 py-2 text-sm text-white outline-none transition focus:border-rose-300/70 focus:ring-2 focus:ring-rose-500/20"
            />
          </label>
        )}

        <div className="mt-6 flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
          <button
            type="button"
            onClick={() => onClose(false)}
            className="rounded-xl border border-white/10 px-4 py-2 text-sm font-semibold text-slate-300 transition hover:bg-white/5 hover:text-white"
          >
            {request.cancelLabel}
          </button>
          <button
            type="button"
            disabled={!canConfirm}
            onClick={() => onClose(true)}
            className={clsx('rounded-xl px-4 py-2 text-sm font-semibold text-white shadow-lg transition disabled:cursor-not-allowed disabled:opacity-45', dangerous ? 'bg-rose-600 shadow-rose-950/40 hover:bg-rose-500' : 'bg-indigo-600 shadow-indigo-950/40 hover:bg-indigo-500')}
          >
            {request.confirmLabel}
          </button>
        </div>
      </motion.div>
    </motion.div>
  );
}

export function useConfirm() {
  const ctx = useContext(ConfirmContext);
  if (!ctx) throw new Error('useConfirm must be used inside ConfirmProvider');
  return ctx;
}

export function AppProviders({ children }) {
  return (
    <ToastProvider>
      <ConfirmProvider>{children}</ConfirmProvider>
    </ToastProvider>
  );
}

export function Button({ children, variant = 'default', loading = false, disabled = false, className, icon: Icon, ...props }) {
  const variants = {
    default: 'border-white/10 bg-white/[0.04] text-slate-200 hover:border-indigo-400/35 hover:bg-indigo-500/10 hover:text-white',
    primary: 'border-indigo-400/30 bg-indigo-500/15 text-indigo-100 hover:bg-indigo-500/25 hover:text-white shadow-lg shadow-indigo-950/20',
    success: 'border-emerald-400/30 bg-emerald-500/15 text-emerald-100 hover:bg-emerald-500/25 hover:text-white',
    danger: 'border-rose-400/30 bg-rose-500/12 text-rose-100 hover:bg-rose-500/22 hover:text-white',
    ghost: 'border-transparent bg-transparent text-slate-400 hover:bg-white/5 hover:text-white',
  };

  return (
    <motion.button
      type="button"
      disabled={disabled || loading}
      className={clsx('inline-flex items-center justify-center gap-2 rounded-xl border px-3.5 py-2 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-50', variants[variant], className)}
      whileHover={disabled || loading ? undefined : { y: -1 }}
      whileTap={disabled || loading ? undefined : { scale: 0.98 }}
      {...props}
    >
      {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : Icon ? <Icon className="h-4 w-4" /> : null}
      {children}
    </motion.button>
  );
}

export function Panel({ children, className, ...props }) {
  return (
    <motion.section
      className={clsx('rounded-2xl border border-white/10 bg-white/[0.045] shadow-2xl shadow-black/20 backdrop-blur-xl', className)}
      {...panelMotion}
      {...props}
    >
      {children}
    </motion.section>
  );
}

export function Field({ label, description, children, className }) {
  return (
    <label className={clsx('block', className)}>
      <span className="block text-xs font-semibold uppercase tracking-[0.16em] text-slate-400">{label}</span>
      {description && <span className="mt-1 block text-xs leading-5 text-slate-500">{description}</span>}
      <span className="mt-2 block">{children}</span>
    </label>
  );
}

export function TextInput({ className, ...props }) {
  return (
    <input
      className={clsx('w-full rounded-xl border border-white/10 bg-slate-900/70 px-3 py-2 text-sm text-slate-100 outline-none transition placeholder:text-slate-500 focus:border-indigo-300/70 focus:ring-2 focus:ring-indigo-500/20', className)}
      {...props}
    />
  );
}

export function TextArea({ className, ...props }) {
  return (
    <textarea
      className={clsx('w-full rounded-xl border border-white/10 bg-slate-900/70 px-3 py-2 text-sm text-slate-100 outline-none transition placeholder:text-slate-500 focus:border-indigo-300/70 focus:ring-2 focus:ring-indigo-500/20', className)}
      {...props}
    />
  );
}

export function StatusPill({ children, tone = 'slate', className }) {
  const tones = {
    slate: 'border-slate-400/20 bg-slate-500/10 text-slate-300',
    indigo: 'border-indigo-400/25 bg-indigo-500/10 text-indigo-200',
    emerald: 'border-emerald-400/25 bg-emerald-500/10 text-emerald-200',
    amber: 'border-amber-400/25 bg-amber-500/10 text-amber-200',
    rose: 'border-rose-400/25 bg-rose-500/10 text-rose-200',
  };
  return (
    <span className={clsx('inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-semibold', tones[tone], className)}>
      {children}
    </span>
  );
}
