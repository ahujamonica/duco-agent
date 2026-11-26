import React, { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  ArrowRight,
  BadgeAlert,
  Calculator,
  CheckCircle2,
  ChevronRight,
  Download,
  FileJson,
  FileText,
  Info,
  Play,
  Scale,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  X,
  XCircle,
} from "lucide-react";
import { useApi } from "../lib/useApi";
import { useI18n } from "../lib/i18n";
import { api, downloadFile } from "../lib/api";
import { ResultClaim, ResultLine, Results } from "../lib/types";
import {
  Alert,
  Badge,
  Button,
  Card,
  EmptyState,
  LoadingBlock,
  Modal,
  PageHeader,
  Spinner,
  Stat,
  StatusBadge,
  Term,
  UsageBar,
  cx,
  useToast,
} from "../components/ui";
import { DonutChart, Legend, Waterfall } from "../components/Charts";
import { inr, pct, shortDate } from "../lib/format";

const TABS = [
  ["overview", "results.overview"],
  ["lines", "results.lines"],
  ["gaps", "results.gaps"],
  ["simulator", "results.simulator"],
  ["audit", "results.audit"],
] as const;

export default function CaseResults() {
  const { caseId } = useParams();
  const { t, lang } = useI18n();
  const { notify } = useToast();
  const results = useApi<Results>(caseId ? `/api/cases/${caseId}/results` : null, [caseId]);
  const [tab, setTab] = useState<(typeof TABS)[number][0]>("overview");
  const [explainId, setExplainId] = useState<number | null>(null);

  if (results.loading && !results.data) return <LoadingBlock />;
  if (results.error) return <Alert tone="danger" title={t("common.error")}>{results.error}</Alert>;
  const data = results.data;
  if (!data) return null;

  const totals = data.totals || {};
  const billed = Number(totals.billed || 0);
  const primary = Number(totals.primary_paid || 0);
  const secondary = Number(totals.secondary_paid || 0);
  const patient = Number(totals.patient_liability || 0);
  const adjustments = Number(totals.contractual_adjustment || 0);
  const saving = data.savings.reduce((sum, item) => sum + Number(item.saving || 0), 0);
  const hasResults = data.claims.length > 0;
  const caseStatus = data.case.status;

  if (!hasResults) {
    return (
      <div>
        <PageHeader title={data.case.title} subtitle={t("results.subtitle")} />
        <EmptyState
          title={t("results.noResults")}
          body={t("results.noResultsBody")}
          icon={<Calculator className="h-5 w-5" />}
          action={<Link to={`/app/cases/${caseId}/run`}><Button icon={<Play className="h-4 w-4" />}>{t("run.start")}</Button></Link>}
        />
      </div>
    );
  }

  const download = async (reportId: number, title: string, mime: string) => {
    const extension = mime.includes("pdf")
      ? "pdf"
      : mime.includes("html")
        ? "html"
        : mime.includes("text/plain")
          ? "txt"
          : mime.includes("audio")
            ? "mp3"
            : "json";
    try {
      await downloadFile(`/api/cases/${caseId}/reports/${reportId}/download`, `${title}.${extension}`);
    } catch (error) {
      notify(error instanceof Error ? error.message : "Could not download.", "error");
    }
  };

  return (
    <div>
      <PageHeader
        eyebrow={data.case.family}
        title={data.case.title}
        subtitle={`${t("results.subtitle")} · ${shortDate(data.case.service_date, lang)}`}
        actions={
          <>
            <Badge tone="amber">{t("common.simulated")}</Badge>
            <StatusBadge status={caseStatus} />
            <Link to={`/app/cases/${caseId}/run`}>
              <Button variant="secondary" size="sm">{t("run.title")}</Button>
            </Link>
            <Link to={`/app/cases/${caseId}/letters`}>
              <Button variant="secondary" size="sm" icon={<FileText className="h-3.5 w-3.5" />}>{t("results.letters")}</Button>
            </Link>
            <Button
              size="sm"
              icon={<Download className="h-3.5 w-3.5" />}
              onClick={() => {
                const report = data.reports.find((item) => item.kind === "html") || data.reports[0];
                if (report) download(report.id, report.title, report.mime);
              }}
            >
              {t("results.download")}
            </Button>
          </>
        }
      />

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label={t("results.billed")} value={inr(billed)} tone="navy" />
        <Stat label={t("results.insurersPay")} value={inr(primary + secondary)} tone="teal" hint={`${inr(primary)} primary · ${inr(secondary)} secondary`} />
        <Stat label={t("results.youPay")} value={inr(patient)} tone="amber" hint={billed ? `${Math.round((patient / billed) * 100)}% of the bill` : ""} />
        <Stat label={t("results.savings")} value={inr(saving)} tone="blue" hint={t("results.coordinationNote")} />
      </div>

      <div className="mt-5 flex flex-wrap gap-1 border-b border-line">
        {TABS.map(([key, label]) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            className={cx(
              "relative px-3 py-2 text-[12px] font-semibold transition",
              tab === key ? "text-brand" : "text-ink-muted hover:text-navy"
            )}
          >
            {t(label)}
            {key === "gaps" && data.gaps.length > 0 && (
              <span className="ml-1 rounded-full bg-amber-50 px-1.5 text-[9px] text-amber">{data.gaps.length}</span>
            )}
            {tab === key && <span className="absolute inset-x-2 -bottom-px h-0.5 rounded bg-brand" />}
          </button>
        ))}
      </div>

      {tab === "overview" && (
        <Overview
          data={data}
          billed={billed}
          primary={primary}
          secondary={secondary}
          patient={patient}
          adjustments={adjustments}
          onExplain={setExplainId}
        />
      )}
      {tab === "lines" && <Lines claims={data.claims} onExplain={setExplainId} />}
      {tab === "gaps" && <Gaps data={data} />}
      {tab === "simulator" && <Simulator data={data} />}
      {tab === "audit" && <Audit data={data} onDownload={download} />}

      {explainId != null && caseId && (
        <ExplainModal caseId={caseId} lineId={explainId} onClose={() => setExplainId(null)} />
      )}
    </div>
  );
}

