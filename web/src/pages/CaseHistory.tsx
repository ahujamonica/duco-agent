import React, { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, FolderKanban, Plus, Sparkles } from "lucide-react";
import { useApi } from "../lib/useApi";
import { useI18n } from "../lib/i18n";
import { useAuth } from "../lib/auth";
import { Badge, Button, Card, EmptyState, LoadingBlock, PageHeader, Select, StatusBadge } from "../components/ui";
import { ago, inr, shortDate } from "../lib/format";

interface CaseRow {
  id: number;
  title: string;
  status: string;
  family_name: string;
  provider_name: string;
  service_date: string | null;
  updated_at: string;
  totals: Record<string, string>;
  claim_count: number;
  evidence_count: number;
}

export default function CaseHistory() {
  const { t, lang } = useI18n();
  const { user } = useAuth();
  const isDemo = user?.email === "demo@duco.health";
  const cases = useApi<{ cases: CaseRow[] }>("/api/cases");
  const demo = useApi<{ seeded: boolean; cases: { id: number; title: string; status: string }[] }>(
    isDemo ? "/api/demo/status" : null
  );
  const [status, setStatus] = useState("all");

  const rows = useMemo(() => {
    const list = cases.data?.cases || [];
    return status === "all" ? list : list.filter((item) => item.status === status);
  }, [cases.data, status]);

  if (cases.loading && !cases.data) return <LoadingBlock />;

  return (
    <div>
      <PageHeader
        title={t("cases.title")}
        subtitle={t("cases.subtitle")}
        actions={
          <>
            <Select value={status} onChange={(event) => setStatus(event.target.value)} className="w-[160px]">
              <option value="all">{t("cases.allStatuses")}</option>
              <option value="draft">Draft</option>
              <option value="ready">Ready</option>
              <option value="running">Running</option>
              <option value="awaiting_review">Needs review</option>
              <option value="complete">Complete</option>
              <option value="failed">Needs attention</option>
            </Select>
            <Link to="/app/cases/new">
              <Button icon={<Plus className="h-4 w-4" />}>{t("cases.new")}</Button>
            </Link>
          </>
        }
      />

      {isDemo && (demo.data?.cases.length || 0) > 0 && (
        <Card className="mb-5 border-amber/25 bg-amber-50/50 p-4">
          <div className="flex items-start gap-2">
            <Sparkles className="mt-0.5 h-4 w-4 text-amber" />
            <div>
              <p className="text-[12.5px] font-bold text-[#6B4A10]">Five demo scenarios, one engine</p>
              <p className="mt-0.5 text-[11px] leading-5 text-[#6B4A10]/80">
                Open any case and press Run analysis. The scenarios use the same tables, agents and calculation engine as a live case — only the fixtures differ.
              </p>
              <div className="mt-2.5 flex flex-wrap gap-1.5">
                {demo.data!.cases.map((item) => (
                  <Link
                    key={item.id}
                    to={`/app/cases/${item.id}${item.status === "complete" ? "" : item.status === "awaiting_review" ? "/review" : "/run"}`}
                    className="flex items-center gap-1.5 rounded-full border border-amber/30 bg-white px-2.5 py-1 text-[10.5px] font-semibold text-[#6B4A10] hover:border-amber"
                  >
                    {item.title.length > 42 ? `${item.title.slice(0, 42)}…` : item.title}
                    <StatusBadge status={item.status} />
                  </Link>
                ))}
              </div>
            </div>
          </div>
        </Card>
      )}

      {rows.length === 0 ? (
        <EmptyState
          title={t("cases.noCases")}
          body={t("cases.noCasesBody")}
          icon={<FolderKanban className="h-5 w-5" />}
          action={<Link to="/app/cases/new"><Button icon={<Plus className="h-4 w-4" />}>{t("cases.new")}</Button></Link>}
        />
      ) : (
        <Card className="overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] text-left text-[11.5px]">
              <thead>
                <tr className="border-b border-line bg-canvas text-[9.5px] uppercase tracking-[0.06em] text-ink-soft">
                  <th className="px-4 py-2.5 font-semibold">Case</th>
                  <th className="px-3 py-2.5 font-semibold">{t("common.status")}</th>
                  <th className="px-3 py-2.5 text-right font-semibold">{t("cases.billed")}</th>
                  <th className="px-3 py-2.5 text-right font-semibold">{t("cases.youPay")}</th>
                  <th className="px-3 py-2.5 font-semibold">{t("cases.updated")}</th>
                  <th className="px-4 py-2.5" />
                </tr>
              </thead>
              <tbody>
                {rows.map((item) => {
                  const target =
                    item.status === "complete"
                      ? `/app/cases/${item.id}`
                      : item.status === "awaiting_review"
                        ? `/app/cases/${item.id}/review`
                        : `/app/cases/${item.id}/run`;
                  return (
                    <tr key={item.id} className="group border-b border-line/70 last:border-0 hover:bg-brand-50/30">
                      <td className="px-4 py-3">
                        <Link to={target}>
                          <p className="font-semibold text-navy group-hover:text-brand">{item.title}</p>
                          <p className="mt-0.5 text-[10px] text-ink-soft">
                            {item.family_name} · {item.provider_name || "—"} · {shortDate(item.service_date, lang)} · {item.claim_count} claims
                          </p>
                        </Link>
                      </td>
                      <td className="px-3 py-3"><StatusBadge status={item.status} /></td>
                      <td className="px-3 py-3 text-right tabular-nums text-ink-muted">{inr(item.totals?.billed || 0)}</td>
                      <td className="px-3 py-3 text-right font-semibold tabular-nums text-navy">{inr(item.totals?.patient_liability || 0)}</td>
                      <td className="px-3 py-3 text-[10px] text-ink-soft">{ago(item.updated_at)}</td>
                      <td className="px-4 py-3 text-right">
                        <Link to={target} className="inline-flex items-center gap-1 text-[10.5px] font-bold text-brand">
                          Open <ArrowRight className="h-3 w-3" />
                        </Link>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  );
}
