import React from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  ArrowRight,
  ArrowUpRight,
  BellRing,
  FileText,
  FolderKanban,
  Plus,
  ShieldAlert,
  ShieldCheck,
  Users,
  Wallet,
} from "lucide-react";
import { useAuth } from "../lib/auth";
import { useI18n } from "../lib/i18n";
import { useApi } from "../lib/useApi";
import { DashboardData, Family } from "../lib/types";
import { inr, ago } from "../lib/format";
import { Alert, Badge, Button, Card, EmptyState, LoadingBlock, PageHeader, Stat, StatusBadge, cx } from "../components/ui";
import { DonutChart, Legend } from "../components/Charts";
import { InsuranceGraph } from "../components/InsuranceGraph";

export default function Dashboard() {
  const { t } = useI18n();
  const { user } = useAuth();
  const navigate = useNavigate();
  const dashboard = useApi<DashboardData>("/api/dashboard");
  const families = useApi<{ families: Family[] }>("/api/families");
  const isDemo = user?.email === "demo@duco.health";

  if (dashboard.loading && !dashboard.data) return <LoadingBlock />;
  if (dashboard.error) return <Alert tone="danger" title={t("common.error")}>{dashboard.error}</Alert>;
  const data = dashboard.data;
  if (!data) return null;

  const family = families.data?.families?.length
    ? families.data.families.reduce((best, current) =>
        current.counts.policies + current.counts.cases > best.counts.policies + best.counts.cases ? current : best
      )
    : null;
  const billed = Number(data.totals.billed || 0);
  const insurer = Number(data.totals.insurer_paid || 0);
  const patient = Number(data.totals.patient_responsibility || 0);
  const hasCases = data.totals.cases > 0;

  return (
    <div>
      <PageHeader
        eyebrow={isDemo ? "Demo household" : undefined}
        title={t("dashboard.title")}
        subtitle={t("dashboard.subtitle")}
        actions={
          <>
            <Link to="/app/cases/new">
              <Button icon={<Plus className="h-4 w-4" />}>{t("nav.newCase")}</Button>
            </Link>
            <Link to="/app/documents">
              <Button variant="secondary" icon={<FileText className="h-4 w-4" />}>{t("documents.upload")}</Button>
            </Link>
          </>
        }
      />

      {isDemo && (
        <div className="mb-5 flex flex-col justify-between gap-3 rounded-xl border border-amber/25 bg-amber-50 px-4 py-3 sm:flex-row sm:items-center">
          <div className="flex items-start gap-2.5">
            <BellRing className="mt-0.5 h-4 w-4 shrink-0 text-amber" />
            <p className="text-[12px] leading-5 text-[#6B4A10]">
              <span className="font-bold">Demo household · Sen family.</span> Five scenarios are preloaded. Open the surgery case and press Run analysis.
            </p>
          </div>
          <Link to="/app/cases" className="shrink-0 text-[11.5px] font-bold text-amber hover:underline">
            View the scenarios →
          </Link>
        </div>
      )}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label={t("dashboard.cases")} value={data.totals.cases} icon={<FolderKanban className="h-4 w-4" />} />
        <Stat label={t("dashboard.activeClaims")} value={data.totals.active_claims} tone="blue" icon={<ArrowUpRight className="h-4 w-4" />} />
        <Stat label={t("dashboard.pendingAuth")} value={data.totals.pending_authorizations} tone={data.totals.pending_authorizations ? "amber" : "navy"} icon={<ShieldAlert className="h-4 w-4" />} />
        <Stat label={t("dashboard.billed")} value={inr(billed)} tone="navy" icon={<Wallet className="h-4 w-4" />} />
      </div>

      {!hasCases || data.totals.families === 0 ? (
        <Card className="mt-5 p-6">
          <div className="mb-5">
            <h2 className="text-[16px] font-bold">{t("dashboard.startTitle")}</h2>
            <p className="mt-1 text-[12.5px] text-ink-muted">{t("dashboard.noCasesBody")}</p>
          </div>
          <div className="grid gap-3 md:grid-cols-3">
            {[
              { n: "01", title: t("dashboard.start1"), body: t("dashboard.start1Body"), to: "/app/family", done: (families.data?.families.length || 0) > 0 },
              { n: "02", title: t("dashboard.start2"), body: t("dashboard.start2Body"), to: "/app/policies", done: (family?.counts.policies || 0) > 0 },
              { n: "03", title: t("dashboard.start3"), body: t("dashboard.start3Body"), to: "/app/documents", done: (family?.counts.documents || 0) > 0 },
            ].map((step) => (
              <Link key={step.to} to={step.to} className="group rounded-xl border border-line p-4 transition hover:border-brand/40 hover:bg-brand-50/30">
                <div className="flex items-center justify-between">
                  <span className="text-[11px] font-bold text-brand">{step.n}</span>
                  {step.done ? <Badge tone="teal">done</Badge> : <ArrowRight className="h-4 w-4 text-ink-soft group-hover:text-brand" />}
                </div>
                <p className="mt-2 text-[13px] font-semibold text-navy">{step.title}</p>
                <p className="mt-1 text-[11.5px] leading-4 text-ink-muted">{step.body}</p>
              </Link>
            ))}
          </div>
        </Card>
      ) : (
        <>
          <div className="mt-5 grid gap-4 lg:grid-cols-[1.35fr_1fr]">
            <Card className="p-5">
              <div className="flex items-start justify-between">
                <div>
                  <h2 className="text-[15px] font-bold">{t("dashboard.recent")}</h2>
                  <p className="mt-0.5 text-[11.5px] text-ink-muted">{data.totals.cases} cases · {data.totals.families} {data.totals.families === 1 ? "household" : "households"}</p>
                </div>
                <Link to="/app/cases" className="text-[11.5px] font-semibold text-brand hover:text-brand-600">
                  {t("dashboard.viewAll")}
                </Link>
              </div>
              <div className="mt-4 overflow-x-auto">
                <table className="w-full min-w-[520px] text-left text-[12px]">
                  <thead>
                    <tr className="border-b border-line text-[10px] uppercase tracking-[0.08em] text-ink-soft">
                      <th className="whitespace-nowrap pb-2 font-semibold">Case</th>
                      <th className="whitespace-nowrap pb-2 font-semibold">{t("common.status")}</th>
                      <th className="whitespace-nowrap pb-2 text-right font-semibold">{t("cases.billed")}</th>
                      <th className="whitespace-nowrap pb-2 text-right font-semibold">{t("cases.youPay")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.recent_cases.map((item) => (
                      <tr key={item.id} className="group border-b border-line/60 last:border-0">
                        <td className="py-2.5 pr-3">
                          <Link to={`/app/cases/${item.id}${item.status === "ready" || item.status === "draft" ? "/run" : ""}`} className="block">
                            <span className="block max-w-[260px] truncate font-semibold text-navy group-hover:text-brand">{item.title}</span>
                            <span className="text-[10.5px] text-ink-soft">{item.family} · {item.provider || "—"} · {ago(item.updated_at)}</span>
                          </Link>
                        </td>
                        <td className="py-2.5"><StatusBadge status={item.status} /></td>
                        <td className="py-2.5 text-right tabular-nums text-ink-muted">{inr(item.totals?.billed || 0)}</td>
                        <td className="py-2.5 text-right font-semibold tabular-nums text-navy">{inr(item.totals?.patient_liability || 0)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>

            <Card className="p-5">
              <div className="flex items-start justify-between">
                <div>
                  <h2 className="text-[15px] font-bold">{t("results.split")}</h2>
                  <p className="mt-0.5 text-[11.5px] text-ink-muted">Across every completed case</p>
                </div>
                <Badge tone="amber">{t("common.simulated")}</Badge>
              </div>
              <DonutChart
                label={t("results.billed")}
                total={billed}
                data={[
                  { name: t("results.primary"), value: Number(data.totals.primary_paid || 0), color: "#3867D6" },
                  { name: t("results.secondary"), value: Number(data.totals.secondary_paid || 0), color: "#16A39A" },
                  { name: t("results.patient"), value: patient, color: "#B7791F" },
                ]}
              />
              <div className="mt-2">
                <Legend
                  items={[
                    { label: t("results.primary"), color: "#3867D6", value: inr(data.totals.primary_paid) },
                    { label: t("results.secondary"), color: "#16A39A", value: inr(data.totals.secondary_paid) },
                    { label: t("results.youPay"), color: "#B7791F", value: inr(patient) },
                  ]}
                />
              </div>
              <div className="mt-4 grid grid-cols-2 gap-2 border-t border-line pt-3 text-[11px]">
                <div>
                  <p className="text-ink-soft">{t("dashboard.insurersPay")}</p>
                  <p className="mt-0.5 text-[14px] font-bold tabular-nums text-teal">{inr(insurer)}</p>
                </div>
                <div>
                  <p className="text-ink-soft">Patient share</p>
                  <p className="mt-0.5 text-[14px] font-bold tabular-nums text-navy">{billed ? `${Math.round((patient / billed) * 100)}%` : "0%"}</p>
                </div>
              </div>
            </Card>
          </div>

          <div className="mt-4 grid gap-4 lg:grid-cols-[1.35fr_1fr]">
            <Card className="p-5">
              <div className="flex items-start justify-between">
                <div>
                  <h2 className="text-[15px] font-bold">{t("dashboard.graph")}</h2>
                  <p className="mt-0.5 text-[11.5px] text-ink-muted">{t("dashboard.graphSub")}</p>
                </div>
                <Link to="/app/family" className="flex items-center gap-1 text-[11.5px] font-semibold text-brand">
                  <Users className="h-3.5 w-3.5" /> {t("nav.family")}
                </Link>
              </div>
              <div className="mt-4">
                <InsuranceGraph family={family} />
              </div>
            </Card>

            <div className="space-y-4">
              <Card className="p-5">
                <div className="flex items-center justify-between">
                  <h2 className="text-[15px] font-bold">{t("dashboard.attention")}</h2>
                  <Badge tone={data.attention.length ? "amber" : "teal"}>{data.attention.length}</Badge>
                </div>
                {data.attention.length === 0 ? (
                  <p className="mt-3 flex items-center gap-2 text-[12px] text-ink-muted">
                    <ShieldCheck className="h-4 w-4 text-teal" /> {t("dashboard.allClear")}
                  </p>
                ) : (
                  <div className="mt-3 space-y-2">
                    {data.attention.slice(0, 4).map((item) => (
                      <Link
                        key={item.case_id}
                        to={`/app/cases/${item.case_id}${item.status === "awaiting_review" ? "/review" : "/run"}`}
                        className="flex items-center justify-between gap-2 rounded-lg border border-line px-3 py-2 hover:border-amber/40 hover:bg-amber-50/40"
                      >
                        <div className="min-w-0">
                          <p className="truncate text-[12px] font-semibold text-navy">{item.title}</p>
                          <p className="text-[10.5px] text-ink-soft">{item.detail}</p>
                        </div>
                        <ArrowRight className="h-3.5 w-3.5 shrink-0 text-ink-soft" />
                      </Link>
                    ))}
                  </div>
                )}
              </Card>
              <Card className="p-5">
                <h2 className="text-[15px] font-bold">{t("dashboard.youPay")}</h2>
                <p className="mt-2 text-[30px] font-bold tracking-[-0.03em] tabular-nums text-navy">{inr(patient)}</p>
                <p className="mt-1 text-[11.5px] text-ink-muted">
                  {billed > 0 ? `${Math.round((patient / billed) * 100)}% of ${inr(billed)} billed` : "No completed cases yet."}
                </p>
                <div className="mt-3 h-2 overflow-hidden rounded-full bg-slate-100">
                  <div className="h-full rounded-full bg-amber" style={{ width: `${billed ? Math.min(100, (patient / billed) * 100) : 0}%` }} />
                </div>
                <div className="mt-3 flex items-center justify-between text-[10.5px] text-ink-soft">
                  <span>{t("results.patient")}</span>
                  <span>{t("results.insurersPay")}</span>
                </div>
              </Card>
            </div>
          </div>
        </>
      )}

      {!hasCases && data.totals.families > 0 && (
        <div className="mt-4">
          <EmptyState
            title={t("dashboard.noCases")}
            body={t("dashboard.noCasesBody")}
            icon={<Plus className="h-5 w-5" />}
            action={
              <Link to="/app/cases/new">
                <Button>{t("cases.new")}</Button>
              </Link>
            }
          />
        </div>
      )}
    </div>
  );
}
