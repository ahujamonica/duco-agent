import React, { useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { FileImage, FileText, RefreshCw, Trash2, UploadCloud } from "lucide-react";
import { useI18n } from "../lib/i18n";
import { useApi } from "../lib/useApi";
import { api } from "../lib/api";
import { DocumentItem, Family } from "../lib/types";
import {
  Alert,
  Badge,
  Button,
  Card,
  Confidence,
  EmptyState,
  Field,
  LoadingBlock,
  PageHeader,
  Select,
  Spinner,
  StatusBadge,
  useToast,
} from "../components/ui";
import { fileSize, shortDate } from "../lib/format";

const TYPES = ["invoice", "estimate", "policy", "radiology", "prescription", "discharge", "transcript"];

export default function DocumentsPage() {
  const { t, lang } = useI18n();
  const { notify } = useToast();
  const navigate = useNavigate();
  const families = useApi<{ families: Family[] }>("/api/families");
  const [familyId, setFamilyId] = useState<number | null>(null);
  const list = families.data?.families || [];
  const activeFamilyId = familyId || list[0]?.id || null;
  const documents = useApi<{ documents: DocumentItem[] }>(
    activeFamilyId ? `/api/documents?family_id=${activeFamilyId}` : null,
    [activeFamilyId]
  );
  const [type, setType] = useState("auto");
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const upload = async (files: FileList | File[]) => {
    if (!activeFamilyId) return;
    setBusy(true);
    setError(null);
    try {
      for (const file of Array.from(files)) {
        const form = new FormData();
        form.append("family_id", String(activeFamilyId));
        form.append("doc_type", type);
        form.append("file", file);
        const result = await api.upload<{ document: DocumentItem; duplicate: boolean; message: string }>("/api/documents/upload", form);
        notify(result.duplicate ? t("documents.duplicate") : `${file.name}: ${result.document.doc_type} · ${Math.round(result.document.classification_confidence * 100)}% confidence`, result.document.status === "failed" ? "error" : "success");
      }
      documents.reload();
      families.reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed.");
    } finally {
      setBusy(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  };

  const remove = async (doc: DocumentItem) => {
    if (!window.confirm(t("documents.deleteConfirm"))) return;
    try {
      await api.del(`/api/documents/${doc.id}`);
      notify("Document deleted.", "success");
      documents.reload();
    } catch (err) {
      notify(err instanceof Error ? err.message : "Could not delete.", "error");
    }
  };

  if (families.loading) return <LoadingBlock />;

  return (
    <div>
      <PageHeader
        title={t("documents.title")}
        subtitle={t("documents.subtitle")}
        actions={
          list.length > 1 ? (
            <Select value={activeFamilyId || ""} onChange={(event) => setFamilyId(Number(event.target.value))} className="min-w-[160px]">
              {list.map((family) => (
                <option key={family.id} value={family.id}>{family.name}</option>
              ))}
            </Select>
          ) : undefined
        }
      />

      {list.length === 0 ? (
        <EmptyState title={t("cases.needFamily")} body="Create a household before uploading documents." action={<Link to="/app/family"><Button>{t("family.createFamily")}</Button></Link>} icon={<FileText className="h-5 w-5" />} />
      ) : (
        <>
          <Card className="p-5">
            <div className="grid gap-4 lg:grid-cols-[1fr_220px]">
              <button
                type="button"
                onClick={() => inputRef.current?.click()}
                onDragOver={(event) => {
                  event.preventDefault();
                  setDragging(true);
                }}
                onDragLeave={() => setDragging(false)}
                onDrop={(event) => {
                  event.preventDefault();
                  setDragging(false);
                  if (event.dataTransfer.files.length) upload(event.dataTransfer.files);
                }}
                className={`flex min-h-[170px] flex-col items-center justify-center rounded-xl2 border border-dashed px-6 text-center transition ${
                  dragging ? "border-brand bg-brand-50/60" : "border-line hover:border-brand/40 hover:bg-brand-50/30"
                }`}
                disabled={busy}
              >
                {busy ? <Spinner /> : <UploadCloud className="h-7 w-7 text-brand" />}
                <p className="mt-2 text-[13.5px] font-semibold text-navy">{busy ? t("documents.uploading") : t("documents.drop")}</p>
                <p className="mt-1 text-[10.5px] text-ink-soft">{t("documents.supported")}</p>
              </button>
              <div className="space-y-3">
                <Field label={t("documents.type")} hint="Auto-detection reads the document and tells you what it found.">
                  <Select value={type} onChange={(event) => setType(event.target.value)}>
                    <option value="auto">{t("documents.auto")}</option>
                    {TYPES.map((option) => (
                      <option key={option} value={option}>{t(`documents.typeLabels.${option}`)}</option>
                    ))}
                  </Select>
                </Field>
                <div className="rounded-lg bg-canvas px-3 py-2 text-[10.5px] leading-4 text-ink-muted">
                  Scans are read with OCR using several preprocessing passes. Low-confidence fields are flagged for your review.
                </div>
              </div>
            </div>
            <input
              ref={inputRef}
              type="file"
              multiple
              accept=".pdf,.png,.jpg,.jpeg,.webp,.tif,.tiff,.txt"
              className="hidden"
              onChange={(event) => event.target.files && upload(event.target.files)}
            />
            {error && <div className="mt-3"><Alert tone="danger">{error}</Alert></div>}
          </Card>

          <div className="mt-5">
            {documents.loading && !documents.data ? (
              <LoadingBlock />
            ) : (documents.data?.documents.length || 0) === 0 ? (
              <EmptyState title={t("documents.noDocuments")} body={t("documents.noDocumentsBody")} icon={<FileImage className="h-5 w-5" />} />
            ) : (
              <div className="grid gap-3 md:grid-cols-2">
                {documents.data!.documents.map((doc) => (
                  <Card key={doc.id} className="group p-4 transition hover:border-brand/30">
                    <div className="flex items-start justify-between gap-3">
                      <div className="flex min-w-0 items-start gap-3">
                        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-canvas text-brand">
                          {doc.mime.includes("pdf") ? <FileText className="h-5 w-5" /> : <FileImage className="h-5 w-5" />}
                        </span>
                        <div className="min-w-0">
                          <p className="truncate text-[12.5px] font-semibold text-navy">{doc.filename}</p>
                          <p className="mt-0.5 text-[10.5px] text-ink-soft">
                            {t(`documents.typeLabels.${doc.doc_type}`)} · {fileSize(doc.size_bytes)} · {shortDate(doc.created_at, lang)}
                          </p>
                        </div>
                      </div>
                      <StatusBadge status={doc.status} />
                    </div>
                    <div className="mt-3 flex flex-wrap items-center gap-3 text-[10.5px] text-ink-soft">
                      <span className="flex items-center gap-1.5">
                        {t("documents.confidence")} <Confidence value={doc.classification_confidence} />
                      </span>
                      <span>{doc.method === "ocr" ? `OCR ${Math.round(doc.mean_ocr_confidence || 0)}%` : doc.method}</span>
                      <span>{doc.lines.length} lines</span>
                      {doc.issues.length > 0 && <Badge tone="amber">{doc.issues.length} notes</Badge>}
                    </div>
                    <div className="mt-3 flex items-center justify-between border-t border-line pt-2.5">
                      <button onClick={() => navigate(`/app/documents/${doc.id}`)} className="text-[11px] font-bold text-brand">
                        {t("documents.review")} →
                      </button>
                      <button onClick={() => remove(doc)} aria-label="Delete" className="rounded-md p-1 text-ink-soft opacity-0 transition group-hover:opacity-100 hover:bg-danger-50 hover:text-danger">
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  </Card>
                ))}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
