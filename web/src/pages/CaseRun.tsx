import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  ArrowRight,
  CheckCircle2,
  Circle,
  Clock3,
  FileCheck2,
  Loader2,
  Play,
  RefreshCw,
  ShieldCheck,
  TriangleAlert,
  XCircle,
} from "lucide-react";
import { useApi } from "../lib/useApi";
import { useI18n } from "../lib/i18n";
import { api } from "../lib/api";
import { CaseDetail, TraceResponse } from "../lib/types";
import {
  Alert,
  Badge,
  Button,
  Card,
  LoadingBlock,
  PageHeader,
  StatusBadge,
  cx,
  useToast,
} from "../components/ui";
import { inr } from "../lib/format";
import { TraceTimeline } from "../components/Timeline";

const TASKS = [
  { key: "intake", agent: "Intake Agent" },
  { key: "documents", agent: "Document Intelligence Agent" },
  { key: "coverage", agent: "Coverage Agent" },
  { key: "cob", agent: "COB Agent" },
  { key: "compliance", agent: "Compliance Agent" },
  { key: "financial", agent: "Financial Calculation Agent" },
  { key: "reporting", agent: "Reporting Agent" },
  { key: "critic", agent: "Supervisor Agent" },
];

export default function CaseRun() {
  const { caseId } = useParams();
  const { t } = useI18n();
  const { notify } = useToast();
  const navigate = useNavigate();
  const [detail, setDetail] = useState<CaseDetail | null>(null);
  const [trace, setTrace] = useState<TraceResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [agentFilter, setAgentFilter] = useState("all");
  const statusRef = useRef<string>("");

  const load = useCallback(async () => {
    if (!caseId) return;
    try {
      const [caseData, traceData] = await Promise.all([
        api.get<CaseDetail>(`/api/cases/${caseId}`),
        api.get<TraceResponse>(`/api/cases/${caseId}/trace?limit=600`),
      ]);
      setDetail(caseData);
      setTrace(traceData);
      statusRef.current = caseData.status;
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load the case.");
    } finally {
      setLoading(false);
    }
  }, [caseId]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (!detail) return;
    if (!["queued", "running"].includes(detail.status)) return;
    const timer = setInterval(load, 1500);
    return () => clearInterval(timer);
  }, [detail?.status, load]);

  const start = async () => {
    setStarting(true);
    try {
      await api.post(`/api/cases/${caseId}/analyze`, {});
      notify("The supervisor is planning the case.", "success");
      await load();
    } catch (err) {
      notify(err instanceof Error ? err.message : "Could not start the analysis.", "error");
    } finally {
      setStarting(false);
    }
  };

  const events = useMemo(() => {
    if (!trace) return [];
    const runId = trace.run_id;
    let list = runId ? trace.events.filter((event) => !event.run_id || event.run_id === runId) : trace.events;
    if (!list.length) list = trace.events;
    if (agentFilter !== "all") list = list.filter((event) => event.agent === agentFilter);
    return list;
  }, [trace, agentFilter]);

  const agents = useMemo(() => Array.from(new Set((trace?.events || []).map((event) => event.agent))), [trace]);
  const tasks = trace?.tasks || {};
  const live = detail ? ["queued", "running"].includes(detail.status) : false;

  if (loading && !detail) return <LoadingBlock />;
  if (error) return <Alert tone="danger" title={t("common.error")}>{error}</Alert>;
  if (!detail) return null;

  const complete = detail.status === "complete";
  const review = detail.status === "awaiting_review" && detail.review_pending > 0;
  const pausedWithoutReview =
    detail.status === "awaiting_review" && detail.review_pending === 0;
  const pauseGap =
    detail.gaps.find((gap) => gap.severity === "blocking") || detail.gaps[0];
  const failed = detail.status === "failed";
  const totals = detail.totals || {};
  const doneTasks = Object.values(tasks).filter((value) => value === "done").length;

  return (
    <div>
      <PageHeader
        eyebrow={detail.family?.name}
        title={detail.title}
        subtitle={t("run.subtitle")}
        actions={
          <>
            <Badge tone="amber">{t("common.simulated")}</Badge>
            <Link to={`/app/cases/${detail.id}`}>
              <Button variant="secondary">{t("common.details")}</Button>
            </Link>
            {["draft", "ready", "failed", "complete"].includes(detail.status) && (
              <Button loading={starting} onClick={start} icon={complete ? <RefreshCw className="h-4 w-4" /> : <Play className="h-4 w-4" />}>
                {complete ? t("run.rerun") : t("run.start")}
              </Button>
            )}
          </>
        }
      />

      {review && (
        <div className="mb-4">
          <Alert
            tone="warning"
            title={`${detail.review_pending} ${t("review.pending")}`}
            action={
              <Link to={`/app/cases/${detail.id}/review`}>
                <Button size="sm" className="bg-amber text-white hover:bg-[#96651b]">{t("run.reviewCta")}</Button>
              </Link>
            }
          >
            {t("review.runAfter")}
          </Alert>
        </div>
      )}
      {pausedWithoutReview && (
        <div className="mb-4">
          <Alert tone="warning" title="Workflow paused">
            {pauseGap
              ? `${pauseGap.title}: ${pauseGap.detail}${pauseGap.action ? ` ${pauseGap.action}` : ""}`
              : "The workflow paused without pending review fields. Check the case gaps and activity for the required next step."}
          </Alert>
        </div>
      )}
      {failed && (
        <div className="mb-4">
          <Alert tone="danger" title={t("run.failed")}>
            {detail.error || t("run.failedBody")}
          </Alert>
        </div>
      )}
      {complete && (
        <div className="mb-4 flex flex-col justify-between gap-3 rounded-xl border border-teal/25 bg-teal-50 px-4 py-3 sm:flex-row sm:items-center">
          <div className="flex items-center gap-2 text-[12.5px] font-medium text-[#0B5B56]">
            <CheckCircle2 className="h-4 w-4" /> {t("run.complete")} · {inr(totals.billed || 0)} billed · {inr(totals.patient_liability || 0)} your share
          </div>
          <Link to={`/app/cases/${detail.id}`}>
            <Button size="sm" variant="teal" icon={<ArrowRight className="h-3.5 w-3.5" />}>{t("run.resultsCta")}</Button>
          </Link>
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
        <div className="space-y-4">
          <Card className="p-5">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="flex items-center gap-3">
                <span
                  className={cx(
                    "flex h-10 w-10 items-center justify-center rounded-xl",
                    live ? "bg-brand-50 text-brand" : complete ? "bg-teal-50 text-teal" : review ? "bg-amber-50 text-amber" : "bg-slate-100 text-ink-soft"
                  )}
                >
                  {live ? <Loader2 className="h-5 w-5 animate-spin" /> : complete ? <ShieldCheck className="h-5 w-5" /> : review ? <FileCheck2 className="h-5 w-5" /> : <Clock3 className="h-5 w-5" />}
                </span>
                <div>
                  <p className="text-[14px] font-bold text-navy">
                    {live ? t("run.running") : complete ? t("run.complete") : review ? t("run.review") : detail.status === "ready" || detail.status === "draft" ? t("run.waiting") : t("run.failed")}
                  </p>
                  <p className="mt-0.5 text-[11px] text-ink-soft">
                    {t("run.stage")}: <span className="font-medium text-ink-muted">{trace?.stage || detail.trace.stage || "—"}</span> · {doneTasks}/8 goals
                  </p>
                </div>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <StatusBadge status={detail.status} />
                {live && <span className="text-[10px] font-semibold text-brand">{t("run.polling")}</span>}
              </div>
            </div>
            <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
              {TASKS.map((task) => {
                const state = tasks[task.key] || "pending";
                const done = state === "done";
                const running = state === "running";
                return (
                  <div
                    key={task.key}
                    className={cx(
                      "flex items-center gap-1.5 rounded-lg border px-2 py-1.5 text-[10px]",
                      done ? "border-teal/25 bg-teal-50/70 text-[#0B5B56]" : running ? "border-brand/30 bg-brand-50 text-brand" : "border-line text-ink-soft"
                    )}
                  >
                    {done ? <CheckCircle2 className="h-3 w-3" /> : running ? <Loader2 className="h-3 w-3 animate-spin" /> : <Circle className="h-2.5 w-2.5" />}
                    <span className="truncate">{task.key}</span>
                  </div>
                );
              })}
            </div>
          </Card>

          <Card className="p-5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 className="text-[15px] font-bold">{t("run.timeline")}</h2>
              <div className="flex flex-wrap gap-1">
                <button
                  onClick={() => setAgentFilter("all")}
                  className={cx("rounded-full px-2 py-0.5 text-[9.5px] font-semibold", agentFilter === "all" ? "bg-navy text-white" : "bg-canvas text-ink-muted")}
                >
                  All
                </button>
                {agents.map((agent) => (
                  <button
                    key={agent}
                    onClick={() => setAgentFilter(agent)}
                    className={cx("rounded-full px-2 py-0.5 text-[9.5px] font-semibold", agentFilter === agent ? "bg-navy text-white" : "bg-canvas text-ink-muted")}
                  >
                    {agent.replace(" Agent", "").replace("Financial Calculation", "Financial")}
                  </button>
                ))}
              </div>
            </div>
            <div className="mt-4">
              {events.length === 0 ? (
                <div className="rounded-xl border border-dashed border-line px-5 py-10 text-center">
                  <p className="text-[12.5px] text-ink-muted">{t("run.empty")}</p>
                  {["ready", "draft"].includes(detail.status) && (
                    <Button className="mt-3" size="sm" loading={starting} onClick={start} icon={<Play className="h-3.5 w-3.5" />}>
                      {t("run.start")}
                    </Button>
                  )}
                </div>
              ) : (
                <TraceTimeline events={events} live={live} />
              )}
            </div>
          </Card>
        </div>

        <div className="space-y-4">
          <Card className="p-5">
            <h2 className="text-[13px] font-bold">{t("run.plan")}</h2>
            <p className="mt-1 text-[10.5px] leading-4 text-ink-soft">The supervisor picks the next agent whose dependencies are met.</p>
            <ol className="mt-3 space-y-1.5">
              {TASKS.map((task, index) => {
                const state = tasks[task.key] || "pending";
                return (
                  <li key={task.key} className="flex items-center gap-2 text-[11px]">
                    <span
                      className={cx(
                        "flex h-4 w-4 shrink-0 items-center justify-center rounded-full text-[8px] font-bold",
                        state === "done" ? "bg-teal text-white" : state === "running" ? "bg-brand text-white" : "bg-slate-100 text-ink-soft"
                      )}
                    >
                      {state === "done" ? "✓" : index + 1}
                    </span>
                    <span className={cx("flex-1 truncate", state === "pending" ? "text-ink-soft" : "text-navy")}>{task.agent}</span>
                    <span className="text-[8.5px] uppercase text-ink-soft">{state}</span>
                  </li>
                );
              })}
            </ol>
          </Card>

          <Card className="p-5">
            <h2 className="text-[13px] font-bold">Case</h2>
            <dl className="mt-3 space-y-2 text-[11px]">
              <div className="flex justify-between gap-3"><dt className="text-ink-soft">{t("cases.patient")}</dt><dd className="font-medium text-navy">{detail.patient?.name || "—"}</dd></div>
              <div className="flex justify-between gap-3"><dt className="text-ink-soft">{t("cases.provider")}</dt><dd className="truncate text-right font-medium text-navy">{detail.provider_name || "—"}</dd></div>
              <div className="flex justify-between gap-3"><dt className="text-ink-soft">{t("cases.date")}</dt><dd className="font-medium text-navy">{detail.service_date || "—"}</dd></div>
              <div className="flex justify-between gap-3"><dt className="text-ink-soft">Documents</dt><dd className="font-medium text-navy">{detail.documents.length}</dd></div>
              <div className="flex justify-between gap-3"><dt className="text-ink-soft">Policies</dt><dd className="font-medium text-navy">{detail.policies.length}</dd></div>
            </dl>
            <div className="mt-3 border-t border-line pt-3">
              <p className="text-[10px] leading-4 text-ink-soft">{t("run.demoNote")}</p>
            </div>
          </Card>

          {detail.gaps.length > 0 && (
            <Card className="p-5">
              <h2 className="text-[13px] font-bold">{t("results.gaps")}</h2>
              <div className="mt-2 space-y-2">
                {detail.gaps.slice(0, 5).map((gap, index) => (
                  <div key={index} className="rounded-lg bg-canvas px-2.5 py-1.5">
                    <p className="text-[11px] font-semibold text-navy">{gap.title}</p>
                    <p className="mt-0.5 text-[10px] leading-4 text-ink-soft">{gap.detail}</p>
                  </div>
                ))}
              </div>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
