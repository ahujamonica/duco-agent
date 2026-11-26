import React, { useEffect, useMemo, useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import { api } from "../lib/api";
import { Family, Policy } from "../lib/types";
import { useI18n } from "../lib/i18n";
import { Badge, Button, Confidence, Field, Input, Select, cx, useToast } from "./ui";

interface Extracted {
  basics: Record<string, any>;
  terms: Record<string, any>;
  confidence: Record<string, number>;
  missing: string[];
}

export function PolicyForm({
  family,
  policy,
  extracted,
  onSaved,
  onCancel,
}: {
  family: Family;
  policy?: Policy;
  extracted?: Extracted | null;
  onSaved: (saved: Policy) => void;
  onCancel: () => void;
}) {
  const { t } = useI18n();
  const { notify } = useToast();
  const version = policy?.current_version;
  const source = extracted?.terms || version?.terms;
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const initialBasics = useMemo(
    () => ({
      insurer_name: policy?.insurer_name || extracted?.basics?.insurer_name || "",
      plan_name: policy?.plan_name || extracted?.basics?.plan_name || "",
      policy_number: policy?.policy_number || extracted?.basics?.policy_number || "",
      policyholder_member_id: policy?.policyholder_member_id || family.members[0]?.id || 0,
      status: policy?.status || "active",
      start_date: policy?.start_date || extracted?.basics?.start_date || "",
      end_date: policy?.end_date || extracted?.basics?.end_date || "",
      coordination_rule: policy?.coordination_rule || family.coordination_rule || "policyholder",
    }),
    [policy, extracted, family]
  );

  const [basics, setBasics] = useState(initialBasics);
  const [terms, setTerms] = useState({
    sum_insured: source?.sum_insured ?? "0",
    deductible: source?.deductible ?? "0",
    deductible_used: source?.deductible_used ?? "0",
    coinsurance_member: source ? String(Number(source.coinsurance_member || 0) * 100) : "20",
    oop_max: source?.oop_max ?? "0",
    oop_used: source?.oop_used ?? "0",
    annual_limit: source?.annual_limit ?? source?.sum_insured ?? "0",
    annual_limit_used: source?.annual_limit_used ?? "0",
    preauth_threshold: source?.preauth_threshold ?? "0",
    preauth_penalty_rate: source ? String(Number(source.preauth_penalty_rate || 0) * 100) : "0",
    waiting_period_days: String(source?.waiting_period_days ?? 0),
    allowed_factor: source?.allowed_factor ?? "1",
    network_only: Boolean(source?.network_only),
    preauth_always: Boolean(source?.preauth_always),
    covers_primary_exclusions: Boolean(source?.covers_primary_exclusions),
    preauth_cpt_codes: (source?.preauth_cpt_codes || []).join(", "),
  });
  const [roles, setRoles] = useState<Record<number, string>>(() => {
    const next: Record<number, string> = {};
    if (policy) {
      for (const member of policy.members) next[member.member_id] = member.role;
    } else if (family.members[0]) {
      next[family.members[0].id] = "policyholder";
    }
    return next;
  });
  const [exclusions, setExclusions] = useState(
    ((source?.exclusions || []) as any[])
      .map((item: any) => (typeof item === "string" ? item : item.code ? `${item.code}: ${item.label || item.keyword}` : item.label || item.keyword || ""))
      .join("\n")
  );
  const [sublimits, setSublimits] = useState<any[]>(
    (source?.sublimits || []).map((item: any) => ({
      key: item.key || String(item.label || "sub-limit").toLowerCase().replace(/[^a-z0-9]+/g, "-"),
      label: item.label || "Sub-limit",
      limit: item.limit || "0",
      used: item.used || "0",
      category: item.applies_to_categories?.[0] || "",
      basis: item.basis || "per_year",
    }))
  );

  useEffect(() => {
    if (!basics.policyholder_member_id) return;
    setRoles((current) => {
      const next = { ...current };
      for (const [key, value] of Object.entries(next)) {
        if (value === "policyholder" && Number(key) !== basics.policyholder_member_id) next[Number(key)] = "spouse";
      }
      next[basics.policyholder_member_id] = "policyholder";
      return next;
    });
  }, [basics.policyholder_member_id]);

  const setMoney = (key: string, value: string) => setTerms((current) => ({ ...current, [key]: value }));

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    if (!basics.insurer_name.trim() || !basics.plan_name.trim() || !basics.policy_number.trim()) {
      setError("Insurer, plan name and policy number are required.");
      return;
    }
    if (!Object.keys(roles).length) {
      setError("Select at least one covered member.");
      return;
    }
    setSaving(true);
    try {
      const parsedExclusions = exclusions
        .split("\n")
        .map((line) => line.trim())
        .filter(Boolean)
        .map((line) => {
          const match = line.match(/^([A-Za-z0-9]{4,8})\s*:\s*(.+)$/);
          if (match && /^[A-Z0-9]+$/.test(match[1])) return { code: match[1], label: match[2], keyword: match[2] };
          return { label: line, keyword: line };
        });
      const payload = {
        ...basics,
        family_id: family.id,
        policyholder_member_id: basics.policyholder_member_id || null,
        terms: {
          sum_insured: String(terms.sum_insured || "0"),
          deductible: String(terms.deductible || "0"),
          deductible_used: String(terms.deductible_used || "0"),
          coinsurance_member: String(Number(terms.coinsurance_member || 0) / 100),
          oop_max: String(terms.oop_max || "0"),
          oop_used: String(terms.oop_used || "0"),
          annual_limit: String(terms.annual_limit || "0"),
          annual_limit_used: String(terms.annual_limit_used || "0"),
          preauth_threshold: String(terms.preauth_threshold || "0"),
          preauth_penalty_rate: String(Number(terms.preauth_penalty_rate || 0) / 100),
          waiting_period_days: Number(terms.waiting_period_days || 0),
          allowed_factor: String(terms.allowed_factor || "1"),
          network_only: terms.network_only,
          preauth_always: terms.preauth_always,
          covers_primary_exclusions: terms.covers_primary_exclusions,
          sublimits: sublimits.map((item) => ({
            key: item.key || String(item.label || "sub-limit").toLowerCase().replace(/[^a-z0-9]+/g, "-"),
            label: item.label || "Sub-limit",
            limit: String(item.limit || "0"),
            used: String(item.used || "0"),
            applies_to_codes: [],
            applies_to_categories: item.category ? [item.category] : [],
            basis: item.basis || "per_year",
          })),
          exclusions: parsedExclusions,
          preauth_cpt_codes: String(terms.preauth_cpt_codes || "")
            .split(",")
            .map((code) => code.trim())
            .filter(Boolean),
          preauth_categories: [],
        },
        members: Object.entries(roles).map(([memberId, role]) => ({ member_id: Number(memberId), role })),
        change_note: policy ? "Terms confirmed in review" : "Created from policy schedule",
      };
      const saved = policy
        ? await api.patch<Policy>(`/api/policies/${policy.id}`, payload)
        : await api.post<Policy>("/api/policies", payload);
      notify(policy ? "New policy version saved." : "Policy saved.", "success");
      onSaved(saved);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save the policy.");
    } finally {
      setSaving(false);
    }
  };

  const confidence = (key: string) => extracted?.confidence?.[key];
  const labelWithConfidence = (text: string, key: string) => (
    <span className="flex items-center justify-between gap-2">
      <span>{text}</span>
      {confidence(key) != null && <Confidence value={Number(confidence(key))} />}
    </span>
  );

  return (
    <form onSubmit={submit} className="space-y-6">
      <section>
        <h3 className="text-[13px] font-bold uppercase tracking-[0.08em] text-ink-soft">{t("policies.basics")}</h3>
        <div className="mt-3 grid gap-4 sm:grid-cols-2">
          <Field label={labelWithConfidence(t("policies.insurer"), "insurer")}>
            <Input value={basics.insurer_name} onChange={(e) => setBasics({ ...basics, insurer_name: e.target.value })} placeholder="ICICI Lombard" />
          </Field>
          <Field label={labelWithConfidence(t("policies.plan"), "plan_name")}>
            <Input value={basics.plan_name} onChange={(e) => setBasics({ ...basics, plan_name: e.target.value })} placeholder="SecureShield" />
          </Field>
          <Field label={labelWithConfidence(t("policies.number"), "policy_number")}>
            <Input value={basics.policy_number} onChange={(e) => setBasics({ ...basics, policy_number: e.target.value })} placeholder="POL-2026-001" />
          </Field>
          <Field label={t("policies.policyholder")}>
            <Select
              value={basics.policyholder_member_id}
              onChange={(e) => setBasics({ ...basics, policyholder_member_id: Number(e.target.value) })}
            >
              {family.members.map((member) => (
                <option key={member.id} value={member.id}>{member.name}</option>
              ))}
            </Select>
          </Field>
          <Field label={t("policies.start")}>
            <Input type="date" value={basics.start_date || ""} onChange={(e) => setBasics({ ...basics, start_date: e.target.value })} />
          </Field>
          <Field label={t("policies.end")}>
            <Input type="date" value={basics.end_date || ""} onChange={(e) => setBasics({ ...basics, end_date: e.target.value })} />
          </Field>
          <Field label={t("policies.status")}>
            <Select value={basics.status} onChange={(e) => setBasics({ ...basics, status: e.target.value })}>
              <option value="active">Active</option>
              <option value="inactive">Inactive</option>
              <option value="expired">Expired</option>
            </Select>
          </Field>
          <Field label={t("family.coordination")} hint={t("family.coordinationHelp")}>
            <Select value={basics.coordination_rule} onChange={(e) => setBasics({ ...basics, coordination_rule: e.target.value })}>
              <option value="policyholder">Own policy first</option>
              <option value="birthday">Birthday rule</option>
              <option value="longest_coverage">Longest coverage</option>
              <option value="manual">Manual</option>
            </Select>
          </Field>
        </div>
      </section>

      <section>
        <h3 className="text-[13px] font-bold uppercase tracking-[0.08em] text-ink-soft">{t("policies.terms")}</h3>
        <div className="mt-3 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <Field label={labelWithConfidence(t("policies.deductible"), "deductible")}>
            <Input type="number" min="0" step="0.01" value={terms.deductible} onChange={(e) => setMoney("deductible", e.target.value)} />
          </Field>
          <Field label={`${t("policies.accrued")} (${t("policies.deductible")})`}>
            <Input type="number" min="0" step="0.01" value={terms.deductible_used} onChange={(e) => setMoney("deductible_used", e.target.value)} />
          </Field>
          <Field label={labelWithConfidence(t("policies.coinsurance"), "coinsurance_member")}>
            <div className="relative">
              <Input type="number" min="0" max="100" step="0.1" value={terms.coinsurance_member} onChange={(e) => setMoney("coinsurance_member", e.target.value)} className="pr-8" />
              <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-[12px] text-ink-soft">%</span>
            </div>
          </Field>
          <Field label={t("policies.annualLimit")}>
            <Input type="number" min="0" step="0.01" value={terms.annual_limit} onChange={(e) => setMoney("annual_limit", e.target.value)} />
          </Field>
          <Field label={t("policies.oop")}>
            <Input type="number" min="0" step="0.01" value={terms.oop_max} onChange={(e) => setMoney("oop_max", e.target.value)} />
          </Field>
          <Field label={t("policies.preauthThreshold")}>
            <Input type="number" min="0" step="0.01" value={terms.preauth_threshold} onChange={(e) => setMoney("preauth_threshold", e.target.value)} />
          </Field>
          <Field label={t("policies.penalty")}>
            <div className="relative">
              <Input type="number" min="0" max="100" step="0.1" value={terms.preauth_penalty_rate} onChange={(e) => setMoney("preauth_penalty_rate", e.target.value)} className="pr-8" />
              <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-[12px] text-ink-soft">%</span>
            </div>
          </Field>
          <Field label={t("policies.waiting")}>
            <Input type="number" min="0" value={terms.waiting_period_days} onChange={(e) => setMoney("waiting_period_days", e.target.value)} />
          </Field>
          <Field label="Sum insured">
            <Input type="number" min="0" step="0.01" value={terms.sum_insured} onChange={(e) => setMoney("sum_insured", e.target.value)} />
          </Field>
        </div>
        <div className="mt-3 grid gap-2 sm:grid-cols-2">
          <label className="flex items-center gap-2 rounded-lg border border-line px-3 py-2 text-[11.5px] text-ink">
            <input type="checkbox" checked={terms.network_only} onChange={(e) => setTerms({ ...terms, network_only: e.target.checked })} />
            Network hospitals only
          </label>
          <label className="flex items-center gap-2 rounded-lg border border-line px-3 py-2 text-[11.5px] text-ink">
            <input type="checkbox" checked={terms.preauth_always} onChange={(e) => setTerms({ ...terms, preauth_always: e.target.checked })} />
            Pre-authorisation for every admission
          </label>
        </div>
      </section>

      <section>
        <h3 className="text-[13px] font-bold uppercase tracking-[0.08em] text-ink-soft">{t("policies.coverage")}</h3>
        <div className="mt-3 space-y-2">
          {family.members.map((member) => {
            const covered = roles[member.id] !== undefined;
            return (
              <div key={member.id} className={cx("flex items-center justify-between gap-3 rounded-lg border px-3 py-2", covered ? "border-brand/30 bg-brand-50/30" : "border-line")}>
                <label className="flex items-center gap-2 text-[12px] font-medium text-navy">
                  <input
                    type="checkbox"
                    checked={covered}
                    onChange={(event) => {
                      setRoles((current) => {
                        const next = { ...current };
                        if (event.target.checked) next[member.id] = "dependent";
                        else delete next[member.id];
                        return next;
                      });
                    }}
                  />
                  {member.name}
                  <span className="text-[10px] font-normal text-ink-soft">{member.relation}</span>
                </label>
                {covered && (
                  <Select
                    value={roles[member.id] || "dependent"}
                    onChange={(event) => setRoles({ ...roles, [member.id]: event.target.value })}
                    className="h-8 w-[140px] py-1 text-[11px]"
                    disabled={member.id === basics.policyholder_member_id}
                  >
                    <option value="policyholder">Policyholder</option>
                    <option value="spouse">Spouse</option>
                    <option value="dependent">Dependent</option>
                    <option value="child">Child</option>
                    <option value="parent">Parent</option>
                  </Select>
                )}
              </div>
            );
          })}
        </div>
        <p className="mt-2 text-[10.5px] text-ink-soft">
          A policy can cover any number of members; a member can be on any number of policies.
        </p>
      </section>

      <section>
        <h3 className="text-[13px] font-bold uppercase tracking-[0.08em] text-ink-soft">{t("policies.advanced")}</h3>
        <div className="mt-3 grid gap-4 lg:grid-cols-2">
          <Field label={t("policies.exclusions")} hint={`${t("policies.exclusionHelp")} One per line: "equipment" or "E0114: Crutches".`}>
            <textarea
              value={exclusions}
              onChange={(e) => setExclusions(e.target.value)}
              className="min-h-[120px] w-full rounded-lg border border-line px-3 py-2 text-[12px] focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand/15"
              placeholder={"equipment\nE0114: Crutches"}
            />
          </Field>
          <div>
            <div className="flex items-center justify-between">
              <p className="text-[12px] font-semibold text-navy">{t("policies.sublimits")}</p>
              <Button
                type="button"
                size="sm"
                variant="ghost"
                icon={<Plus className="h-3.5 w-3.5" />}
                onClick={() =>
                  setSublimits([...sublimits, { key: "", label: "", limit: "0", used: "0", category: "therapy", basis: "per_year" }])
                }
              >
                {t("policies.addSublimit")}
              </Button>
            </div>
            <div className="mt-2 space-y-2">
              {sublimits.length === 0 && <p className="rounded-lg border border-dashed border-line px-3 py-4 text-[11px] text-ink-soft">No sub-limits.</p>}
              {sublimits.map((item, index) => (
                <div key={index} className="grid grid-cols-[1fr_90px_90px_auto] gap-1.5">
                  <Input
                    value={item.label}
                    placeholder="Annual physiotherapy"
                    onChange={(event) => {
                      const next = [...sublimits];
                      next[index] = { ...item, label: event.target.value, key: event.target.value.toLowerCase().replace(/[^a-z0-9]+/g, "-") };
                      setSublimits(next);
                    }}
                    className="h-8 text-[11px]"
                  />
                  <Input
                    type="number"
                    value={item.limit}
                    onChange={(event) => {
                      const next = [...sublimits];
                      next[index] = { ...item, limit: event.target.value };
                      setSublimits(next);
                    }}
                    className="h-8 text-[11px]"
                    aria-label="Limit"
                  />
                  <Select
                    value={item.category}
                    onChange={(event) => {
                      const next = [...sublimits];
                      next[index] = { ...item, category: event.target.value };
                      setSublimits(next);
                    }}
                    className="h-8 py-0 text-[10.5px]"
                  >
                    <option value="">Any service</option>
                    <option value="therapy">Therapy</option>
                    <option value="diagnostic">Diagnostic</option>
                    <option value="facility">Room / facility</option>
                    <option value="professional">Professional</option>
                  </Select>
                  <button
                    type="button"
                    onClick={() => setSublimits(sublimits.filter((_, i) => i !== index))}
                    className="rounded-md p-1.5 text-ink-soft hover:bg-danger-50 hover:text-danger"
                    aria-label="Remove sub-limit"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              ))}
            </div>
          </div>
        </div>
        <div className="mt-3">
          <Field label="Pre-authorisation CPT / HCPCS codes" hint="Comma separated, e.g. 29888, 29881.">
            <Input value={terms.preauth_cpt_codes} onChange={(e) => setTerms({ ...terms, preauth_cpt_codes: e.target.value })} />
          </Field>
        </div>
      </section>

      {extracted && extracted.missing.length > 0 && (
        <div className="rounded-lg border border-amber/25 bg-amber-50 px-3 py-2 text-[11.5px] text-[#6B4A10]">
          These extracted values need your confirmation: <b>{extracted.missing.join(", ")}</b>.
        </div>
      )}
      {error && <div className="rounded-lg border border-danger/25 bg-danger-50 px-3 py-2 text-[11.5px] text-danger">{error}</div>}

      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line pt-4">
        <p className="text-[10.5px] text-ink-soft">
          {policy ? t("policies.versionNote") : "Terms are saved as version 1."}
        </p>
        <div className="flex gap-2">
          <Button type="button" variant="ghost" onClick={onCancel}>{t("common.cancel")}</Button>
          <Button type="submit" loading={saving}>{policy ? t("policies.saveVersion") : t("policies.savePolicy")}</Button>
        </div>
      </div>
    </form>
  );
}
