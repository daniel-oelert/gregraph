import type { ButtonHTMLAttributes, ReactNode } from "react";

type Variant = "primary" | "secondary" | "danger" | "ghost";

const variants: Record<Variant, string> = {
  primary: "bg-indigo-600 text-white hover:bg-indigo-500 disabled:bg-indigo-300",
  secondary: "bg-white text-slate-800 ring-1 ring-inset ring-slate-300 hover:bg-slate-50 disabled:text-slate-400",
  danger: "bg-white text-red-700 ring-1 ring-inset ring-red-300 hover:bg-red-50 disabled:text-red-300",
  ghost: "text-indigo-700 hover:bg-indigo-50 disabled:text-slate-400",
};

export function Button({
  variant = "secondary",
  className = "",
  type = "button",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  return (
    <button
      type={type}
      className={`inline-flex items-center justify-center gap-1 rounded-md px-3 py-1.5 text-sm font-medium shadow-sm transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600 disabled:cursor-not-allowed ${variants[variant]} ${className}`}
      {...props}
    />
  );
}

export function Alert({ children }: { children: ReactNode }) {
  return (
    <div role="alert" className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
      {children}
    </div>
  );
}

export function Notice({ children, tone = "info" }: { children: ReactNode; tone?: "info" | "warn" }) {
  const toneClass = tone === "warn" ? "border-amber-200 bg-amber-50 text-amber-900" : "border-slate-200 bg-slate-50 text-slate-700";
  return (
    <div role="status" className={`rounded-md border px-3 py-2 text-sm ${toneClass}`}>
      {children}
    </div>
  );
}

export function Badge({ children, tone = "neutral" }: { children: ReactNode; tone?: "neutral" | "warn" | "good" }) {
  const toneClass = {
    neutral: "bg-slate-100 text-slate-700 ring-slate-200",
    warn: "bg-amber-100 text-amber-900 ring-amber-300",
    good: "bg-emerald-100 text-emerald-900 ring-emerald-300",
  }[tone];
  return (
    <span className={`inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium ring-1 ring-inset ${toneClass}`}>
      {children}
    </span>
  );
}

export function Spinner({ label }: { label: string }) {
  return (
    <p role="status" className="text-sm text-slate-500">
      {label}
    </p>
  );
}

export function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section aria-label={title} className="rounded-lg bg-white p-4 shadow-sm ring-1 ring-slate-200">
      <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
        {title}
      </h3>
      {children}
    </section>
  );
}
