import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { AlertCircle, CheckCircle2, ChevronDown, Info, Loader2, X } from "lucide-react";
import { useI18n } from "../lib/i18n";
import { STATUS_LABELS } from "../lib/format";

export function cx(...values: Array<string | false | null | undefined>): string {
  return values.filter(Boolean).join(" ");
}

type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger" | "teal" | "soft";
  size?: "sm" | "md" | "lg";
  loading?: boolean;
  icon?: React.ReactNode;
};

export function Button({
  variant = "primary",
  size = "md",
  loading,
  icon,
  className,
  children,
  disabled,
  ...rest
}: ButtonProps) {
  const styles: Record<string, string> = {
    primary: "bg-brand text-white hover:bg-brand-600 shadow-sm",
    secondary: "bg-white text-navy border border-line hover:border-brand/40 hover:text-brand",
    ghost: "bg-transparent text-ink-muted hover:bg-navy/5 hover:text-navy",
    danger: "bg-danger text-white hover:bg-red-700",
    teal: "bg-teal text-white hover:bg-teal-600",
    soft: "bg-brand-50 text-brand hover:bg-brand/10",
  };
  const sizes: Record<string, string> = {
    sm: "h-8 px-3 text-[13px] gap-1.5",
    md: "h-10 px-4 text-sm gap-2",
    lg: "h-12 px-5 text-[15px] gap-2",
  };
  return (
    <button
      className={cx(
        "inline-flex items-center justify-center rounded-lg font-semibold transition-all duration-150 focus-ring disabled:opacity-50 disabled:cursor-not-allowed whitespace-nowrap",
        styles[variant],
        sizes[size],
        className
      )}
      disabled={disabled || loading}
      {...rest}
    >
      {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : icon}
      {children}
    </button>
  );
}

export function Card({ className, children, ...rest }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cx("rounded-xl2 border border-line bg-white shadow-card", className)} {...rest}>
      {children}
    </div>
  );
}

export function Badge({
  children,
  tone = "slate",
  className,
}: {
  children: React.ReactNode;
  tone?: "slate" | "blue" | "teal" | "amber" | "red" | "navy";
  className?: string;
}) {
  const tones: Record<string, string> = {
    slate: "bg-slate-100 text-slate-600",
    blue: "bg-brand-50 text-brand-600",
    teal: "bg-teal-50 text-teal-600",
    amber: "bg-amber-50 text-amber",
    red: "bg-danger-50 text-danger",
    navy: "bg-navy-100 text-navy",
  };
  return (
    <span
      className={cx(
        "inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[11px] font-semibold tracking-wide uppercase",
        tones[tone],
        className
      )}
    >
      {children}
    </span>
  );
}

export function StatusBadge({ status }: { status: string }) {
  const { lang } = useI18n();
  const meta = STATUS_LABELS[status] || { en: status, hi: status, tone: "slate" };
  return <Badge tone={(meta.tone as any) || "slate"}>{lang === "hi" ? meta.hi : meta.en}</Badge>;
}

export function Field({
  label,
  hint,
  error,
  children,
  className,
  htmlFor,
}: {
  label?: React.ReactNode;
  hint?: string;
  error?: string;
  children: React.ReactNode;
  className?: string;
  htmlFor?: string;
}) {
  return (
    <div className={cx("space-y-1.5", className)}>
      {label && (
        <label htmlFor={htmlFor} className="block text-[12px] font-semibold text-navy">
          {label}
        </label>
      )}
      {children}
      {hint && !error && <p className="text-[11.5px] leading-4 text-ink-soft">{hint}</p>}
      {error && <p className="text-[11.5px] leading-4 text-danger">{error}</p>}
    </div>
  );
}

const inputBase =
  "w-full rounded-lg border border-line bg-white px-3 py-2 text-sm text-ink placeholder:text-ink-soft/70 focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand/15 disabled:bg-slate-50";

export function Input(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={cx(inputBase, props.className)} />;
}

export function Textarea(props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea {...props} className={cx(inputBase, "min-h-[92px] resize-y", props.className)} />;
}

export function Select(props: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <div className="relative">
      <select {...props} className={cx(inputBase, "appearance-none pr-9", props.className)} />
      <ChevronDown className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-soft" />
    </div>
  );
}

