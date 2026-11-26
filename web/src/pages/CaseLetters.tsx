import React from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, Download, FileCheck2, Info } from "lucide-react";
import { useApi } from "../lib/useApi";
import { useI18n } from "../lib/i18n";
import { api, downloadFile } from "../lib/api";
import { Alert, Badge, Button, Card, EmptyState, LoadingBlock, PageHeader, StatusBadge, useToast } from "../components/ui";
import { shortDate } from "../lib/format";

export default function CaseLetters() {
  const { caseId } = useParams();
  const { t, lang } = useI18n();
  const { notify } = useToast();
  const letters = useApi<{ letters: any[] }>(caseId ? `/api/cases/${caseId}/letters` : null, [caseId]);

  if (letters.loading && !letters.data) return <LoadingBlock />;
  if (letters.error) return <Alert tone="danger">{letters.error}</Alert>;
  const list = letters.data?.letters || [];

  return (
    <div>
      <Link to={`/app/cases/${caseId}`} className="mb-4 inline-flex items-center gap-1 text-[11.5px] font-semibold text-ink-muted hover:text-navy">
        <ArrowLeft className="h-3.5 w-3.5" /> {t("results.title")}
      </Link>
      <PageHeader title={t("letters.title")} subtitle={t("letters.subtitle")} actions={<Badge tone="amber">{t("common.simulated")}</Badge>} />

      {list.length === 0 ? (
        <EmptyState title={t("letters.none")} body={t("letters.noneBody")} icon={<FileCheck2 className="h-5 w-5" />} />
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {list.map((letter) => (
            <Card key={letter.report_id} className="p-5">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-[10px] font-bold uppercase tracking-[0.1em] text-ink-soft">{t("letters.insurer")}</p>
                  <h2 className="mt-1 text-[15px] font-bold text-navy">{letter.insurer || letter.title}</h2>
                  <p className="mt-0.5 font-mono text-[10px] text-ink-soft">{letter.policy_number}</p>
                </div>
                <StatusBadge status={letter.status || "pending"} />
              </div>
              <div className="mt-4 space-y-1.5 border-y border-line py-3 text-[11px]">
                <div className="flex justify-between gap-3">
                  <span className="text-ink-soft">{t("letters.reference")}</span>
                  <span className="font-mono text-[10px] text-navy">{letter.reference || "—"}</span>
                </div>
                <div className="flex justify-between gap-3">
                  <span className="text-ink-soft">{t("letters.letterStatus")}</span>
                  <span className="font-medium capitalize text-navy">{letter.status || "—"}</span>
                </div>
                <div className="flex justify-between gap-3">
                  <span className="text-ink-soft">Generated</span>
                  <span className="text-ink-muted">{shortDate(letter.created_at, lang)}</span>
                </div>
              </div>
              <Button
                className="mt-4 w-full"
                variant="secondary"
                icon={<Download className="h-4 w-4" />}
                onClick={async () => {
                  try {
                    await downloadFile(letter.download_url, `${letter.title}.pdf`);
                  } catch (error) {
                    notify(error instanceof Error ? error.message : "Could not download.", "error");
                  }
                }}
              >
                {t("letters.download")}
              </Button>
            </Card>
          ))}
        </div>
      )}

      <div className="mt-5 grid gap-3 md:grid-cols-2">
        <Alert tone="info" title="What every letter contains">
          {t("letters.checklist")}
        </Alert>
        <Alert tone="warning" title={t("results.disclaimer")}>
          {t("letters.disclaimer")} A pre-authorisation letter is a request, not an approval or a guarantee of payment.
        </Alert>
      </div>
    </div>
  );
}
