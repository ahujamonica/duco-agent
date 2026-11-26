import React, { useState } from "react";
import {
  Bot,
  BrainCircuit,
  Calculator,
  ChevronDown,
  ClipboardCheck,
  FileSearch,
  ShieldCheck,
  Sparkles,
  Timer,
  UserCheck,
} from "lucide-react";
import { TraceEvent } from "../lib/types";
import { cx } from "./ui";
import { useI18n } from "../lib/i18n";

const AGENT_META: Record<string, { color: string; bg: string; icon: React.ReactNode; short: string }> = {
  "Supervisor Agent": { color: "text-navy", bg: "bg-navy-100", icon: <BrainCircuit className="h-3.5 w-3.5" />, short: "Supervisor" },
  "Intake Agent": { color: "text-brand", bg: "bg-brand-50", icon: <ClipboardCheck className="h-3.5 w-3.5" />, short: "Intake" },
  "Document Intelligence Agent": { color: "text-teal", bg: "bg-teal-50", icon: <FileSearch className="h-3.5 w-3.5" />, short: "Documents" },
  "Coverage Agent": { color: "text-brand", bg: "bg-brand-50", icon: <ShieldCheck className="h-3.5 w-3.5" />, short: "Coverage" },
  "COB Agent": { color: "text-[#7C3AED]", bg: "bg-violet-50", icon: <Sparkles className="h-3.5 w-3.5" />, short: "COB" },
  "Compliance Agent": { color: "text-amber", bg: "bg-amber-50", icon: <UserCheck className="h-3.5 w-3.5" />, short: "Compliance" },
  "Financial Calculation Agent": { color: "text-teal", bg: "bg-teal-50", icon: <Calculator className="h-3.5 w-3.5" />, short: "Financial" },
  "Reporting Agent": { color: "text-brand", bg: "bg-brand-50", icon: <FileSearch className="h-3.5 w-3.5" />, short: "Reporting" },
};

function metaFor(agent: string) {
  return AGENT_META[agent] || { color: "text-ink-muted", bg: "bg-slate-100", icon: <Bot className="h-3.5 w-3.5" />, short: agent };
}

export function TraceTimeline({ events, live }: { events: TraceEvent[]; live?: boolean }) {
  const { t } = useI18n();
  const [expanded, setExpanded] = useState<number | null>(null);
  if (!events.length) return null;
  return (
    <ol className="relative space-y-3">
      <span className="absolute bottom-4 left-[15px] top-2 w-px bg-line" aria-hidden="true" />
      {events.map((event, index) => {
        const meta = metaFor(event.agent);
        const isOpen = expanded === event.seq;
        const failed = event.status === "failed";
        const waiting = event.status === "waiting";
        return (
          <li key={`${event.run_id}-${event.seq}`} className="relative pl-10">
            <span
              className={cx(
                "absolute left-0 top-1 flex h-[31px] w-[31px] items-center justify-center rounded-full border-2 border-white shadow-sm",
                meta.bg,
                meta.color,
                live && index === events.length - 1 && "ring-2 ring-brand/20"
              )}
            >
              {meta.icon}
            </span>
            <div
              className={cx(
                "rounded-xl border bg-white p-3.5 transition",
                failed ? "border-danger/30" : waiting ? "border-amber/35" : "border-line"
              )}
            >
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className={cx("text-[11px] font-bold uppercase tracking-[0.06em]", meta.color)}>{meta.short}</span>
                    <span className="text-[10px] text-ink-soft">·</span>
                    <span className="text-[11px] text-ink-soft">{event.state}</span>
                    <span className="text-[10px] text-ink-soft">#{event.seq}</span>
                  </div>
                  <p className="mt-1 text-[13.5px] font-semibold leading-5 text-navy">{event.action.replace(/_/g, " ")}</p>
                </div>
                <div className="flex items-center gap-2">
                  {live && index === events.length - 1 && (
                    <span className="flex items-center gap-1 text-[10px] font-semibold text-brand">
                      <span className="h-1.5 w-1.5 animate-pulse-soft rounded-full bg-brand" /> {t("run.polling")}
                    </span>
                  )}
                  {event.duration_ms != null && event.duration_ms > 0 && (
                    <span className="flex items-center gap-1 text-[10.5px] tabular-nums text-ink-soft">
                      <Timer className="h-3 w-3" /> {event.duration_ms} ms
                    </span>
                  )}
                  <span
                    className={cx(
                      "rounded-full px-2 py-0.5 text-[9.5px] font-bold uppercase tracking-wide",
                      failed
                        ? "bg-danger-50 text-danger"
                        : waiting
                          ? "bg-amber-50 text-amber"
                          : event.status === "running"
                            ? "bg-brand-50 text-brand"
                            : "bg-teal-50 text-teal-600"
                    )}
                  >
                    {event.status}
                  </span>
                </div>
              </div>
              {event.observation && (
                <p className="mt-2 text-[12px] leading-5 text-ink-muted">
                  <span className="font-semibold text-ink">Observation: </span>
                  {event.observation}
                </p>
              )}
              {event.decision && (
                <p className={cx("mt-1.5 rounded-lg px-2.5 py-1.5 text-[11.5px] leading-4", failed ? "bg-danger-50 text-[#7B1E1E]" : "bg-canvas text-ink-muted")}>
                  <span className="font-semibold text-navy">Decision: </span>
                  {event.decision}
                </p>
              )}
              {event.checks.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {event.checks.slice(0, 5).map((check, checkIndex) => (
                    <span
                      key={checkIndex}
                      title={check.detail}
                      className={cx(
                        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium",
                        check.passed ? "bg-teal-50 text-[#0B5B56]" : "bg-danger-50 text-[#7B1E1E]"
                      )}
                    >
                      <span className={cx("h-1.5 w-1.5 rounded-full", check.passed ? "bg-teal" : "bg-danger")} />
                      {check.name}
                    </span>
                  ))}
                </div>
              )}
              <button
                onClick={() => setExpanded(isOpen ? null : event.seq)}
                className="focus-ring mt-2 flex items-center gap-1 text-[10.5px] font-semibold text-brand hover:text-brand-600"
                aria-expanded={isOpen}
              >
                <ChevronDown className={cx("h-3 w-3 transition", isOpen && "rotate-180")} />
                {isOpen ? "Hide inputs" : "Inputs and tool"}
              </button>
              {isOpen && (
                <div className="mt-2 rounded-lg bg-navy p-3 text-[10.5px] leading-4 text-white/80">
                  <p className="mb-1 text-white/50">Tool: {event.tool || "internal"}</p>
                  <pre className="max-h-52 overflow-auto whitespace-pre-wrap break-words font-mono text-[10px] text-teal-200">
                    {JSON.stringify(event.inputs, null, 2)}
                  </pre>
                  {event.next_action && <p className="mt-2 text-white/50">Next: {event.next_action}</p>}
                </div>
              )}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