export function Checkbox({
  checked,
  onChange,
  label,
  description,
  disabled,
}: {
  checked: boolean;
  onChange: (value: boolean) => void;
  label: React.ReactNode;
  description?: React.ReactNode;
  disabled?: boolean;
}) {
  return (
    <label
      className={cx(
        "flex cursor-pointer items-start gap-3 rounded-lg border p-3 transition",
        checked ? "border-brand/50 bg-brand-50/60" : "border-line hover:border-brand/30",
        disabled && "cursor-not-allowed opacity-60"
      )}
    >
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
        className="mt-0.5 h-4 w-4 rounded border-line text-brand focus:ring-brand/30"
      />
      <span className="min-w-0">
        <span className="block text-[13px] font-semibold text-navy">{label}</span>
        {description && <span className="mt-0.5 block text-[11.5px] leading-4 text-ink-muted">{description}</span>}
      </span>
    </label>
  );
}

export function Modal({
  open,
  onClose,
  title,
  children,
  footer,
  width = "max-w-2xl",
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: React.ReactNode;
  footer?: React.ReactNode;
  width?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const listener = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", listener);
    document.body.style.overflow = "hidden";
    ref.current?.focus();
    return () => {
      document.removeEventListener("keydown", listener);
      document.body.style.overflow = "";
    };
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-navy/45 p-4 sm:p-8" role="dialog" aria-modal="true" aria-label={title}>
      <div
        ref={ref}
        tabIndex={-1}
        className={cx("animate-fade-up w-full rounded-2xl bg-white shadow-lift outline-none", width)}
      >
        <div className="flex items-start justify-between gap-4 border-b border-line px-6 py-4">
          <h2 className="text-[17px] font-bold tracking-tight text-navy">{title}</h2>
          <button
            onClick={onClose}
            aria-label="Close"
            className="focus-ring rounded-lg p-1.5 text-ink-soft hover:bg-navy/5 hover:text-navy"
          >
            <X className="h-4.5 w-4.5" />
          </button>
        </div>
        <div className="max-h-[70vh] overflow-y-auto px-6 py-5">{children}</div>
        {footer && <div className="flex flex-wrap justify-end gap-2 border-t border-line px-6 py-4">{footer}</div>}
      </div>
    </div>
  );
}

