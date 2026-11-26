import React, { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, Clock3, FileText, Pencil, Trash2 } from "lucide-react";
import { useApi } from "../lib/useApi";
import { useI18n } from "../lib/i18n";
import { api } from "../lib/api";
import { Family, Policy } from "../lib/types";
import {
  Alert,
  Badge,
  Button,
  Card,
  LoadingBlock,
  Modal,
  PageHeader,
  StatusBadge,
  Term,
  UsageBar,
  useToast,
} from "../components/ui";
import { inr, pct, shortDate } from "../lib/format";
import { PolicyForm } from "../components/PolicyForm";

export default function PolicyDetail() {
  const { policyId } = useParams();
  const { t, lang } = useI18n();
  const { notify } = useToast();
  const navigate = useNavigate();
  const policy = useApi<Policy>(policyId ? `/api/policies/${policyId}` : null, [policyId]);
  const accumulators = useApi<{ accumulators: any[]; version: number }>(
    policyId ? `/api/policies/${policyId}/accumulators` : null,
    [policyId]
  );
  const family = useApi<Family>(policy.data ? `/api/families/${policy.data.family_id}` : null, [policy.data?.family_id]);
  const [editing, setEditing] = useState(false);
  const [deleting, setDeleting] = useState(false);

  if (policy.loading && !policy.data) return <LoadingBlock />;
  if (policy.error) return <Alert tone="danger">{policy.error}</Alert>;
  if (!policy.data) return null;
  const item = policy.data;
  const terms = item.current_version?.terms;

  const remove = async () => {
    if (!window.confirm(t("policies.deleteConfirm"))) return;
    setDeleting(true);
    try {
      await api.del(`/api/policies/${item.id}`);
      notify("Policy deleted.", "success");
      navigate("/app/policies");
    } catch (error) {
      notify(error instanceof Error ? error.message : "Could not delete the policy.", "error");
    } finally {
      setDeleting(false);
    }
  };

  const fields = [
    { label: "Sum insured", value: inr(terms?.sum_insured || 0), term: "claim" },
    { label: t("policies.deductible"), value: inr(terms?.deductible || 0), term: "deductible" },
    { label: t("policies.coinsurance"), value: pct(terms?.coinsurance_member || 0), term: "coinsurance" },
    { label: t("policies.oop"), value: inr(terms?.oop_max || 0), term: "oop" },
    { label: t("policies.annualLimit"), value: inr(terms?.annual_limit || 0), term: "claim" },
    { label: t("policies.preauthThreshold"), value: inr(terms?.preauth_threshold || 0), term: "preauth" },
    { label: t("policies.penalty"), value: pct(terms?.preauth_penalty_rate || 0), term: "preauth" },
    { label: t("policies.waiting"), value: `${terms?.waiting_period_days ?? 0} days`, term: "waiting" },
  ];

  return (
    <div>
      <Link to="/app/policies" className="mb-4 inline-flex items-center gap-1 text-[11.5px] font-semibold text-ink-muted hover:text-navy">
        <ArrowLeft className="h-3.5 w-3.5" /> {t("policies.title")}
      </Link>
      <PageHeader
        eyebrow={family.data?.name || ""}
        title={item.insurer_name}
        subtitle={`${item.plan_name} · ${item.policy_number}`}
        actions={
          <>
            <StatusBadge status={item.status} />
            <Button variant="secondary" onClick={() => setEditing(true)} icon={<Pencil className="h-4 w-4" />}>{t("common.edit")}</Button>
            <Button variant="ghost" loading={deleting} onClick={remove} icon={<Trash2 className="h-4 w-4" />}>{t("common.delete")}</Button>
          </>
        }
      />

      <div className="grid gap-4 lg:grid-cols-[1.4fr_1fr]">
        <Card className="p-5">
          <div className="flex items-center justify-between">
            <h2 className="text-[15px] font-bold">{t("policies.terms")}</h2>
            <Badge tone="blue">v{item.current_version?.version}</Badge>
          </div>
          <div className="mt-4 grid grid-cols-2 gap-x-4 gap-y-4 sm:grid-cols-4">
            {fields.map((field) => (
              <div key={field.label}>
                <p className="text-[10.5px] text-ink-soft">
                  <Term term={field.term}>{field.label}</Term>
                </p>
                <p className="mt-1 text-[14px] font-bold tabular-nums text-navy">{field.value}</p>
              </div>
            ))}
          </div>
          <div className="mt-5 grid gap-2 border-t border-line pt-4 text-[11.5px] text-ink-muted sm:grid-cols-2">
            <p>Policy period: <span className="font-semibold text-navy">{shortDate(item.start_date, lang)} → {shortDate(item.end_date, lang)}</span></p>
            <p>Policyholder: <span className="font-semibold text-navy">{item.policyholder_name || "—"}</span></p>
            <p>Network: <span className="font-semibold text-navy">{terms?.network_only ? "Network hospitals only" : "Network and reimbursement"}</span></p>
            <p>Pre-authorisation: <span className="font-semibold text-navy">{terms?.preauth_always ? "Every admission" : "Above threshold or listed codes"}</span></p>
          </div>
          {(terms?.exclusions?.length || 0) > 0 && (
            <div className="mt-4">
              <p className="text-[11px] font-bold uppercase tracking-[0.08em] text-ink-soft">{t("policies.exclusions")}</p>
              <div className="mt-1.5 flex flex-wrap gap-1.5">
                {terms!.exclusions.map((exclusion: any, index: number) => (
                  <span key={index} className="rounded-full bg-danger-50 px-2 py-0.5 text-[10px] font-medium text-danger">
                    {exclusion.label || exclusion.keyword || exclusion}
                  </span>
                ))}
              </div>
            </div>
          )}
          {(terms?.sublimits?.length || 0) > 0 && (
            <div className="mt-4">
              <p className="text-[11px] font-bold uppercase tracking-[0.08em] text-ink-soft">{t("policies.sublimits")}</p>
              <div className="mt-1.5 space-y-1">
                {terms!.sublimits.map((sub: any) => (
                  <div key={sub.key} className="flex items-center justify-between rounded-lg bg-canvas px-2.5 py-1.5 text-[11px]">
                    <span className="text-ink-muted">{sub.label}</span>
                    <span className="font-semibold tabular-nums text-navy">{inr(sub.limit)}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </Card>

        <Card className="p-5">
          <h2 className="text-[15px] font-bold">{t("policies.members")}</h2>
          <div className="mt-3 space-y-2">
            {item.members.map((member) => (
              <div key={member.member_id} className="flex items-center justify-between rounded-lg border border-line px-3 py-2">
                <div>
                  <p className="text-[12px] font-semibold text-navy">{member.name}</p>
                  <p className="text-[10px] capitalize text-ink-soft">{member.relation || "member"}</p>
                </div>
                <Badge tone={member.role === "policyholder" ? "blue" : "slate"}>{member.role}</Badge>
              </div>
            ))}
          </div>
          <div className="mt-4 flex items-center justify-between text-[10.5px] text-ink-soft">
            <span>{item.version_count} versions</span>
            <Link to={`/app/family`} className="font-semibold text-brand">Manage members</Link>
          </div>
        </Card>
      </div>

      <Card className="mt-4 p-5">
        <div className="flex items-start justify-between">
          <div>
            <h2 className="text-[15px] font-bold">{t("policies.accumulators")}</h2>
            <p className="mt-0.5 text-[11.5px] text-ink-muted">{t("policies.accumulatorsBody")}</p>
          </div>
          <Badge tone="amber">v{accumulators.data?.version || item.current_version?.version}</Badge>
        </div>
        {accumulators.loading && !accumulators.data ? (
          <div className="py-6"><LoadingBlock /></div>
        ) : (
          <div className="mt-4 grid gap-4 md:grid-cols-2">
            {(accumulators.data?.accumulators || []).map((row) => (
              <div key={row.member_id} className="rounded-xl border border-line p-4">
                <div className="flex items-center justify-between">
                  <p className="text-[12.5px] font-semibold text-navy">{row.member}</p>
                  <Badge tone={row.role === "policyholder" ? "blue" : "slate"}>{row.role}</Badge>
                </div>
                <div className="mt-3 space-y-2.5">
                  <UsageBar label={t("policies.deductible")} used={Number(row.deductible_used)} max={Number(row.deductible)} format={(value) => inr(value)} />
                  <UsageBar label={t("policies.oop")} used={Number(row.oop_used)} max={Number(row.oop_max)} format={(value) => inr(value)} />
                  <UsageBar label={t("policies.annualLimit")} used={Number(row.annual_limit_used)} max={Number(row.annual_limit)} format={(value) => inr(value)} />
                  {row.sublimits.map((sub: any) => (
                    <UsageBar key={sub.key} label={sub.label} used={Number(sub.used)} max={Number(sub.limit)} format={(value) => inr(value)} />
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>

      <Card className="mt-4 p-5">
        <div className="flex items-center justify-between">
          <h2 className="text-[15px] font-bold">{t("policies.versions")}</h2>
          <Button size="sm" variant="ghost" onClick={() => setEditing(true)}>{t("common.add")}</Button>
        </div>
        <div className="mt-3 space-y-2">
          {(item.versions || []).slice().reverse().map((version) => (
            <div key={version.id} className="flex items-start justify-between gap-3 rounded-lg border border-line px-3 py-2.5">
              <div className="flex items-start gap-2.5">
                <span className="mt-0.5 flex h-6 w-6 items-center justify-center rounded-full bg-navy-100 text-[10px] font-bold text-navy">
                  {version.version}
                </span>
                <div>
                  <p className="text-[11.5px] font-semibold text-navy">
                    {version.change_note || "Terms version"}
                    {version.id === item.current_version?.id && <span className="ml-2 text-[9.5px] font-bold uppercase text-teal">current</span>}
                  </p>
                  <p className="mt-0.5 flex items-center gap-2 text-[10px] text-ink-soft">
                    <Clock3 className="h-3 w-3" /> {shortDate(version.created_at, lang)} · {version.source} ·{" "}
                    {version.confirmed ? "confirmed" : "unconfirmed"}
                  </p>
                </div>
              </div>
              <span className="text-[10px] tabular-nums text-ink-soft">{inr(version.terms.deductible)} deductible</span>
            </div>
          ))}
        </div>
      </Card>

      {family.data && (
        <Modal open={editing} onClose={() => setEditing(false)} title={`${item.insurer_name} — ${t("common.edit")}`} width="max-w-5xl">
          <PolicyForm
            family={family.data}
            policy={item}
            onCancel={() => setEditing(false)}
            onSaved={() => {
              setEditing(false);
              policy.reload();
              accumulators.reload();
            }}
          />
        </Modal>
      )}
    </div>
  );
}