function Overview({
  data,
  billed,
  primary,
  secondary,
  patient,
  adjustments,
  onExplain,
}: {
  data: Results;
  billed: number;
  primary: number;
  secondary: number;
  patient: number;
  adjustments: number;
  onExplain: (id: number) => void;
}) {
  const { t, lang } = useI18n();
  return (
    <div className="mt-4 space-y-4">
      <div className="grid gap-4 lg:grid-cols-[1.25fr_1fr]">
        <Card className="p-5">
          <div className="flex items-start justify-between">
            <div>
              <h2 className="text-[15px] font-bold">{t("results.costFlow")}</h2>
              <p className="mt-0.5 text-[11.5px] text-ink-muted">Billed → allowed → insurers → you</p>
            </div>
            <Badge tone="slate">{data.claims.length} {t("results.claims")}</Badge>
          </div>
          <div className="mt-5">
            <Waterfall
              base={billed}
              items={[
                { label: t("results.billed"), amount: billed, color: "#14243A" },
                { label: t("results.adjustments"), amount: adjustments, color: "#C3CAD6", muted: true },
                { label: t("results.allowed"), amount: Number(data.totals.allowed || 0), color: "#5B6B82" },
                { label: t("results.primary"), amount: primary, color: "#3867D6" },
                { label: t("results.secondary"), amount: secondary, color: "#16A39A" },
                { label: t("results.youPay"), amount: patient, color: "#B7791F" },
              ]}
            />
          </div>
          <div className="mt-4 rounded-lg bg-canvas px-3 py-2 text-[11px] leading-4 text-ink-muted">
            Every figure above comes from the deterministic engine. Select any line to see its arithmetic.
          </div>
        </Card>
        <Card className="p-5">
          <div className="flex items-start justify-between">
            <div>
              <h2 className="text-[15px] font-bold">{t("results.split")}</h2>
              <p className="mt-0.5 text-[11.5px] text-ink-muted">Who pays what</p>
            </div>
          </div>
          <DonutChart
            label={t("results.insurersPay")}
            total={primary + secondary}
            data={[
              { name: t("results.primary"), value: primary, color: "#3867D6" },
              { name: t("results.secondary"), value: secondary, color: "#16A39A" },
            ]}
          />
          <Legend
            items={[
              { label: t("results.primary"), color: "#3867D6", value: inr(primary) },
              { label: t("results.secondary"), color: "#16A39A", value: inr(secondary) },
              { label: t("results.youPay"), color: "#B7791F", value: inr(patient) },
            ]}
          />
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        {data.claims.map((claim) => (
          <Card key={claim.id} className="p-5">
            <div className="flex items-start justify-between gap-2">
              <div>
                <h3 className="text-[14px] font-bold">{claim.patient}</h3>
                <p className="mt-0.5 text-[10.5px] text-ink-muted">
                  {claim.provider || "—"} · {shortDate(claim.service_date, lang)}
                </p>
              </div>
              <div className="text-right">
                <p className="text-[9.5px] uppercase tracking-wide text-ink-soft">{t("results.youPay")}</p>
                <p className="text-[17px] font-bold tabular-nums text-navy">{inr(claim.totals.patient_liability || 0)}</p>
              </div>
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-1.5">
              {claim.order.map((item) => (
                <span key={item.plan_key} className="flex items-center gap-1 rounded-full bg-canvas px-2 py-0.5 text-[9.5px] font-medium text-ink-muted">
                  <span className={cx("h-1.5 w-1.5 rounded-full", item.role === "primary" ? "bg-brand" : "bg-teal")} />
                  {item.role} · {item.rule.replace(/_/g, " ")}
                </span>
              ))}
            </div>
            <div className="mt-3 grid grid-cols-3 gap-2 border-t border-line pt-3 text-[10.5px]">
              <div><p className="text-ink-soft">{t("results.billed")}</p><p className="mt-0.5 text-[12px] font-semibold tabular-nums text-navy">{inr(claim.totals.billed)}</p></div>
              <div><p className="text-ink-soft">{t("results.insurersPay")}</p><p className="mt-0.5 text-[12px] font-semibold tabular-nums text-teal">{inr(claim.totals.insurer_paid)}</p></div>
              <div><p className="text-ink-soft">{t("results.allowed")}</p><p className="mt-0.5 text-[12px] font-semibold tabular-nums text-navy">{inr(claim.totals.allowed)}</p></div>
            </div>
            <div className="mt-3 space-y-1.5">
              {claim.lines.slice(0, 3).map((line) => (
                <button key={line.id} onClick={() => onExplain(line.id)} className="flex w-full items-center justify-between gap-2 rounded-lg px-2 py-1 text-left text-[10.5px] hover:bg-canvas">
                  <span className="truncate text-ink-muted">{line.description}</span>
                  <span className="shrink-0 font-semibold tabular-nums text-navy">{inr(line.patient)}</span>
                  <ChevronRight className="h-3 w-3 shrink-0 text-ink-soft" />
                </button>
              ))}
            </div>
          </Card>
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-[1fr_1fr]">
        <Card className="p-5">
          <h2 className="text-[15px] font-bold">{t("results.preauth")}</h2>
          <div className="mt-3 space-y-2">
            {data.preauth.filter((item) => item.required).length === 0 && (
              <p className="text-[11.5px] text-ink-muted">No pre-authorisation was required.</p>
            )}
            {data.preauth.filter((item) => item.required).map((item) => (
              <div key={item.id} className="rounded-lg border border-line px-3 py-2">
                <div className="flex items-center justify-between gap-2">
                  <p className="text-[11.5px] font-semibold text-navy">{item.insurer}</p>
                  <StatusBadge status={item.status} />
                </div>
                <p className="mt-1 font-mono text-[9.5px] text-ink-soft">{item.reference || "—"}</p>
                {item.reason && <p className="mt-1 text-[10px] leading-4 text-ink-muted">{item.reason}</p>}
              </div>
            ))}
          </div>
          <Link to={`/app/cases/${data.case.id}/letters`} className="mt-3 inline-flex items-center gap-1 text-[11px] font-bold text-brand">
            {t("results.letters")} <ArrowRight className="h-3 w-3" />
          </Link>
        </Card>

        <Card className="p-5">
          <h2 className="text-[15px] font-bold">{t("results.accumulators")}</h2>
          <div className="mt-3 space-y-4">
            {data.accumulators.slice(0, 4).map((row) => (
              <div key={`${row.policy_id}-${row.member_id}`}>
                <div className="flex items-center justify-between text-[11px]">
                  <span className="font-semibold text-navy">{row.member}</span>
                  <span className="text-ink-soft">{row.insurer}</span>
                </div>
                <div className="mt-1.5 space-y-2">
                  <UsageBar label={t("policies.deductible")} used={Number(row.deductible_used)} max={Number(row.deductible)} format={(value) => inr(value)} />
                  <UsageBar label={t("policies.oop")} used={Number(row.oop_used)} max={Number(row.oop_max)} format={(value) => inr(value)} />
                </div>
              </div>
            ))}
          </div>
        </Card>
      </div>

      {data.assumptions.length > 0 && (
        <Card className="p-5">
          <h2 className="text-[15px] font-bold">{t("results.assumptions")}</h2>
          <ul className="mt-2 space-y-1.5">
            {data.assumptions.map((assumption, index) => (
              <li key={index} className="flex items-start gap-2 text-[11.5px] leading-5 text-ink-muted">
                <Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-brand" /> {assumption}
              </li>
            ))}
          </ul>
        </Card>
      )}

      <Alert tone="warning" title={t("results.disclaimer")}>
        {data.disclaimer} Insurer responses in this case came from the local mock sandbox; they are not approvals.
      </Alert>
    </div>
  );
}

function Lines({ claims, onExplain }: { claims: ResultClaim[]; onExplain: (id: number) => void }) {
  const { t } = useI18n();
  return (
    <div className="mt-4 space-y-4">
      {claims.map((claim) => (
        <Card key={claim.id} className="overflow-hidden">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-5 py-3">
            <div>
              <h2 className="text-[14px] font-bold text-navy">{claim.patient}</h2>
              <p className="text-[10.5px] text-ink-soft">{claim.provider} · {claim.bill_number || "no bill number"}</p>
            </div>
            <p className="text-[12px] font-bold tabular-nums text-teal">{inr(claim.totals.patient_liability)} {t("results.youPay")}</p>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[780px] text-left text-[11.5px]">
              <thead>
                <tr className="border-b border-line bg-canvas text-[9.5px] uppercase tracking-[0.06em] text-ink-soft">
                  <th className="px-4 py-2 font-semibold">Service</th>
                  <th className="px-3 py-2 font-semibold">CPT</th>
                  <th className="px-3 py-2 text-right font-semibold">Billed</th>
                  <th className="px-3 py-2 text-right font-semibold">Allowed</th>
                  <th className="px-3 py-2 text-right font-semibold">{t("results.primary")}</th>
                  <th className="px-3 py-2 text-right font-semibold">{t("results.secondary")}</th>
                  <th className="px-3 py-2 text-right font-semibold">{t("results.patient")}</th>
                  <th className="px-4 py-2" />
                </tr>
              </thead>
              <tbody>
                {claim.lines.map((line) => {
                  const primaryPaid = line.plans.filter((plan) => plan.role === "primary").reduce((sum, plan) => sum + Number(plan.plan_paid || 0), 0);
                  const secondaryPaid = line.plans.filter((plan) => plan.role !== "primary").reduce((sum, plan) => sum + Number(plan.plan_paid || 0), 0);
                  return (
                    <tr key={line.id} className="group cursor-pointer border-b border-line/60 last:border-0 hover:bg-brand-50/40" onClick={() => onExplain(line.id)}>
                      <td className="max-w-[280px] px-4 py-2.5">
                        <p className="truncate font-medium text-navy">{line.description}</p>
                        {line.notes.length > 0 && <p className="truncate text-[9.5px] text-ink-soft">{line.notes[0]}</p>}
                      </td>
                      <td className="px-3 py-2.5 font-mono text-[10px] text-ink-muted">{line.cpt_code || "—"}</td>
                      <td className="px-3 py-2.5 text-right tabular-nums text-ink-muted">{inr(line.billed)}</td>
                      <td className="px-3 py-2.5 text-right tabular-nums text-ink-muted">{inr(line.allowed)}</td>
                      <td className="px-3 py-2.5 text-right tabular-nums text-brand">{inr(primaryPaid)}</td>
                      <td className="px-3 py-2.5 text-right tabular-nums text-teal">{inr(secondaryPaid)}</td>
                      <td className="px-3 py-2.5 text-right font-bold tabular-nums text-navy">{inr(line.patient)}</td>
                      <td className="px-4 py-2.5 text-right"><ChevronRight className="ml-auto h-3.5 w-3.5 text-ink-soft group-hover:text-brand" /></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Card>
      ))}
      <p className="text-center text-[10.5px] text-ink-soft">{t("results.clickLine")}</p>
    </div>
  );
}

function Gaps({ data }: { data: Results }) {
  const { t } = useI18n();
  const icons = {
    blocking: <XCircle className="h-4 w-4 text-danger" />,
    action: <ShieldAlert className="h-4 w-4 text-amber" />,
    info: <Info className="h-4 w-4 text-brand" />,
  } as Record<string, React.ReactNode>;
  return (
    <div className="mt-4">
      {data.gaps.length === 0 ? (
        <EmptyState title={t("results.gaps")} body={t("results.gapEmpty")} icon={<ShieldCheck className="h-5 w-5" />} />
      ) : (
        <div className="grid gap-3 md:grid-cols-2">
          {data.gaps.map((gap, index) => (
            <Card key={index} className="p-4">
              <div className="flex items-start gap-3">
                <span className="mt-0.5">{icons[gap.severity] || icons.info}</span>
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="text-[12.5px] font-bold text-navy">{gap.title}</p>
                    <Badge tone={gap.severity === "blocking" ? "red" : gap.severity === "action" ? "amber" : "blue"}>{gap.severity}</Badge>
                  </div>
                  <p className="mt-1 text-[11px] leading-4 text-ink-muted">{gap.detail}</p>
                  {gap.action && <p className="mt-1.5 rounded-lg bg-canvas px-2 py-1.5 text-[10.5px] text-ink-muted">Action: {gap.action}</p>}
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

function Simulator({ data }: { data: Results }) {
  const { t } = useI18n();
  const { notify } = useToast();
  const policies = useMemo(() => {
    const seen = new Map<number, any>();
    for (const row of data.accumulators) if (!seen.has(row.policy_id)) seen.set(row.policy_id, row);
    return Array.from(seen.values());
  }, [data.accumulators]);
  const [policyId, setPolicyId] = useState<number>(policies[0]?.policy_id || 0);
  const selected = policies.find((policy) => policy.policy_id === policyId);
  const [overrides, setOverrides] = useState({ deductible: "", coinsurance: "", oop: "" });
  const [result, setResult] = useState<any>(null);
  const [busy, setBusy] = useState(false);

  const run = async () => {
    setBusy(true);
    try {
      const payload: any = { policies: {} };
      if (policyId) {
        payload.policies[String(policyId)] = {
          ...(overrides.deductible !== "" ? { deductible: overrides.deductible } : {}),
          ...(overrides.coinsurance !== "" ? { coinsurance_member: String(Number(overrides.coinsurance) / 100) } : {}),
          ...(overrides.oop !== "" ? { oop_max: overrides.oop } : {}),
        };
      }
      const response = await api.post(`/api/cases/${data.case.id}/simulate`, payload);
      setResult(response);
    } catch (error) {
      notify(error instanceof Error ? error.message : "Could not run the simulation.", "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mt-4 grid gap-4 lg:grid-cols-[380px_1fr]">
      <Card className="p-5">
        <div className="flex items-start gap-2">
          <Sparkles className="mt-0.5 h-4 w-4 text-brand" />
          <div>
            <h2 className="text-[15px] font-bold">{t("results.simTitle")}</h2>
            <p className="mt-1 text-[11px] leading-4 text-ink-muted">{t("results.simSub")}</p>
          </div>
        </div>
        <div className="mt-4 space-y-3">
          <div>
            <label className="text-[11px] font-semibold text-navy">Policy</label>
            <select
              value={policyId}
              onChange={(event) => { setPolicyId(Number(event.target.value)); setOverrides({ deductible: "", coinsurance: "", oop: "" }); setResult(null); }}
              className="mt-1 w-full rounded-lg border border-line px-3 py-2 text-[12px]"
            >
              {policies.map((policy) => (
                <option key={policy.policy_id} value={policy.policy_id}>{policy.insurer} · {policy.plan_name}</option>
              ))}
            </select>
          </div>
          {selected && (
            <div className="grid grid-cols-3 gap-2">
              <div>
                <label className="text-[10px] text-ink-soft">{t("results.deductible")}</label>
                <input
                  type="number"
                  placeholder={String(Math.round(Number(selected.deductible)))}
                  value={overrides.deductible}
                  onChange={(event) => setOverrides({ ...overrides, deductible: event.target.value })}
                  className="mt-1 w-full rounded-lg border border-line px-2 py-1.5 text-[11.5px]"
                />
              </div>
              <div>
                <label className="text-[10px] text-ink-soft">{t("results.coinsurance")} %</label>
                <input
                  type="number"
                  placeholder={String(Math.round(Number(selected.coinsurance_member) * 100))}
                  value={overrides.coinsurance}
                  onChange={(event) => setOverrides({ ...overrides, coinsurance: event.target.value })}
                  className="mt-1 w-full rounded-lg border border-line px-2 py-1.5 text-[11.5px]"
                />
              </div>
              <div>
                <label className="text-[10px] text-ink-soft">{t("results.oop")}</label>
                <input
                  type="number"
                  placeholder={String(Math.round(Number(selected.oop_max)))}
                  value={overrides.oop}
                  onChange={(event) => setOverrides({ ...overrides, oop: event.target.value })}
                  className="mt-1 w-full rounded-lg border border-line px-2 py-1.5 text-[11.5px]"
                />
              </div>
            </div>
          )}
          <Button className="w-full" loading={busy} onClick={run} icon={<Play className="h-3.5 w-3.5" />}>{t("results.simRun")}</Button>
          <button
            onClick={() => { setOverrides({ deductible: "", coinsurance: "", oop: "" }); setResult(null); }}
            className="w-full text-center text-[10.5px] font-semibold text-ink-soft hover:text-navy"
          >
            {t("results.simReset")}
          </button>
        </div>
      </Card>

      <Card className="p-5">
        {!result ? (
          <div className="flex h-full min-h-[280px] flex-col items-center justify-center text-center">
            <Scale className="h-7 w-7 text-ink-soft" />
            <p className="mt-2 text-[12.5px] font-semibold text-navy">Hypothetical only</p>
            <p className="mt-1 max-w-xs text-[11px] leading-4 text-ink-muted">Change a term and run the simulation. The stored claim never changes.</p>
          </div>
        ) : (
          <div>
            <div className="flex items-center gap-2">
              <Badge tone="amber">{t("results.simNote")}</Badge>
            </div>
            <div className="mt-4 grid grid-cols-2 gap-3">
              <div className="rounded-lg bg-canvas p-3">
                <p className="text-[10px] uppercase tracking-wide text-ink-soft">{t("results.simBaseline")}</p>
                <p className="mt-1 text-[16px] font-bold tabular-nums text-navy">{inr(result.baseline.patient_liability)}</p>
              </div>
              <div className="rounded-lg bg-brand-50 p-3">
                <p className="text-[10px] uppercase tracking-wide text-brand">{t("results.simHypo")}</p>
                <p className="mt-1 text-[16px] font-bold tabular-nums text-brand-600">{inr(result.result.patient_liability)}</p>
              </div>
            </div>
            <div className="mt-3 flex items-center justify-between rounded-lg border border-line px-3 py-2">
              <span className="text-[11px] text-ink-muted">{t("results.simDelta")} · {t("results.youPay")}</span>
              <span className={cx("text-[13px] font-bold tabular-nums", Number(result.difference.patient_liability) <= 0 ? "text-teal" : "text-danger")}>
                {Number(result.difference.patient_liability) > 0 ? "+" : ""}{inr(result.difference.patient_liability)}
              </span>
            </div>
            <div className="mt-4 space-y-2">
              {result.result.claims.map((claim: any) => (
                <div key={claim.claim_id} className="flex items-center justify-between rounded-lg bg-canvas px-3 py-2 text-[11px]">
                  <span className="text-ink-muted">{claim.patient}</span>
                  <span className="font-semibold tabular-nums text-navy">{inr(claim.totals.patient_liability)}</span>
                </div>
              ))}
            </div>
            <p className="mt-3 text-[10px] leading-4 text-ink-soft">{result.note}</p>
          </div>
        )}
      </Card>
    </div>
  );
}

function Audit({ data, onDownload }: { data: Results; onDownload: (id: number, title: string, mime: string) => void }) {
  const { t } = useI18n();
  const failure = (data.invariants || []).some((item: any) => item.passed === false);
  return (
    <div className="mt-4 space-y-4">
      <div className="grid gap-3 sm:grid-cols-3">
        <Card className="p-4"><p className="text-[10px] uppercase tracking-wide text-ink-soft">Agent events</p><p className="mt-1 text-[22px] font-bold tabular-nums text-navy">{data.audit.events}</p></Card>
        <Card className="p-4"><p className="text-[10px] uppercase tracking-wide text-ink-soft">Adjudications</p><p className="mt-1 text-[22px] font-bold tabular-nums text-navy">{data.audit.adjudications}</p></Card>
        <Card className="p-4"><p className="text-[10px] uppercase tracking-wide text-ink-soft">Insurer calls</p><p className="mt-1 text-[22px] font-bold tabular-nums text-navy">{data.audit.api_calls}</p></Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="p-5">
          <div className="flex items-center justify-between">
            <h2 className="text-[15px] font-bold">{t("results.invariants")}</h2>
            {failure ? <Badge tone="red">{t("results.failed")}</Badge> : <Badge tone="teal">{t("results.invariantPass")}</Badge>}
          </div>
          <div className="mt-3 space-y-1.5">
            {(data.invariants || []).map((invariant: any, index: number) => (
              <div key={`case-${index}`} className="flex items-start gap-2 text-[10.5px]">
                {invariant.passed !== false ? <CheckCircle2 className="mt-0.5 h-3 w-3 shrink-0 text-teal" /> : <XCircle className="mt-0.5 h-3 w-3 shrink-0 text-danger" />}
                <span className="text-ink-muted"><b className="text-navy">{invariant.name}:</b> {invariant.detail || "passed"}</span>
              </div>
            ))}
            {data.claims.map((claim) => (
              <div key={claim.id}>
                <p className="mt-2 text-[10.5px] font-semibold text-ink-soft">{claim.patient}</p>
                {claim.invariants.map((invariant, index) => (
                  <div key={index} className="mt-1 flex items-start gap-2 text-[10.5px]">
                    {invariant.passed ? <CheckCircle2 className="mt-0.5 h-3 w-3 shrink-0 text-teal" /> : <XCircle className="mt-0.5 h-3 w-3 shrink-0 text-danger" />}
                    <span className="text-ink-muted"><b className="text-navy">{invariant.name}:</b> {invariant.detail}</span>
                  </div>
                ))}
              </div>
            ))}
            {data.claims.every((claim) => claim.invariants.length === 0) && (
              <p className="flex items-center gap-2 text-[11px] text-ink-muted"><CheckCircle2 className="h-4 w-4 text-teal" /> All financial invariants passed.</p>
            )}
          </div>
        </Card>

        <Card className="p-5">
          <h2 className="text-[15px] font-bold">{t('results.download')}</h2>
          <div className="mt-3 space-y-2">
            {data.reports.map((report) => (
              <button
                key={report.id}
                onClick={() => onDownload(report.id, report.title, report.mime)}
                className="flex w-full items-center justify-between gap-2 rounded-lg border border-line px-3 py-2 text-left hover:border-brand/30 hover:bg-brand-50/30"
              >
                <span className="flex items-center gap-2 text-[11.5px] font-medium text-navy">
                  {report.kind === "json" ? <FileJson className="h-3.5 w-3.5 text-brand" /> : <FileText className="h-3.5 w-3.5 text-brand" />}
                  {report.title}
                </span>
                <Download className="h-3.5 w-3.5 text-ink-soft" />
              </button>
            ))}
          </div>
          <Link to={`/app/cases/${data.case.id}/run`} className="mt-3 inline-flex items-center gap-1 text-[11px] font-bold text-brand">
            {t("results.openTrace")} <ArrowRight className="h-3 w-3" />
          </Link>
        </Card>
      </div>

      {data.assumptions.length > 0 && (
        <Card className="p-5">
          <h2 className="text-[15px] font-bold">{t("results.assumptions")}</h2>
          <ul className="mt-2 space-y-1.5">
            {data.assumptions.map((assumption, index) => (
              <li key={index} className="text-[11.5px] leading-5 text-ink-muted">— {assumption}</li>
            ))}
          </ul>
        </Card>
      )}
      <Alert tone="warning" title={t("results.disclaimer")}>{data.disclaimer}</Alert>
    </div>
  );
}

function ExplainModal({ caseId, lineId, onClose }: { caseId: string; lineId: number; onClose: () => void }) {
  const { t } = useI18n();
  const explain = useApi<any>(`/api/cases/${caseId}/lines/${lineId}/explain`, [caseId, lineId]);
  return (
    <Modal open onClose={onClose} title={t("results.lineDetail")} width="max-w-xl">
      {explain.loading && !explain.data ? (
        <div className="flex justify-center py-8"><Spinner /></div>
      ) : explain.error ? (
        <Alert tone="danger">{explain.error}</Alert>
      ) : explain.data ? (
        <div>
          <p className="text-[13px] font-semibold text-navy">{explain.data.line.description}</p>
          <p className="mt-0.5 text-[10.5px] text-ink-soft">{explain.data.patient} · CPT {explain.data.line.cpt_code || "—"}</p>
          <div className="mt-4 space-y-1.5">
            {explain.data.steps.map((step: any, index: number) => (
              <div key={index} className="flex items-start justify-between gap-3 rounded-lg border border-line px-3 py-2">
                <div>
                  <p className="text-[11.5px] font-semibold text-navy">{step.label}</p>
                  <p className="mt-0.5 text-[10px] leading-4 text-ink-soft">{step.explanation}</p>
                </div>
                <p className="shrink-0 text-[12px] font-bold tabular-nums text-navy">{inr(step.amount)}</p>
              </div>
            ))}
          </div>
          <div className={cx("mt-3 flex items-center justify-between rounded-lg px-3 py-2 text-[11px]", explain.data.calculation.check ? "bg-teal-50 text-[#0B5B56]" : "bg-danger-50 text-danger")}>
            <span>{explain.data.calculation.check ? "The line reconciles." : "The line does not reconcile."}</span>
            <span className="font-semibold">{inr(explain.data.calculation.patient)} {t("results.youPay")}</span>
          </div>
        </div>
      ) : null}
    </Modal>
  );
}