export function PageHeader({
  title,
  subtitle,
  actions,
  eyebrow,
}: {
  title: string;
  subtitle?: string;
  actions?: React.ReactNode;
  eyebrow?: string;
}) {
  return (
    <div className="mb-6 flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
      <div>
        {eyebrow && <p className="mb-1 text-[11px] font-bold uppercase tracking-[0.14em] text-brand">{eyebrow}</p>}
        <h1 className="text-[26px] font-bold leading-tight tracking-[-0.02em] text-navy sm:text-[30px]">{title}</h1>
        {subtitle && <p className="mt-1.5 max-w-2xl text-[13.5px] leading-5 text-ink-muted">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function EmptyState({
  title,
  body,
  action,
  icon,
}: {
  title: string;
  body: string;
  action?: React.ReactNode;
  icon?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center rounded-xl2 border border-dashed border-line bg-white/70 px-6 py-14 text-center">
      {icon && <div className="mb-3 rounded-2xl bg-brand-50 p-3 text-brand">{icon}</div>}
      <h3 className="text-[16px] font-bold text-navy">{title}</h3>
      <p className="mt-1 max-w-md text-[13px] leading-5 text-ink-muted">{body}</p>
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={cx("h-5 w-5 animate-spin text-brand", className)} />;
}

export function LoadingBlock({ label }: { label?: string }) {
  const { t } = useI18n();
  return (
    <div className="flex items-center justify-center gap-3 rounded-xl2 border border-line bg-white px-6 py-16 text-[13px] text-ink-muted">
      <Spinner />
      {label || t("common.loading")}
    </div>
  );
}

export function Alert({
  children,
  tone = "info",
  title,
  action,
}: {
  children: React.ReactNode;
  tone?: "info" | "warning" | "danger" | "success";
  title?: string;
  action?: React.ReactNode;
}) {
  const styles = {
    info: { box: "border-brand/20 bg-brand-50/70 text-navy", icon: <Info className="h-4.5 w-4.5 text-brand" /> },
    warning: { box: "border-amber/25 bg-amber-50 text-[#6B4A10]", icon: <AlertCircle className="h-4.5 w-4.5 text-amber" /> },
    danger: { box: "border-danger/20 bg-danger-50 text-[#7B1E1E]", icon: <AlertCircle className="h-4.5 w-4.5 text-danger" /> },
    success: { box: "border-teal/25 bg-teal-50 text-[#0B5B56]", icon: <CheckCircle2 className="h-4.5 w-4.5 text-teal" /> },
  }[tone];
  return (
    <div className={cx("flex items-start gap-3 rounded-xl border px-4 py-3 text-[12.5px] leading-5", styles.box)}>
      <div className="mt-0.5 shrink-0">{styles.icon}</div>
      <div className="min-w-0 flex-1">
        {title && <p className="mb-0.5 font-bold">{title}</p>}
        <div>{children}</div>
      </div>
      {action}
    </div>
  );
}

export function Confidence({ value, showLabel = true }: { value: number; showLabel?: boolean }) {
  const percent = Math.round((Number(value) || 0) * 100);
  const tone = percent >= 85 ? "bg-teal" : percent >= 65 ? "bg-amber" : "bg-danger";
  return (
    <div className="flex items-center gap-2" title={`${percent}% confidence`}>
      <div className="h-1.5 w-16 overflow-hidden rounded-full bg-slate-100">
        <div className={cx("h-full rounded-full", tone)} style={{ width: `${percent}%` }} />
      </div>
      {showLabel && <span className="text-[11px] font-semibold tabular-nums text-ink-muted">{percent}%</span>}
    </div>
  );
}

export function Stat({
  label,
  value,
  hint,
  tone = "navy",
  icon,
}: {
  label: string;
  value: React.ReactNode;
  hint?: string;
  tone?: "navy" | "teal" | "blue" | "amber" | "red";
  icon?: React.ReactNode;
}) {
  const colour = {
    navy: "text-navy",
    teal: "text-teal",
    blue: "text-brand",
    amber: "text-amber",
    red: "text-danger",
  }[tone];
  return (
    <Card className="p-4 sm:p-5">
      <div className="flex items-start justify-between gap-2">
        <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-ink-soft">{label}</p>
        {icon && <span className="text-ink-soft/70">{icon}</span>}
      </div>
      <p className={cx("mt-2 text-[23px] font-bold leading-none tracking-[-0.02em] tabular-nums", colour)}>{value}</p>
      {hint && <p className="mt-1.5 text-[11px] leading-4 text-ink-soft">{hint}</p>}
    </Card>
  );
}

export function Term({ term, children }: { term: string; children?: React.ReactNode }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  return (
    <span className="relative inline-flex items-center gap-1">
      <span>{children || t(`glossary.${term}`)}</span>
      <button
        type="button"
        aria-label={`What is ${t(`glossary.${term}`)}?`}
        onClick={() => setOpen((value) => !value)}
        onBlur={() => setTimeout(() => setOpen(false), 120)}
        className="focus-ring inline-flex h-4 w-4 items-center justify-center rounded-full border border-line text-[9px] font-bold text-ink-soft hover:border-brand hover:text-brand"
      >
        i
      </button>
      {open && (
        <span className="absolute bottom-full left-0 z-30 mb-2 w-64 rounded-lg border border-line bg-white p-3 text-left text-[11.5px] font-normal leading-4 text-ink shadow-lift">
          {t(`glossary.${term}Plain`)}
        </span>
      )}
    </span>
  );
}

export function UsageBar({
  label,
  used,
  max,
  format,
}: {
  label: string;
  used: number;
  max: number;
  format: (value: number) => string;
}) {
  const percent = max > 0 ? Math.min(100, (used / max) * 100) : 0;
  return (
    <div>
      <div className="mb-1 flex items-center justify-between text-[11.5px]">
        <span className="text-ink-muted">{label}</span>
        <span className="font-semibold tabular-nums text-navy">
          {format(used)} <span className="font-normal text-ink-soft">/ {format(max)}</span>
        </span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-slate-100">
        <div
          className={cx("h-full rounded-full", percent >= 90 ? "bg-danger" : percent >= 70 ? "bg-amber" : "bg-teal")}
          style={{ width: `${percent}%` }}
        />
      </div>
    </div>
  );
}

type Toast = { id: number; message: string; tone: "success" | "error" | "info" };
const ToastContext = createContext<{ notify: (message: string, tone?: Toast["tone"]) => void } | null>(null);

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const notify = useCallback((message: string, tone: Toast["tone"] = "info") => {
    const id = Date.now() + Math.random();
    setToasts((current) => [...current, { id, message, tone }]);
    setTimeout(() => setToasts((current) => current.filter((item) => item.id !== id)), 4200);
  }, []);
  return (
    <ToastContext.Provider value={{ notify }}>
      {children}
      <div className="pointer-events-none fixed bottom-4 right-4 z-[60] flex w-[min(92vw,380px)] flex-col gap-2">
        {toasts.map((toast) => (
          <div
            key={toast.id}
            className={cx(
              "pointer-events-auto animate-fade-up rounded-xl border px-4 py-3 text-[12.5px] font-medium shadow-lift",
              toast.tone === "success" && "border-teal/30 bg-white text-[#0B5B56]",
              toast.tone === "error" && "border-danger/25 bg-white text-[#7B1E1E]",
              toast.tone === "info" && "border-line bg-white text-navy"
            )}
          >
            {toast.message}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const context = useContext(ToastContext);
  if (!context) throw new Error("useToast must be used inside ToastProvider");
  return context;
}
