import React, { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, CheckCircle2, Download, RefreshCw, Trash2 } from "lucide-react";
import { useApi } from "../lib/useApi";
import { useI18n } from "../lib/i18n";
import { api, downloadFile, fileUrl } from "../lib/api";
import { DocumentItem } from "../lib/types";
import {
  Alert,
  Badge,
  Button,
  Card,
  Confidence,
  Field,
  Input,
  LoadingBlock,
  PageHeader,
  Select,
  Spinner,
  StatusBadge,
  useToast,
} from "../components/ui";
import { fileSize, shortDate } from "../lib/format";

const TYPES = ["invoice", "estimate", "policy", "radiology", "prescription", "discharge", "transcript", "unknown"];

function humanise(key: string): string {
  return key.replace(/_/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export default function DocumentDetail() {
  const { documentId } = useParams();
  const { t, lang } = useI18n();
  const { notify } = useToast();
  const navigate = useNavigate();
  const document = useApi<DocumentItem>(documentId ? `/api/documents/${documentId}` : null, [documentId]);
  const [preview, setPreview] = useState<string | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [reprocessing, setReprocessing] = useState(false);
  const [docType, setDocType] = useState("");

  useEffect(() => {
    if (!documentId) return;
    let url: string | null = null;
    fileUrl(`/api/documents/${documentId}/file`)
      .then((value) => {
        url = value;
        setPreview(value);
      })
      .catch((error) => setPreviewError(error instanceof Error ? error.message : "Preview unavailable."));
    return () => {
      if (url) URL.revokeObjectURL(url);
    };
  }, [documentId]);

  useEffect(() => {
    if (document.data) {
      setDocType(document.data.doc_type);
      setEdits({});
    }
  }, [document.data?.id]);

  if (document.loading && !document.data) return <LoadingBlock />;
  if (document.error) return <Alert tone="danger">{document.error}</Alert>;
  if (!document.data) return null;
  const doc = document.data;
  const fields = Object.entries(doc.fields || {});

  const save = async (confirm = false) => {
    setSaving(true);
    try {
      if (Object.keys(edits).length) {
        await api.patch(`/api/documents/${doc.id}`, { doc_type: docType, fields: edits });
      } else if (docType !== doc.doc_type) {
        await api.patch(`/api/documents/${doc.id}`, { doc_type: docType });
      }
      if (confirm) await api.post(`/api/documents/${doc.id}/confirm`, {});
      notify(confirm ? "Document confirmed." : "Corrections saved.", "success");
      document.reload();
    } catch (error) {
      notify(error instanceof Error ? error.message : "Could not save.", "error");
    } finally {
      setSaving(false);
    }
  };

  const reprocess = async () => {
    setReprocessing(true);
    try {
      await api.post(`/api/documents/${doc.id}/reprocess`, {});
      notify("Document read again.", "success");
      document.reload();
    } catch (error) {
      notify(error instanceof Error ? error.message : "Could not reprocess.", "error");
    } finally {
      setReprocessing(false);
    }
  };

  const remove = async () => {
    if (!window.confirm(t("documents.deleteConfirm"))) return;
    try {
      await api.del(`/api/documents/${doc.id}`);
      notify("Document deleted.", "success");
      navigate("/app/documents");
    } catch (error) {
      notify(error instanceof Error ? error.message : "Could not delete.", "error");
    }
  };

  return (
    <div>
      <Link to="/app/documents" className="mb-4 inline-flex items-center gap-1 text-[11.5px] font-semibold text-ink-muted hover:text-navy">
        <ArrowLeft className="h-3.5 w-3.5" /> {t("documents.title")}
      </Link>
      <PageHeader
        title={doc.filename}
        subtitle={`${t(`documents.typeLabels.${doc.doc_type}`)} · ${fileSize(doc.size_bytes)} · ${shortDate(doc.created_at, lang)}`}
        actions={
          <>
            <StatusBadge status={doc.status} />
            <Button variant="secondary" onClick={() => downloadFile(`/api/documents/${doc.id}/file`, doc.filename)} icon={<Download className="h-4 w-4" />}>
              {t("common.download")}
            </Button>
            <Button variant="ghost" onClick={remove} icon={<Trash2 className="h-4 w-4" />}>{t("common.delete")}</Button>
          </>
        }
      />

      <div className="grid gap-4 lg:grid-cols-[0.9fr_1.1fr]">
        <Card className="overflow-hidden">
          <div className="flex items-center justify-between border-b border-line px-4 py-2.5">
            <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-ink-soft">Original</p>
            <span className="text-[10px] text-ink-soft">{doc.method === "ocr" ? `OCR ${Math.round(doc.mean_ocr_confidence || 0)}%` : doc.method}</span>
          </div>
          <div className="flex min-h-[360px] items-center justify-center bg-canvas p-3">
            {previewError ? (
              <p className="text-[12px] text-ink-soft">{previewError}</p>
            ) : !preview ? (
              <Spinner />
            ) : doc.mime.includes("pdf") ? (
              <iframe src={preview} title="Document preview" className="h-[520px] w-full rounded-lg border border-line bg-white" />
            ) : doc.mime.startsWith("image/") ? (
              <img src={preview} alt={doc.filename} className="max-h-[560px] w-auto rounded-lg border border-line bg-white object-contain" />
            ) : (
              <p className="text-[12px] text-ink-soft">Preview is not available for this file type.</p>
            )}
          </div>
        </Card>

        <div className="space-y-4">
          <Card className="p-5">
            <div className="flex items-center justify-between">
              <h2 className="text-[15px] font-bold">{t("documents.issues")}</h2>
              <Badge tone={doc.issues.length ? "amber" : "teal"}>{doc.issues.length || "clear"}</Badge>
            </div>
            <div className="mt-2 space-y-1.5">
              {doc.issues.length === 0 && <p className="text-[11.5px] text-ink-muted">No extraction issues were reported.</p>}
              {doc.issues.map((issue, index) => (
                <p key={index} className="rounded-lg bg-amber-50 px-2.5 py-1.5 text-[11px] leading-4 text-[#6B4A10]">{issue}</p>
              ))}
            </div>
            <div className="mt-4 grid grid-cols-2 gap-3 border-t border-line pt-3">
              <Field label={t("documents.type")}>
                <Select value={docType} onChange={(event) => setDocType(event.target.value)}>
                  {TYPES.map((option) => (
                    <option key={option} value={option}>{t(`documents.typeLabels.${option}`)}</option>
                  ))}
                </Select>
              </Field>
              <div>
                <p className="text-[11px] font-semibold text-navy">{t("documents.confidence")}</p>
                <div className="mt-2"><Confidence value={doc.classification_confidence} /></div>
                <p className="mt-1 text-[10px] text-ink-soft">{doc.classification_evidence?.[0] || ""}</p>
              </div>
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              <Button size="sm" variant="secondary" loading={reprocessing} onClick={reprocess} icon={<RefreshCw className="h-3.5 w-3.5" />}>
                Read again
              </Button>
              <Button size="sm" loading={saving} onClick={() => save(false)}>{t("common.save")}</Button>
              <Button size="sm" variant="teal" onClick={() => save(true)} icon={<CheckCircle2 className="h-3.5 w-3.5" />}>
                {t("common.confirm")}
              </Button>
            </div>
          </Card>

          <Card className="p-5">
            <h2 className="text-[15px] font-bold">Extracted fields</h2>
            <p className="mt-0.5 text-[11px] text-ink-soft">Confidence is measured from OCR or exact PDF text; low values are flagged.</p>
            <div className="mt-3 divide-y divide-line">
              {fields.map(([key, field]) => (
                <div key={key} className="grid gap-2 py-2.5 sm:grid-cols-[150px_1fr]">
                  <div>
                    <p className="text-[10.5px] font-semibold text-ink-muted">{humanise(key)}</p>
                    <div className="mt-1 flex items-center gap-2">
                      <Confidence value={field.confidence} />
                      <span className="text-[9px] uppercase text-ink-soft">{field.source}</span>
                    </div>
                  </div>
                  <div>
                    {typeof field.value === "string" || typeof field.value === "number" ? (
                      <Input
                        value={edits[key] ?? String(field.value ?? "")}
                        onChange={(event) => setEdits({ ...edits, [key]: event.target.value })}
                        className="py-1.5 text-[11.5px]"
                      />
                    ) : (
                      <pre className="max-h-32 overflow-auto rounded-lg bg-canvas px-2 py-1.5 text-[10px] leading-4 text-ink-muted">
                        {JSON.stringify(field.value, null, 2)}
                      </pre>
                    )}
                    {field.evidence && <p className="mt-1 line-clamp-2 text-[9.5px] text-ink-soft">{field.evidence}</p>}
                  </div>
                </div>
              ))}
              {fields.length === 0 && <p className="py-4 text-[11.5px] text-ink-soft">No fields were extracted.</p>}
            </div>
          </Card>
        </div>
      </div>

      {doc.lines.length > 0 && (
        <Card className="mt-4 overflow-hidden">
          <div className="flex items-center justify-between border-b border-line px-5 py-3">
            <h2 className="text-[15px] font-bold">{t("documents.lines")}</h2>
            <Badge tone="blue">{doc.lines.length}</Badge>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] text-left text-[11.5px]">
              <thead>
                <tr className="border-b border-line bg-canvas text-[9.5px] uppercase tracking-[0.06em] text-ink-soft">
                  <th className="px-4 py-2 font-semibold">Service</th>
                  <th className="px-3 py-2 font-semibold">CPT</th>
                  <th className="px-3 py-2 text-right font-semibold">Qty</th>
                  <th className="px-3 py-2 text-right font-semibold">Amount</th>
                  <th className="px-3 py-2 font-semibold">Code source</th>
                  <th className="px-4 py-2 font-semibold">Notes</th>
                </tr>
              </thead>
              <tbody>
                {doc.lines.map((line, index) => (
                  <tr key={index} className="border-b border-line/70 last:border-0">
                    <td className="max-w-[260px] px-4 py-2.5 font-medium text-navy">{line.description}</td>
                    <td className="px-3 py-2.5 font-mono text-[10.5px]">{line.cpt_code || "—"}</td>
                    <td className="px-3 py-2.5 text-right tabular-nums">{line.quantity}</td>
                    <td className="px-3 py-2.5 text-right font-semibold tabular-nums">₹{Number(line.amount || 0).toLocaleString("en-IN")}</td>
                    <td className="px-3 py-2.5">
                      <span className={`rounded-full px-1.5 py-0.5 text-[9px] font-bold uppercase ${line.code_source === "printed" ? "bg-teal-50 text-teal-600" : "bg-amber-50 text-amber"}`}>
                        {line.code_source}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 text-[10px] leading-4 text-ink-soft">{line.issues.join("; ") || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  );
}
