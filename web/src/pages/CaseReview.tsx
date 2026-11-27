import React, { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  AlertTriangle,
  ArrowLeft,
  Check,
  CheckCircle2,
  FileText,
} from "lucide-react";
import { useApi } from "../lib/useApi";
import { useI18n } from "../lib/i18n";
import { api } from "../lib/api";
import { CaseDetail, ReviewItem } from "../lib/types";
import {
  Alert,
  Badge,
  Button,
  Card,
  Confidence,
  EmptyState,
  Input,
  LoadingBlock,
  PageHeader,
  useToast,
} from "../components/ui";

export default function CaseReview() {
  const { caseId } = useParams();
  const { t } = useI18n();
  const { notify } = useToast();
  const navigate = useNavigate();
  const detail = useApi<CaseDetail>(caseId ? `/api/cases/${caseId}` : null, [
    caseId,
  ]);
  const [decisions, setDecisions] = useState<
    Record<number, { status: "accepted" | "corrected"; value: string }>
  >({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!detail.data) return;
    const next: Record<
      number,
      { status: "accepted" | "corrected"; value: string }
    > = {};
    for (const item of detail.data.review_items) {
      if (item.status === "pending" && item.extracted_value?.trim()) {
        next[item.id] = {
          status: "accepted",
          value: item.extracted_value,
        };
      }
    }
    setDecisions(next);
  }, [detail.data?.id, detail.data?.review_pending]);

  if (detail.loading && !detail.data) return <LoadingBlock />;
  if (detail.error) return <Alert tone="danger">{detail.error}</Alert>;
  if (!detail.data) return null;
  const data = detail.data;
  const pending = data.review_items.filter((item) => item.status === "pending");
  const resolved = data.review_items.filter((item) => item.status !== "pending");
  const pausedWithoutReview =
    data.status === "awaiting_review" && pending.length === 0;
  const blockingGaps = data.gaps.filter((gap) => gap.severity === "blocking");

  const documents = new Map<number, string>();
  for (const doc of data.documents) {
    documents.set(doc.id, doc.filename);
  }

  const submit = async () => {
    if (!caseId) return;
    const unresolved = pending.filter((item) => {
      const decision = decisions[item.id];

      return (
        !decision ||
        !decision.value.trim() ||
        (decision.status === "accepted" && !item.extracted_value?.trim())
      );
    });

    if (unresolved.length > 0) {
      setError(
        `Complete all ${unresolved.length} unresolved field(s). Enter a value or correct the extracted value before submitting.`,
      );
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const items = Object.entries(decisions).map(([id, value]) => ({
        id: Number(id),
        status: value.status,
        value: value.value,
      }));
      await api.post(`/api/cases/${caseId}/review`, { items, confirm: true });
      notify("Review saved. The supervisor is resuming the case.", "success");
      await api.post(`/api/cases/${caseId}/analyze`, {});
      navigate(`/app/cases/${caseId}/run`);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Could not submit the review.",
      );
    } finally {
      setBusy(false);
    }
  };

  const acceptAll = () => {
    const next = { ...decisions };

    for (const item of pending) {
      if (item.extracted_value?.trim()) {
        next[item.id] = {
          status: "accepted",
          value: item.extracted_value,
        };
      }
    }

    setDecisions(next);
  };

  return (
    <div>
      <Link
        to={`/app/cases/${caseId}/run`}
        className="mb-4 inline-flex items-center gap-1 text-[11.5px] font-semibold text-ink-muted hover:text-navy"
      >
        <ArrowLeft className="h-3.5 w-3.5" /> {t("run.title")}
      </Link>
      <PageHeader
        eyebrow={data.family?.name}
        title={t("review.title")}
        subtitle={t("review.subtitle")}
        actions={
          <Badge tone={pending.length || pausedWithoutReview ? "amber" : "teal"}>
            {pending.length
              ? `${pending.length} ${t("review.pending")}`
              : pausedWithoutReview
                ? "Action required"
                : t("review.complete")}
          </Badge>
        }
      />

      {pending.length === 0 ? (
        pausedWithoutReview ? (
          <div className="space-y-3">
            <Alert tone="warning" title="Workflow paused">
              {blockingGaps.length
                ? blockingGaps.map((gap) => `${gap.title}: ${gap.detail}${gap.action ? ` ${gap.action}` : ""}`).join(" ")
                : "There are no pending review fields. Check the case activity for the required next step."}
            </Alert>
            <Link to={`/app/cases/${caseId}/run`}>
              <Button variant="secondary">{t("run.title")}</Button>
            </Link>
          </div>
        ) : (
          <EmptyState
            title={t("review.complete")}
            body={t("review.none")}
            icon={<CheckCircle2 className="h-5 w-5" />}
            action={
              <Link to={`/app/cases/${caseId}/run`}>
                <Button>{t("run.start")}</Button>
              </Link>
            }
          />
        )
      ) : (
        <div className="grid gap-4 lg:grid-cols-[1fr_300px]">
          <div className="space-y-3">
            {pending.map((item) => (
              <ReviewCard
                key={item.id}
                item={item}
                filename={
                  item.document_id ? documents.get(item.document_id) : undefined
                }
                decision={decisions[item.id]}
                onChange={(value) =>
                  setDecisions({ ...decisions, [item.id]: value })
                }
              />
            ))}
          </div>
          <div className="space-y-4">
            <Card className="sticky top-20 p-5">
              <h2 className="text-[14px] font-bold">{t("review.title")}</h2>
              <p className="mt-1 text-[11.5px] leading-5 text-ink-muted">
                {t("review.hint")}
              </p>
              <div className="mt-4 space-y-2">
                <Button
                  variant="secondary"
                  className="w-full"
                  onClick={acceptAll}
                  icon={<Check className="h-4 w-4" />}
                >
                  Accept every extracted value
                </Button>
                <Button
                  className="w-full"
                  loading={busy}
                  onClick={submit}
                  icon={<CheckCircle2 className="h-4 w-4" />}
                >
                  {t("review.submit")}
                </Button>
              </div>
              {error && (
                <div className="mt-3">
                  <Alert tone="danger">{error}</Alert>
                </div>
              )}
              <div className="mt-4 border-t border-line pt-3 text-[10px] leading-4 text-ink-soft">
                Values you correct are written back to the document and used in
                the calculation. Corrected values are marked as human-reviewed
                in the audit trail.
              </div>
            </Card>
          </div>
        </div>
      )}

      {resolved.length > 0 && (
        <Card className="mt-4 p-4">
          <h2 className="text-[13px] font-bold">Resolved review fields</h2>
          <div className="mt-3 space-y-2">
            {resolved.map((item) => (
              <div
                key={item.id}
                className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-canvas px-3 py-2"
              >
                <span className="text-[11.5px] font-medium text-navy">
                  {item.label}
                </span>
                <span className="flex items-center gap-2">
                  <Badge tone={item.status === "accepted" ? "teal" : "blue"}>
                    {item.status === "accepted" ? "Confirmed" : "Corrected"}
                  </Badge>
                  <span className="text-[11px] text-ink-soft">
                    {item.corrected_value ?? item.extracted_value ?? "—"}
                  </span>
                </span>
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}

function ReviewCard({
  item,
  filename,
  decision,
  onChange,
}: {
  item: ReviewItem;
  filename?: string;
  decision?: { status: "accepted" | "corrected"; value: string };
  onChange: (value: {
    status: "accepted" | "corrected";
    value: string;
  }) => void;
}) {
  const { t } = useI18n();
  const [editing, setEditing] = useState(false);
  const value = decision?.value ?? item.extracted_value ?? "";
  return (
    <Card className="p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="text-[12.5px] font-bold text-navy">{item.label}</p>
          <p className="mt-0.5 flex items-center gap-1 text-[10px] text-ink-soft">
            <FileText className="h-3 w-3" /> {filename || "document"}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Confidence value={item.confidence} />
          {item.status === "pending" && (
            <Badge tone={decision?.status === "corrected" ? "blue" : "slate"}>
              {decision?.status || "pending"}
            </Badge>
          )}
        </div>
      </div>
      <div className="mt-3 grid gap-3 sm:grid-cols-[1fr_auto]">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.06em] text-ink-soft">
            {t("review.value")}
          </p>
          {editing ? (
            <Input
              value={value}
              onChange={(event) =>
                onChange({ status: "corrected", value: event.target.value })
              }
              className="mt-1"
              autoFocus
            />
          ) : (
            <p
              className={`mt-1 rounded-lg px-2.5 py-1.5 text-[12.5px] font-medium ${decision?.status === "corrected" ? "bg-brand-50 text-brand-600" : "bg-canvas text-navy"}`}
            >
              {value || "—"}
            </p>
          )}
        </div>
        <div className="flex items-end gap-1.5">
          <Button
            size="sm"
            disabled={!item.extracted_value?.trim()}
            variant={
              decision?.status === "accepted" && !editing ? "teal" : "secondary"
            }
            onClick={() => {
              onChange({
                status: "accepted",
                value: item.extracted_value || "",
              });
              setEditing(false);
            }}
          >
            {t("review.accept")}
          </Button>
          <Button
            size="sm"
            variant={editing ? "primary" : "ghost"}
            onClick={() => {
              setEditing(!editing);
              if (!editing) onChange({ status: "corrected", value });
            }}
          >
            {editing ? t("common.save") : t("review.correct")}
          </Button>
        </div>
      </div>
      {item.reason && (
        <p className="mt-2 flex items-start gap-1.5 rounded-lg bg-amber-50 px-2.5 py-1.5 text-[10.5px] leading-4 text-[#6B4A10]">
          <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" /> {item.reason}
        </p>
      )}
      {item.source_text && (
        <p className="mt-2 border-l-2 border-line pl-2 text-[10px] italic leading-4 text-ink-soft">
          “{item.source_text.slice(0, 240)}”
        </p>
      )}
    </Card>
  );
}
