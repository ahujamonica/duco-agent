import React, { useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ArrowRight, FileUp, Plus, ShieldCheck, UploadCloud } from "lucide-react";
import { useI18n } from "../lib/i18n";
import { useApi } from "../lib/useApi";
import { api } from "../lib/api";
import { Family, Policy } from "../lib/types";
import {
  Alert,
  Badge,
  Button,
  Card,
  Confidence,
  EmptyState,
  Field,
  LoadingBlock,
  Modal,
  PageHeader,
  Select,
  Spinner,
  StatusBadge,
  useToast,
} from "../components/ui";
import { inr, pct, shortDate } from "../lib/format";
import { PolicyForm } from "../components/PolicyForm";

export default function PoliciesPage() {
  const { t, lang } = useI18n();
  const { notify } = useToast();
  const navigate = useNavigate();
  const families = useApi<{ families: Family[] }>("/api/families");
  const [familyId, setFamilyId] = useState<number | null>(null);
  const list = families.data?.families || [];
  const activeFamilyId = familyId || list[0]?.id || null;
  const family = useApi<Family>(activeFamilyId ? `/api/families/${activeFamilyId}` : null, [activeFamilyId]);
  const policies = useApi<{ policies: Policy[] }>(activeFamilyId ? `/api/policies?family_id=${activeFamilyId}` : null, [activeFamilyId]);
  const [showForm, setShowForm] = useState(false);
  const [showImport, setShowImport] = useState(false);

  if (families.loading) return <LoadingBlock />;
  if (list.length === 0) {
    return (
      <div>
        <PageHeader title={t("policies.title")} subtitle={t("policies.subtitle")} />
        <EmptyState
          title={t("cases.needFamily")}
          body="A policy belongs to a household. Create one first, then add its policies."
          icon={<ShieldCheck className="h-5 w-5" />}
          action={<Link to="/app/family"><Button>{t("family.createFamily")}</Button></Link>}
        />
      </div>
    );
  }

  return (
    <div>
      <PageHeader
        title={t("policies.title")}
        subtitle={t("policies.subtitle")}
        actions={
          <>
            {list.length > 1 && (
              <Select value={activeFamilyId || ""} onChange={(event) => setFamilyId(Number(event.target.value))} className="min-w-[160px]">
                {list.map((item) => (
                  <option key={item.id} value={item.id}>{item.name}</option>
                ))}
              </Select>
            )}
            <Button variant="secondary" onClick={() => setShowImport(true)} icon={<FileUp className="h-4 w-4" />}>
              {t("policies.import")}
            </Button>
            <Button onClick={() => setShowForm(true)} icon={<Plus className="h-4 w-4" />}>
              {t("policies.add")}
            </Button>
          </>
        }
      />

      {policies.loading && !policies.data ? (
        <LoadingBlock />
      ) : (policies.data?.policies.length || 0) === 0 ? (
        <EmptyState
          title={t("policies.noPolicies")}
          body={t("policies.noPoliciesBody")}
          icon={<ShieldCheck className="h-5 w-5" />}
          action={
            <div className="flex gap-2">
              <Button onClick={() => setShowForm(true)}>{t("policies.add")}</Button>
              <Button variant="secondary" onClick={() => setShowImport(true)}>{t("policies.import")}</Button>
            </div>
          }
        />
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {policies.data!.policies.map((policy) => {
            const terms = policy.current_version?.terms;
            return (
              <Card key={policy.id} className="group p-5 transition hover:border-brand/30">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-navy text-[11px] font-bold text-white">
                        {policy.insurer_name.slice(0, 2).toUpperCase()}
                      </span>
                      <div className="min-w-0">
                        <p className="truncate text-[14px] font-bold text-navy">{policy.insurer_name}</p>
                        <p className="truncate text-[11px] text-ink-muted">{policy.plan_name}</p>
                      </div>
                    </div>
                  </div>
                  <StatusBadge status={policy.status} />
                </div>
                <p className="mt-3 font-mono text-[10.5px] text-ink-soft">{policy.policy_number}</p>
                <div className="mt-3 grid grid-cols-3 gap-2 border-y border-line py-3 text-[10.5px]">
                  <div>
                    <p className="text-ink-soft">Deductible</p>
                    <p className="mt-0.5 text-[12.5px] font-semibold tabular-nums text-navy">{inr(terms?.deductible || 0)}</p>
                  </div>
                  <div>
                    <p className="text-ink-soft">Co-insurance</p>
                    <p className="mt-0.5 text-[12.5px] font-semibold tabular-nums text-navy">{pct(terms?.coinsurance_member || 0)}</p>
                  </div>
                  <div>
                    <p className="text-ink-soft">OOP max</p>
                    <p className="mt-0.5 text-[12.5px] font-semibold tabular-nums text-navy">{inr(terms?.oop_max || 0)}</p>
                  </div>
                </div>
                <div className="mt-3 flex flex-wrap items-center gap-1.5">
                  {policy.members.map((member) => (
                    <span key={member.member_id} className="rounded-full bg-canvas px-2 py-0.5 text-[9.5px] font-medium text-ink-muted">
                      {member.name?.split(" ")[0]} · {member.role}
                    </span>
                  ))}
                </div>
                <div className="mt-3 flex items-center justify-between">
                  <span className="text-[10px] text-ink-soft">
                    v{policy.current_version?.version} · {policy.version_count} version{policy.version_count === 1 ? "" : "s"} ·{" "}
                    {shortDate(policy.start_date, lang)} → {shortDate(policy.end_date, lang)}
                  </span>
                  <button onClick={() => navigate(`/app/policies/${policy.id}`)} className="flex items-center gap-1 text-[11px] font-bold text-brand hover:text-brand-600">
                    {t("policies.view")} <ArrowRight className="h-3 w-3" />
                  </button>
                </div>
              </Card>
            );
          })}
        </div>
      )}

      {family.data && (
        <>
          <Modal open={showForm} onClose={() => setShowForm(false)} title={t("policies.add")} width="max-w-5xl">
            <PolicyForm
              family={family.data}
              onCancel={() => setShowForm(false)}
              onSaved={() => {
                setShowForm(false);
                policies.reload();
                family.reload();
              }}
            />
          </Modal>
          <ImportPolicy
            open={showImport}
            family={family.data}
            onClose={() => setShowImport(false)}
            onSaved={() => {
              setShowImport(false);
              policies.reload();
              family.reload();
            }}
          />
        </>
      )}
    </div>
  );
}

