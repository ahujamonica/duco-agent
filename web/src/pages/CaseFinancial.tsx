import React from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, CheckCircle2, Download, XCircle } from "lucide-react";
import { useApi } from "../lib/useApi";
import { useI18n } from "../lib/i18n";
import { downloadFile } from "../lib/api";
import { Results } from "../lib/types";
import { Alert, Badge, Button, Card, EmptyState, LoadingBlock, PageHeader, useToast } from "../components/ui";
import { inr } from "../lib/format";

export default function CaseFinancial() {
  const { caseId } = useParams();
  const { t } = useI18n();
  const { notify } = useToast();
  const results = useApi<Results>(caseId ? `/api/cases/${caseId}/results` : null, [caseId]);

  if (results.loading && !results.data) return <LoadingBlock />;
  if (results.error) return <Alert tone="danger">{results.error}</Alert>;
  const data = results.data;
  if (!data) return null;

  const jsonReport = data.reports.find((report) => report.kind === "json");

  return (
    <div>
      <Link to={`/app/cases/${caseId}`} className="mb-4 inline-flex items-center gap-1 text-[11.5px] font-semibold text-ink-muted hover:text-navy">
        <ArrowLeft className="h-3.5 w-3.5" /> {t("results.title")}
      </Link>
      <PageHeader
        eyebrow={data.case.family}
        title={t("financial.title")}
        subtitle={`${data.case.title} · ${t("financial.subtitle")}`}
        actions={
          jsonReport ? (
            <Button
              variant="secondary"
              icon={<Download className="h-4 w-4" />}
              onClick={async () => {
                try {
                  await downloadFile(`/api/cases/${caseId}/reports/${jsonReport.id}/download`, "financial-breakdown.json");
                } catch (error) {
                  notify(error instanceof Error ? error.message : "Could not download.", "error");
                }
              }}
            >
              {t("financial.export")}
            </Button>
          ) : undefined
        }
      />

      {data.claims.length === 0 ? (
        <EmptyState title={t("financial.empty")} body={t("results.noResultsBody")} action={<Link to={`/app/cases/${caseId}/run`}><Button>{t("run.start")}</Button></Link>} />
      ) : (
        <div className="space-y-4">
          {data.claims.map((claim) => (
            <Card key={claim.id} className="overflow-hidden">
              <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-5 py-3">
                <div>
                  <h2 className="text-[14px] font-bold text-navy">{claim.patient}</h2>
                  <p className="text-[10.5px] text-ink-soft">{claim.provider} · {claim.bill_number || "—"}</p>
                </div>
                <p className="text-[13px] font-bold tabular-nums text-navy">{inr(claim.totals.billed)} billed</p>
              </div>

              <div className="overflow-x-auto">
                <table className="w-full min-w-[900px] text-left text-[11px]">
                  <thead>
                    <tr className="border-b border-line bg-canvas text-[9px] uppercase tracking-[0.06em] text-ink-soft">
                      <th className="px-4 py-2 font-semibold">Service</th>
                      <th className="px-2 py-2 text-right font-semibold">Billed</th>
                      {claim.plans.map((plan: any) => (
                        <th key={plan.plan_key} className="px-2 py-2 text-right font-semibold">
                          {plan.insurer}<br /><span className="font-normal normal-case">{plan.role}</span>
                        </th>
                      ))}
                      <th className="px-2 py-2 text-right font-semibold">Adjustment</th>
                      <th className="px-4 py-2 text-right font-semibold">You pay</th>
                    </tr>
                  </thead>
                  <tbody>
                    {claim.lines.map((line) => (
                      <tr key={line.id} className="border-b border-line/60">
                        <td className="max-w-[260px] px-4 py-2">
                          <p className="truncate text-navy">{line.description}</p>
                          <p className="text-[9px] text-ink-soft">{line.cpt_code || "no code"} · {line.category}</p>
                        </td>
                        <td className="px-2 py-2 text-right tabular-nums text-ink-muted">{inr(line.billed)}</td>
                        {claim.plans.map((plan: any) => {
                          const detail = line.plans.find((item) => item.plan_key === plan.plan_key);
                          return (
                            <td key={plan.plan_key} className="px-2 py-2 text-right tabular-nums">
                              <span className="font-semibold text-navy">{inr(detail?.plan_paid || 0)}</span>
                              <span className="block text-[8.5px] text-ink-soft">
                                ded {inr(detail?.deductible || 0)} · coins {inr(detail?.coinsurance || 0)}
                              </span>
                            </td>
                          );
                        })}
                        <td className="px-2 py-2 text-right tabular-nums text-ink-soft">{inr(line.contractual)}</td>
                        <td className="px-4 py-2 text-right font-bold tabular-nums text-navy">{inr(line.patient)}</td>
                      </tr>
                    ))}
                  </tbody>
                  <tfoot>
                    <tr className="bg-canvas text-[10.5px]">
                      <td className="px-4 py-2.5 font-semibold text-navy">Total</td>
                      <td className="px-2 py-2.5 text-right font-semibold tabular-nums text-navy">{inr(claim.totals.billed)}</td>
                      {claim.plans.map((plan: any) => (
                        <td key={plan.plan_key} className="px-2 py-2.5 text-right font-semibold tabular-nums text-teal">{inr(plan.plan_paid)}</td>
                      ))}
                      <td className="px-2 py-2.5 text-right font-semibold tabular-nums text-ink-soft">{inr(claim.totals.contractual_adjustment)}</td>
                      <td className="px-4 py-2.5 text-right font-bold tabular-nums text-navy">{inr(claim.totals.patient_liability)}</td>
                    </tr>
                  </tfoot>
                </table>
              </div>

              <div className="grid gap-3 border-t border-line p-4 sm:grid-cols-2 lg:grid-cols-4">
                {claim.plans.map((plan: any) => (
                  <div key={plan.plan_key} className="rounded-lg border border-line p-3">
                    <div className="flex items-center justify-between">
                      <p className="text-[11px] font-semibold text-navy">{plan.insurer}</p>
                      <Badge tone={plan.role === "primary" ? "blue" : "teal"}>{plan.role}</Badge>
                    </div>
                    <p className="mt-1 font-mono text-[9px] text-ink-soft">{plan.policy_number}</p>
                    <dl className="mt-2 space-y-1 text-[10px]">
                      <div className="flex justify-between"><dt className="text-ink-soft">Allowed</dt><dd className="font-semibold tabular-nums">{inr(plan.allowed_total)}</dd></div>
                      <div className="flex justify-between"><dt className="text-ink-soft">Deductible</dt><dd className="tabular-nums">{inr(plan.deductible_total)}</dd></div>
                      <div className="flex justify-between"><dt className="text-ink-soft">Co-insurance</dt><dd className="tabular-nums">{inr(plan.coinsurance_total)}</dd></div>
                      <div className="flex justify-between"><dt className="text-ink-soft">Penalty</dt><dd className="tabular-nums">{inr(plan.penalty_total)}</dd></div>
                      <div className="flex justify-between border-t border-line pt-1"><dt className="font-semibold text-navy">Paid</dt><dd className="font-bold tabular-nums text-teal">{inr(plan.plan_paid)}</dd></div>
                    </dl>
                  </div>
                ))}
                <div className="rounded-lg border border-amber/25 bg-amber-50 p-3">
                  <p className="text-[10px] font-semibold uppercase tracking-wide text-amber">Patient</p>
                  <p className="mt-1 text-[17px] font-bold tabular-nums text-navy">{inr(claim.totals.patient_liability)}</p>
                  <p className="mt-1 text-[9.5px] leading-4 text-[#6B4A10]">After every coordinated payment and adjustment.</p>
                </div>
              </div>

              <div className="border-t border-line px-4 py-3">
                <div className="flex flex-wrap gap-x-5 gap-y-1">
                  {claim.invariants.map((invariant, index) => (
                    <span key={index} className={`flex items-center gap-1 text-[9.5px] ${invariant.passed ? "text-[#0B5B56]" : "text-danger"}`}>
                      {invariant.passed ? <CheckCircle2 className="h-3 w-3" /> : <XCircle className="h-3 w-3" />}
                      {invariant.name}
                    </span>
                  ))}
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
