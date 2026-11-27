import React, { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  AlertCircle,
  ArrowRight,
  FileText,
  Plus,
  ShieldCheck,
  Trash2,
} from "lucide-react";
import { useI18n } from "../lib/i18n";
import { useApi } from "../lib/useApi";
import { api } from "../lib/api";
import { Family } from "../lib/types";
import {
  Alert,
  Badge,
  Button,
  Card,
  Checkbox,
  Field,
  Input,
  LoadingBlock,
  PageHeader,
  Select,
  Textarea,
  useToast,
} from "../components/ui";
import { shortDate } from "../lib/format";

const RULES = [
  ["policyholder", "family.rulePolicyholder", "family.rulePolicyholderDesc"],
  ["birthday", "family.ruleBirthday", "family.ruleBirthdayDesc"],
  ["longest_coverage", "family.ruleLongest", "family.ruleLongestDesc"],
  ["manual", "family.ruleManual", "family.ruleManualDesc"],
] as const;

export default function NewCase() {
  const { t, lang } = useI18n();
  const { notify } = useToast();
  const navigate = useNavigate();
  const families = useApi<{ families: Family[] }>("/api/families");
  const [familyId, setFamilyId] = useState<number | null>(null);
  const list = families.data?.families || [];
  const activeFamilyId = familyId || list[0]?.id || null;
  const family = useApi<Family>(
    activeFamilyId ? `/api/families/${activeFamilyId}` : null,
    [activeFamilyId],
  );
  const [form, setForm] = useState({
    title: "",
    patient_member_id: 0,
    provider_name: "",
    service_date: "",
    provider_in_network: true,
    narrative: "",
    coordination_rule: "",
  });
  const [selectedMemberIds, setSelectedMemberIds] = useState<number[]>([]);
  const [policyIds, setPolicyIds] = useState<number[]>([]);
  const [policyOrder, setPolicyOrder] = useState<number[]>([]);
  const [documentIds, setDocumentIds] = useState<number[]>([]);
  const [manualLines, setManualLines] = useState<
    {
      description: string;
      amount: string;
      quantity: string;
      cpt_code: string;
      member_id: number | "";
    }[]
  >([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!family.data) return;
    // A case can include any subset of the existing household members.
    // Default to all members; the user can uncheck any member.
    setSelectedMemberIds(family.data.members.map((member) => member.id));
    setForm((current) => ({
      ...current,
      patient_member_id: family.data!.members[0]?.id || 0, // legacy lead-member field
      coordination_rule:
        current.coordination_rule ||
        family.data!.coordination_rule ||
        "policyholder",
    }));
    const activeIds = family.data.policies
      .filter((policy) => policy.status === "active")
      .map((policy) => policy.id);
    setPolicyIds(activeIds);
    setPolicyOrder(activeIds);
  }, [family.data?.id]);

  if (families.loading) return <LoadingBlock />;
  if (list.length === 0) {
    return (
      <div>
        <PageHeader title={t("cases.new")} subtitle={t("cases.subtitle")} />
        <Alert tone="warning" title={t("cases.needFamily")}>
          Create a household, add its members and at least one policy before
          opening a case.{" "}
          <Link to="/app/family" className="font-bold underline">
            Open Family
          </Link>
        </Alert>
      </div>
    );
  }

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!activeFamilyId) return;
    setError(null);
    if (!form.title.trim()) {
      setError("Give the case a short title.");
      return;
    }
    if (!selectedMemberIds.length) {
      setError("Select at least one family member.");
      return;
    }
    if (
      manualLines.some(
        (line) =>
          line.description.trim() &&
          Number(line.amount) > 0 &&
          !selectedMemberIds.includes(Number(line.member_id)),
      )
    ) {
      setError("Assign each manual service line to a selected family member.");
      return;
    }
    if (
      manualLines.some(
        (line) => line.description.trim() && Number(line.amount) > 0,
      ) &&
      !form.service_date
    ) {
      setError("Enter the actual service date for manually entered lines.");
      return;
    }
    if (!policyIds.length) {
      setError("Select at least one policy to coordinate.");
      return;
    }
    if (
      !documentIds.length &&
      !manualLines.filter((line) => line.description && Number(line.amount) > 0)
        .length
    ) {
      setError(t("cases.selectAtLeastDoc"));
      return;
    }
    setBusy(true);
    try {
      const created = await api.post<{ id: number }>("/api/cases", {
        family_id: activeFamilyId,
        title: form.title.trim(),
        // Kept for backwards compatibility; selected_member_ids is authoritative.
        patient_member_id: selectedMemberIds[0],
        selected_member_ids: selectedMemberIds,
        provider_name: form.provider_name,
        service_date: form.service_date || null,
        provider_in_network: form.provider_in_network,
        narrative: form.narrative || null,
        document_ids: documentIds,
        policy_ids: policyIds,
        policy_order: policyOrder,
        coordination_rule: form.coordination_rule || null,
        manual_lines: manualLines
          .filter((line) => line.description && Number(line.amount) > 0)
          .map((line) => ({
            description: line.description,
            amount: line.amount,
            quantity: line.quantity.trim() ? Number(line.quantity) : null,
            member_id: Number(line.member_id),
            cpt_code: line.cpt_code || null,
            category: "professional",
          })),
      });
      notify("Case created. Run the analysis to start the agents.", "success");
      navigate(`/app/cases/${created.id}/run`);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Could not create the case.",
      );
    } finally {
      setBusy(false);
    }
  };

  const familyData = family.data;
  const attachable = (familyData?.documents || []).filter(
    (doc) => doc.doc_type !== "policy",
  );

  return (
    <div>
      <PageHeader
        title={t("cases.new")}
        subtitle="One case is one medical episode. Attach the paperwork, choose the policies, and let the supervisor plan the work."
        actions={
          list.length > 1 ? (
            <Select
              value={activeFamilyId || ""}
              onChange={(event) => setFamilyId(Number(event.target.value))}
              className="min-w-[160px]"
            >
              {list.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </Select>
          ) : undefined
        }
      />

      {!familyData ? (
        <LoadingBlock />
      ) : (
        <form
          onSubmit={submit}
          className="grid gap-4 lg:grid-cols-[1.35fr_1fr]"
        >
          <div className="space-y-4">
            <Card className="p-5">
              <h2 className="text-[13px] font-bold uppercase tracking-[0.08em] text-ink-soft">
                The claim
              </h2>
              <div className="mt-3 grid gap-4 sm:grid-cols-2">
                <Field label={t("cases.titleField")} className="sm:col-span-2">
                  <Input
                    value={form.title}
                    onChange={(event) =>
                      setForm({ ...form, title: event.target.value })
                    }
                    placeholder="Asha's knee surgery and physiotherapy"
                  />
                </Field>
                <Field
                  label="Select family members"
                  className="sm:col-span-2"
                  hint="Select one or more existing household members whose claims should be included in this case."
                >
                  <div className="space-y-2 rounded-lg border border-line p-3">
                    {familyData.members.map((member) => (
                      <Checkbox
                        key={member.id}
                        checked={selectedMemberIds.includes(member.id)}
                        onChange={(checked) =>
                          setSelectedMemberIds((current) =>
                            checked
                              ? [...current, member.id]
                              : current.filter((id) => id !== member.id),
                          )
                        }
                        label={
                          <span className="font-medium">{member.name}</span>
                        }
                        description={`${member.relation}${member.age !== null ? ` · ${member.age} years` : ""}`}
                      />
                    ))}
                    <div className="flex items-center justify-between border-t border-line pt-2 text-[10.5px]">
                      <span className="text-ink-soft">
                        {selectedMemberIds.length} of{" "}
                        {familyData.members.length} selected
                      </span>
                      <button
                        type="button"
                        className="font-semibold text-brand"
                        onClick={() =>
                          setSelectedMemberIds(
                            selectedMemberIds.length ===
                              familyData.members.length
                              ? []
                              : familyData.members.map((member) => member.id),
                          )
                        }
                      >
                        {selectedMemberIds.length === familyData.members.length
                          ? "Clear selection"
                          : "Select all"}
                      </button>
                    </div>
                  </div>
                </Field>
                <Field label={t("cases.provider")}>
                  <Input
                    value={form.provider_name}
                    onChange={(event) =>
                      setForm({ ...form, provider_name: event.target.value })
                    }
                    placeholder="Sunrise Hospital"
                  />
                </Field>
                <Field label={t("cases.date")}>
                  <Input
                    type="date"
                    value={form.service_date}
                    onChange={(event) =>
                      setForm({ ...form, service_date: event.target.value })
                    }
                  />
                </Field>
                <Field
                  label={t("cases.coordination")}
                  hint="Overrides the household rule for this case only."
                >
                  <Select
                    value={form.coordination_rule}
                    onChange={(event) => {
                      const rule = event.target.value;
                      setForm({ ...form, coordination_rule: rule });
                      if (rule === "manual" && policyOrder.length === 0)
                        setPolicyOrder(policyIds);
                    }}
                  >
                    {RULES.map(([value, label]) => (
                      <option key={value} value={value}>
                        {t(label)}
                      </option>
                    ))}
                  </Select>
                </Field>
                <Field
                  label={t("cases.narrative")}
                  hint={t("cases.narrativeHint")}
                  className="sm:col-span-2"
                >
                  <Textarea
                    value={form.narrative}
                    onChange={(event) =>
                      setForm({ ...form, narrative: event.target.value })
                    }
                    placeholder="ACL reconstruction planned after an MRI confirmed a complete tear…"
                  />
                </Field>
              </div>
              <label className="mt-3 flex items-center gap-2 text-[11.5px] text-ink">
                <input
                  type="checkbox"
                  checked={form.provider_in_network}
                  onChange={(event) =>
                    setForm({
                      ...form,
                      provider_in_network: event.target.checked,
                    })
                  }
                />
                {t("cases.network")}
              </label>
            </Card>

            <Card className="p-5">
              <div className="flex items-center justify-between">
                <h2 className="text-[13px] font-bold uppercase tracking-[0.08em] text-ink-soft">
                  {t("cases.selectPolicies")}
                </h2>
                <Badge tone="blue">{policyIds.length} selected</Badge>
              </div>
              {form.coordination_rule === "manual" &&
                policyOrder.length > 0 && (
                  <div className="mt-3 rounded-lg border border-brand/25 bg-brand-50/40 p-2.5">
                    <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-brand">
                      Payer order — first pays first
                    </p>
                    <div className="mt-1.5 space-y-1">
                      {policyOrder.map((id, index) => {
                        const policy = familyData.policies.find(
                          (item) => item.id === id,
                        );
                        return (
                          <div
                            key={id}
                            className="flex items-center gap-2 text-[11px]"
                          >
                            <span className="flex h-4 w-4 items-center justify-center rounded-full bg-brand text-[8px] font-bold text-white">
                              {index + 1}
                            </span>
                            <span className="flex-1 truncate text-navy">
                              {policy?.insurer_name}
                            </span>
                            <button
                              type="button"
                              disabled={index === 0}
                              onClick={() => {
                                const next = [...policyOrder];
                                [next[index - 1], next[index]] = [
                                  next[index],
                                  next[index - 1],
                                ];
                                setPolicyOrder(next);
                              }}
                              className="rounded px-1 text-ink-soft hover:text-brand disabled:opacity-30"
                              aria-label="Move up"
                            >
                              ↑
                            </button>
                            <button
                              type="button"
                              disabled={index === policyOrder.length - 1}
                              onClick={() => {
                                const next = [...policyOrder];
                                [next[index + 1], next[index]] = [
                                  next[index],
                                  next[index + 1],
                                ];
                                setPolicyOrder(next);
                              }}
                              className="rounded px-1 text-ink-soft hover:text-brand disabled:opacity-30"
                              aria-label="Move down"
                            >
                              ↓
                            </button>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}
              <div className="mt-3 space-y-2">
                {familyData.policies.map((policy) => (
                  <Checkbox
                    key={policy.id}
                    checked={policyIds.includes(policy.id)}
                    onChange={(checked) => {
                      setPolicyIds(
                        checked
                          ? [...policyIds, policy.id]
                          : policyIds.filter((id) => id !== policy.id),
                      );
                      setPolicyOrder(
                        checked
                          ? [...policyOrder, policy.id]
                          : policyOrder.filter((id) => id !== policy.id),
                      );
                    }}
                    label={
                      <span className="flex flex-wrap items-center gap-2">
                        {policy.insurer_name}
                        <span className="text-[10.5px] font-normal text-ink-soft">
                          {policy.plan_name}
                        </span>
                        {policy.status !== "active" && (
                          <Badge tone="red">{policy.status}</Badge>
                        )}
                      </span>
                    }
                    description={`${policy.policy_number} · ${policy.members.map((member) => `${member.name?.split(" ")[0]} (${member.role})`).join(", ")}`}
                  />
                ))}
                {familyData.policies.length === 0 && (
                  <p className="text-[12px] text-ink-muted">
                    No policies yet.{" "}
                    <Link
                      to="/app/policies"
                      className="font-semibold text-brand"
                    >
                      Add one
                    </Link>
                    .
                  </p>
                )}
              </div>
            </Card>

            <Card className="p-5">
              <div className="flex items-center justify-between">
                <h2 className="text-[13px] font-bold uppercase tracking-[0.08em] text-ink-soft">
                  {t("cases.selectDocuments")}
                </h2>
                <Link
                  to="/app/documents"
                  className="text-[11px] font-semibold text-brand"
                >
                  {t("documents.upload")}
                </Link>
              </div>
              <div className="mt-3 space-y-2">
                {attachable.map((doc) => (
                  <Checkbox
                    key={doc.id}
                    checked={documentIds.includes(doc.id)}
                    onChange={(checked) =>
                      setDocumentIds(
                        checked
                          ? [...documentIds, doc.id]
                          : documentIds.filter((id) => id !== doc.id),
                      )
                    }
                    label={
                      <span className="flex flex-wrap items-center gap-2">
                        <FileText className="h-3.5 w-3.5 text-ink-soft" />
                        {doc.filename}
                        <Badge tone="slate">
                          {t(`documents.typeLabels.${doc.doc_type}`)}
                        </Badge>
                        <span className="text-[9.5px] font-normal text-ink-soft">
                          {Math.round(doc.classification_confidence * 100)}%
                        </span>
                      </span>
                    }
                    description={`${shortDate(doc.created_at, lang)} · ${doc.lines.length} service line(s)`}
                  />
                ))}
                {attachable.length === 0 && (
                  <div className="rounded-lg border border-dashed border-line px-3 py-6 text-center">
                    <p className="text-[11.5px] text-ink-muted">
                      No documents yet.
                    </p>
                    <Link
                      to="/app/documents"
                      className="mt-2 inline-block text-[11px] font-semibold text-brand"
                    >
                      Upload a bill or report →
                    </Link>
                  </div>
                )}
              </div>
            </Card>

            <Card className="p-5">
              <div className="flex items-center justify-between">
                <div>
                  <h2 className="text-[13px] font-bold uppercase tracking-[0.08em] text-ink-soft">
                    {t("cases.manualLines")}
                  </h2>
                  <p className="mt-1 text-[10.5px] text-ink-soft">
                    Use this when there is no bill to upload. Lines are treated
                    as self-declared.
                  </p>
                </div>
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  icon={<Plus className="h-3.5 w-3.5" />}
                  onClick={() =>
                    setManualLines([
                      ...manualLines,
                      {
                        description: "",
                        amount: "",
                        quantity: "",
                        cpt_code: "",
                        member_id: selectedMemberIds[0] || "",
                      },
                    ])
                  }
                >
                  Add line
                </Button>
              </div>
              <div className="mt-3 space-y-2">
                {manualLines.map((line, index) => (
                  <div
                    key={index}
                    className="grid grid-cols-[1fr_140px_90px_60px_80px_auto] gap-1.5"
                  >
                    <Input
                      value={line.description}
                      placeholder="Therapeutic exercise"
                      onChange={(event) => {
                        const next = [...manualLines];
                        next[index] = {
                          ...line,
                          description: event.target.value,
                        };
                        setManualLines(next);
                      }}
                      className="h-9 py-1 text-[11.5px]"
                    />
                    <Select
                      value={line.member_id}
                      onChange={(event) => {
                        const next = [...manualLines];
                        next[index] = {
                          ...line,
                          member_id: event.target.value
                            ? Number(event.target.value)
                            : "",
                        };
                        setManualLines(next);
                      }}
                      aria-label="Family member"
                      className="h-9 py-1 text-[11.5px]"
                    >
                      <option value="">Patient</option>
                      {familyData.members
                        .filter((member) => selectedMemberIds.includes(member.id))
                        .map((member) => (
                          <option key={member.id} value={member.id}>
                            {member.name}
                          </option>
                        ))}
                    </Select>
                    <Input
                      type="number"
                      value={line.amount}
                      placeholder="Amount"
                      onChange={(event) => {
                        const next = [...manualLines];
                        next[index] = { ...line, amount: event.target.value };
                        setManualLines(next);
                      }}
                      className="h-9 py-1 text-[11.5px]"
                      aria-label="Amount"
                    />
                    <Input
                      type="number"
                      value={line.quantity}
                      placeholder="Qty"
                      onChange={(event) => {
                        const next = [...manualLines];
                        next[index] = { ...line, quantity: event.target.value };
                        setManualLines(next);
                      }}
                      className="h-9 py-1 text-[11.5px]"
                      aria-label="Quantity"
                    />
                    <Input
                      value={line.cpt_code}
                      placeholder="CPT"
                      onChange={(event) => {
                        const next = [...manualLines];
                        next[index] = { ...line, cpt_code: event.target.value };
                        setManualLines(next);
                      }}
                      className="h-9 py-1 text-[11.5px]"
                      aria-label="CPT code"
                    />
                    <button
                      type="button"
                      onClick={() =>
                        setManualLines(
                          manualLines.filter((_, i) => i !== index),
                        )
                      }
                      className="rounded-md p-1.5 text-ink-soft hover:bg-danger-50 hover:text-danger"
                      aria-label="Remove line"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                ))}
                {manualLines.length === 0 && (
                  <p className="text-[11px] text-ink-soft">No manual lines.</p>
                )}
              </div>
            </Card>
          </div>

          <div className="space-y-4">
            <Card className="sticky top-20 p-5">
              <h2 className="text-[15px] font-bold">Before you run</h2>
              <ul className="mt-3 space-y-2.5 text-[11.5px] leading-4 text-ink-muted">
                {[
                  "Every member on the policy is covered — relationships are checked, not assumed.",
                  "Missing or low-confidence fields pause the case before any money is calculated.",
                  "Pre-authorisation letters are filed against both insurers where required.",
                  "The calculation is deterministic and every number is traceable.",
                ].map((text) => (
                  <li key={text} className="flex items-start gap-2">
                    <ShieldCheck className="mt-0.5 h-3.5 w-3.5 shrink-0 text-teal" />{" "}
                    {text}
                  </li>
                ))}
              </ul>
              {error && (
                <div className="mt-4">
                  <Alert tone="danger">{error}</Alert>
                </div>
              )}
              <Button
                type="submit"
                className="mt-5 w-full"
                size="lg"
                loading={busy}
                icon={<ArrowRight className="h-4 w-4" />}
              >
                {t("cases.create")}
              </Button>
              <p className="mt-2 text-center text-[10px] text-ink-soft">
                You will see the agent plan before anything is calculated.
              </p>
              <div className="mt-4 border-t border-line pt-3">
                <p className="flex items-start gap-1.5 text-[10px] leading-4 text-ink-soft">
                  <AlertCircle className="mt-0.5 h-3 w-3 shrink-0" />
                  Insurer responses are simulated. This prototype does not
                  submit anything to a real insurer.
                </p>
              </div>
            </Card>
          </div>
        </form>
      )}
    </div>
  );
}
