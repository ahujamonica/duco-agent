import React, { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ArrowRight, Pencil, Plus, Trash2, UserRound, Users } from "lucide-react";
import { useAuth } from "../lib/auth";
import { useI18n } from "../lib/i18n";
import { useApi } from "../lib/useApi";
import { api } from "../lib/api";
import { Family, Member } from "../lib/types";
import {
  Alert,
  Badge,
  Button,
  Card,
  EmptyState,
  Field,
  Input,
  LoadingBlock,
  Modal,
  PageHeader,
  Select,
  Term,
  useToast,
} from "../components/ui";
import { initials, shortDate } from "../lib/format";
import { InsuranceGraph } from "../components/InsuranceGraph";

const RULES = [
  { value: "policyholder", label: "family.rulePolicyholder", desc: "family.rulePolicyholderDesc" },
  { value: "birthday", label: "family.ruleBirthday", desc: "family.ruleBirthdayDesc" },
  { value: "longest_coverage", label: "family.ruleLongest", desc: "family.ruleLongestDesc" },
  { value: "manual", label: "family.ruleManual", desc: "family.ruleManualDesc" },
];

export default function FamilyPage() {
  const { t, lang } = useI18n();
  const { user } = useAuth();
  const { notify } = useToast();
  const [params] = useSearchParams();
  const families = useApi<{ families: Family[] }>("/api/families");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const list = families.data?.families || [];
  const activeId = selectedId || list[0]?.id || null;
  const detail = useApi<Family>(activeId ? `/api/families/${activeId}` : null, [activeId]);
  const [memberModal, setMemberModal] = useState<Member | null | "new">(null);
  const [familyModal, setFamilyModal] = useState(false);
  const [saving, setSaving] = useState(false);
  const welcome = params.get("welcome") === "1";

  const memberInitial = useMemo(() => {
    if (memberModal && memberModal !== "new") return memberModal;
    return null;
  }, [memberModal]);

  if (families.loading) return <LoadingBlock />;
  if (families.error) return <Alert tone="danger">{families.error}</Alert>;

  const saveMember = async (payload: any) => {
    if (!activeId) return;
    setSaving(true);
    try {
      if (memberInitial) await api.patch(`/api/members/${memberInitial.id}`, payload);
      else await api.post(`/api/families/${activeId}/members`, payload);
      notify(memberInitial ? "Member updated." : "Member added.", "success");
      setMemberModal(null);
      detail.reload();
      families.reload();
    } catch (error) {
      notify(error instanceof Error ? error.message : "Could not save the member.", "error");
    } finally {
      setSaving(false);
    }
  };

  const deleteMember = async (member: Member) => {
    if (!window.confirm(t("family.deleteConfirm"))) return;
    try {
      await api.del(`/api/members/${member.id}`);
      notify("Member removed.", "success");
      detail.reload();
      families.reload();
    } catch (error) {
      notify(error instanceof Error ? error.message : "Could not remove the member.", "error");
    }
  };

  const createFamily = async (payload: any) => {
    setSaving(true);
    try {
      const family = await api.post<Family>("/api/families", payload);
      notify("Household created.", "success");
      setFamilyModal(false);
      families.reload();
      setSelectedId(family.id);
    } catch (error) {
      notify(error instanceof Error ? error.message : "Could not create the household.", "error");
    } finally {
      setSaving(false);
    }
  };

  const updateRule = async (rule: string) => {
    if (!activeId) return;
    try {
      await api.patch(`/api/families/${activeId}`, { coordination_rule: rule });
      notify("Coordination rule updated.", "success");
      detail.reload();
    } catch (error) {
      notify(error instanceof Error ? error.message : "Could not update the rule.", "error");
    }
  };

  if (list.length === 0) {
    return (
      <div>
        <PageHeader title={t("family.title")} subtitle={t("family.subtitle")} />
        <EmptyState
          title={t("family.createFamily")}
          body="Start with the people you cover and the policies that cover them. You can add more of both later."
          icon={<Users className="h-5 w-5" />}
          action={<Button onClick={() => setFamilyModal(true)} icon={<Plus className="h-4 w-4" />}>{t("family.createFamily")}</Button>}
        />
        <FamilyModal open={familyModal} onClose={() => setFamilyModal(false)} onSave={createFamily} saving={saving} />
      </div>
    );
  }

  const family = detail.data;

  return (
    <div>
      <PageHeader
        title={t("family.title")}
        subtitle={t("family.subtitle")}
        actions={
          <>
            <Select
              aria-label="Household"
              value={activeId || ""}
              onChange={(event) => setSelectedId(Number(event.target.value))}
              className="min-w-[170px]"
            >
              {list.map((item) => (
                <option key={item.id} value={item.id}>{item.name}</option>
              ))}
            </Select>
            <Button variant="secondary" onClick={() => setFamilyModal(true)} icon={<Plus className="h-4 w-4" />}>
              {t("family.createFamily")}
            </Button>
            <Button onClick={() => setMemberModal("new")} icon={<UserRound className="h-4 w-4" />}>
              {t("family.addMember")}
            </Button>
          </>
        }
      />

      {welcome && (
        <div className="mb-5">
          <Alert tone="success" title="Your workspace is ready">
            Add each family member below, then add a policy. A case needs both before an analysis can run.
          </Alert>
        </div>
      )}

      {detail.loading && !family ? <LoadingBlock /> : !family ? null : (
        <>
          <div className="grid gap-4 lg:grid-cols-[1.5fr_1fr]">
            <Card className="p-5">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <h2 className="text-[15px] font-bold">{family.name}</h2>
                  <p className="mt-0.5 text-[11.5px] text-ink-muted">
                    {family.counts.members} members · {family.counts.policies} policies · {family.counts.cases} cases
                  </p>
                </div>
                <Badge tone="blue">{family.counts.policies} policies</Badge>
              </div>
              <div className="mt-4 grid gap-3 sm:grid-cols-2">
                {family.members.map((member) => (
                  <div key={member.id} className="group rounded-xl border border-line p-3.5">
                    <div className="flex items-start justify-between">
                      <div className="flex items-center gap-2.5">
                        <span className="flex h-9 w-9 items-center justify-center rounded-full bg-navy-100 text-[11px] font-bold text-navy">
                          {initials(member.name)}
                        </span>
                        <div>
                          <p className="text-[13px] font-semibold text-navy">{member.name}</p>
                          <p className="text-[10.5px] text-ink-soft">
                            <span className="capitalize">{member.relation}</span>{member.age ? ` · ${member.age} years` : ""}
                          </p>
                        </div>
                      </div>
                      <div className="flex gap-0.5 opacity-0 transition group-hover:opacity-100">
                        <button onClick={() => setMemberModal(member)} aria-label="Edit member" className="rounded-md p-1.5 text-ink-soft hover:bg-navy/5 hover:text-navy">
                          <Pencil className="h-3.5 w-3.5" />
                        </button>
                        <button onClick={() => deleteMember(member)} aria-label="Delete member" className="rounded-md p-1.5 text-ink-soft hover:bg-danger-50 hover:text-danger">
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    </div>
                    <div className="mt-2.5 space-y-1">
                      {member.policies.length === 0 && <p className="text-[10.5px] text-ink-soft">{t("family.noPolicies")}</p>}
                      {member.policies.map((link) => (
                        <div key={link.policy_id} className="flex items-center justify-between gap-2 rounded-md bg-canvas px-2 py-1">
                          <span className="truncate text-[10.5px] text-ink-muted">{link.insurer}</span>
                          <span className="shrink-0 text-[9.5px] font-semibold uppercase tracking-wide text-brand">{link.role}</span>
                        </div>
                      ))}
                    </div>
                    {member.date_of_birth && (
                      <p className="mt-2 text-[10px] text-ink-soft">DOB {shortDate(member.date_of_birth, lang)}</p>
                    )}
                  </div>
                ))}
                <button
                  onClick={() => setMemberModal("new")}
                  className="flex min-h-[132px] flex-col items-center justify-center gap-1.5 rounded-xl border border-dashed border-line text-ink-soft transition hover:border-brand/40 hover:text-brand"
                >
                  <Plus className="h-4 w-4" />
                  <span className="text-[11.5px] font-semibold">{t("family.addMember")}</span>
                </button>
              </div>
            </Card>

            <Card className="p-5">
              <h2 className="text-[15px] font-bold">{t("family.coordination")}</h2>
              <p className="mt-1 text-[11.5px] leading-5 text-ink-muted">{t("family.coordinationHelp")}</p>
              <div className="mt-3 space-y-1.5">
                {RULES.map((rule) => (
                  <button
                    key={rule.value}
                    onClick={() => updateRule(rule.value)}
                    className={`w-full rounded-lg border px-3 py-2 text-left transition ${
                      family.coordination_rule === rule.value
                        ? "border-brand/50 bg-brand-50"
                        : "border-line hover:border-brand/30"
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <span className="text-[12px] font-semibold text-navy">{t(rule.label)}</span>
                      {family.coordination_rule === rule.value && <span className="h-2 w-2 rounded-full bg-brand" />}
                    </div>
                    <p className="mt-0.5 text-[10.5px] leading-4 text-ink-muted">{t(rule.desc)}</p>
                  </button>
                ))}
              </div>
            </Card>
          </div>

          <Card className="mt-4 p-5">
            <div className="flex items-start justify-between">
              <div>
                <h2 className="text-[15px] font-bold">{t("dashboard.graph")}</h2>
                <p className="mt-0.5 text-[11.5px] text-ink-muted">{t("family.graphSub")}</p>
              </div>
              <ArrowRight className="h-4 w-4 text-ink-soft" />
            </div>
            <div className="mt-4">
              <InsuranceGraph family={family} />
            </div>
          </Card>
        </>
      )}

      <MemberModal
        open={memberModal !== null}
        member={memberInitial}
        onClose={() => setMemberModal(null)}
        onSave={saveMember}
        saving={saving}
      />
      <FamilyModal open={familyModal} onClose={() => setFamilyModal(false)} onSave={createFamily} saving={saving} />
    </div>
  );
}

function MemberModal({
  open,
  member,
  onClose,
  onSave,
  saving,
}: {
  open: boolean;
  member: Member | null;
  onClose: () => void;
  onSave: (payload: any) => void;
  saving: boolean;
}) {
  const { t } = useI18n();
  const [form, setForm] = useState({
    name: "",
    date_of_birth: "",
    age_years: "",
    relation: "dependent",
    gender: "",
    phone: "",
    notes: "",
  });

  React.useEffect(() => {
    if (!open) return;
    setForm({
      name: member?.name || "",
      date_of_birth: member?.date_of_birth || "",
      age_years: member?.age != null ? String(member.age) : "",
      relation: member?.relation || "dependent",
      gender: member?.gender || "",
      phone: member?.phone || "",
      notes: member?.notes || "",
    });
  }, [open, member]);

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={member ? t("family.editMember") : t("family.addMember")}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button>
          <Button
            loading={saving}
            onClick={() =>
              onSave({
                name: form.name,
                date_of_birth: form.date_of_birth || null,
                age_years: form.age_years ? Number(form.age_years) : null,
                relation: form.relation,
                gender: form.gender || null,
                phone: form.phone || null,
                notes: form.notes || null,
              })
            }
          >
            {t("common.save")}
          </Button>
        </>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label={t("family.memberName")} className="sm:col-span-2">
          <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Priya Sen" />
        </Field>
        <Field label={t("family.dob")}>
          <Input type="date" value={form.date_of_birth} onChange={(e) => setForm({ ...form, date_of_birth: e.target.value })} />
        </Field>
        <Field label={`${t("family.age")} (${t("common.optional")})`}>
          <Input type="number" min={0} max={120} value={form.age_years} onChange={(e) => setForm({ ...form, age_years: e.target.value })} />
        </Field>
        <Field label={t("family.relation")}>
          <Select value={form.relation} onChange={(e) => setForm({ ...form, relation: e.target.value })}>
            <option value="self">Self</option>
            <option value="spouse">Spouse</option>
            <option value="child">Child</option>
            <option value="parent">Parent</option>
            <option value="dependent">Dependent</option>
            <option value="other">Other</option>
          </Select>
        </Field>
        <Field label={t("family.gender")}>
          <Select value={form.gender} onChange={(e) => setForm({ ...form, gender: e.target.value })}>
            <option value="">Not specified</option>
            <option value="F">Female</option>
            <option value="M">Male</option>
            <option value="O">Other</option>
          </Select>
        </Field>
        <Field label={t("family.phone")} className="sm:col-span-2">
          <Input value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} placeholder="+91…" />
        </Field>
        <Field label={t("family.notes")} className="sm:col-span-2">
          <Input value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} placeholder="Optional" />
        </Field>
      </div>
    </Modal>
  );
}

function FamilyModal({
  open,
  onClose,
  onSave,
  saving,
}: {
  open: boolean;
  onClose: () => void;
  onSave: (payload: any) => void;
  saving: boolean;
}) {
  const { t } = useI18n();
  const [name, setName] = useState("");
  const [rule, setRule] = useState("policyholder");
  return (
    <Modal
      open={open}
      onClose={onClose}
      title={t("family.createFamily")}
      width="max-w-lg"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button>
          <Button loading={saving} onClick={() => onSave({ name, coordination_rule: rule })} disabled={!name.trim()}>
            {t("common.save")}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Field label={t("family.familyName")}>
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Rao household" />
        </Field>
        <Field label={t("family.coordination")} hint={t("family.coordinationHelp")}>
          <Select value={rule} onChange={(e) => setRule(e.target.value)}>
            {RULES.map((item) => (
              <option key={item.value} value={item.value}>{t(item.label)}</option>
            ))}
          </Select>
        </Field>
      </div>
    </Modal>
  );
}