function ImportPolicy({
  open,
  family,
  onClose,
  onSaved,
}: {
  open: boolean;
  family: Family;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { t } = useI18n();
  const { notify } = useToast();
  const inputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [extracted, setExtracted] = useState<any>(null);
  const [filename, setFilename] = useState<string>("");

  const upload = async (file: File) => {
    setBusy(true);
    setError(null);
    setExtracted(null);
    setFilename(file.name);
    try {
      const form = new FormData();
      form.append("family_id", String(family.id));
      form.append("doc_type", "policy");
      form.append("file", file);
      const uploaded = await api.upload<{ document: any; duplicate: boolean }>("/api/documents/upload", form);
      const documentId = uploaded.document.id;
      const result = await api.post<any>("/api/policies/extract", { document_id: documentId });
      setExtracted(result);
      if (uploaded.duplicate) notify("This policy document was already uploaded; reusing its extraction.", "info");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not read the policy.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={t("policies.importTitle")}
      width={extracted ? "max-w-5xl" : "max-w-xl"}
    >
      {!extracted ? (
        <div className="space-y-4">
          <p className="text-[12.5px] leading-5 text-ink-muted">{t("policies.importBody")}</p>
          <button
            onClick={() => inputRef.current?.click()}
            disabled={busy}
            className="flex w-full flex-col items-center justify-center rounded-xl2 border border-dashed border-line px-6 py-12 text-center transition hover:border-brand/40 hover:bg-brand-50/30"
          >
            {busy ? <Spinner /> : <UploadCloud className="h-7 w-7 text-brand" />}
            <p className="mt-2 text-[13px] font-semibold text-navy">{busy ? "Reading the policy…" : t("documents.drop")}</p>
            <p className="mt-1 text-[10.5px] text-ink-soft">{t("documents.supported")}</p>
          </button>
          <input
            ref={inputRef}
            type="file"
            accept=".pdf,.png,.jpg,.jpeg,.webp,.tif,.tiff"
            className="hidden"
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) upload(file);
            }}
          />
          {error && <Alert tone="danger">{error}</Alert>}
          <div className="rounded-lg bg-canvas px-3 py-2 text-[11px] leading-4 text-ink-muted">
            Values are extracted with a confidence score. Nothing is saved until you confirm every field.
          </div>
        </div>
      ) : (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-canvas px-3 py-2">
            <div className="text-[11.5px] text-ink-muted">
              <span className="font-semibold text-navy">{filename}</span> · {extracted.document.mean_ocr_confidence ? `OCR ${Math.round(extracted.document.mean_ocr_confidence)}%` : "text PDF"}
            </div>
            <button onClick={() => setExtracted(null)} className="text-[11px] font-semibold text-brand">Choose another file</button>
          </div>
          {extracted.missing.length > 0 && (
            <Alert tone="warning" title={t("policies.missing")}>
              {extracted.missing.join(", ")} could not be read confidently. Confirm or enter them below.
            </Alert>
          )}
          <div className="grid gap-2 sm:grid-cols-3">
            {Object.entries(extracted.confidence || {}).slice(0, 6).map(([key, value]) => (
              <div key={key} className="flex items-center justify-between rounded-lg border border-line px-2.5 py-1.5">
                <span className="text-[10.5px] capitalize text-ink-muted">{key.replace(/_/g, " ")}</span>
                <Confidence value={Number(value)} />
              </div>
            ))}
          </div>
          <PolicyForm family={family} extracted={extracted} onCancel={onClose} onSaved={onSaved} />
        </div>
      )}
    </Modal>
  );
}
