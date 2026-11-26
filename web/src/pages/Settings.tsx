import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { AlertTriangle, CheckCircle2, Download, Globe2, ShieldCheck, Trash2 } from "lucide-react";
import { useApi } from "../lib/useApi";
import { useI18n } from "../lib/i18n";
import { useAuth } from "../lib/auth";
import { api, downloadFile } from "../lib/api";
import {
  Alert,
  Badge,
  Button,
  Card,
  Field,
  Input,
  LoadingBlock,
  Modal,
  PageHeader,
  Select,
  cx,
  useToast,
} from "../components/ui";
import { shortDate } from "../lib/format";

export default function Settings() {
  const { t, lang, setLanguage } = useI18n();
  const { user, refreshUser, logout } = useAuth();
  const { notify } = useToast();
  const navigate = useNavigate();
  const profile = useApi<any>("/api/settings/profile");
  const meta = useApi<any>("/api/meta");
  const notes = useApi<{ implemented: string[]; not_implemented: string[]; note: string }>("/api/settings/security-notes");
  const [name, setName] = useState("");
  const [locale, setLocale] = useState("en");
  const [saving, setSaving] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [confirmText, setConfirmText] = useState("");
  const isDemo = user?.email === "demo@duco.health";

  useEffect(() => {
    if (profile.data) {
      setName(profile.data.user.name);
      setLocale(profile.data.user.locale);
    }
  }, [profile.data?.user?.id]);

  if (profile.loading && !profile.data) return <LoadingBlock />;

  const save = async () => {
    setSaving(true);
    try {
      await api.patch("/api/settings/profile", { name, locale });
      await refreshUser();
      notify("Profile saved.", "success");
    } catch (error) {
      notify(error instanceof Error ? error.message : "Could not save.", "error");
    } finally {
      setSaving(false);
    }
  };

  const changeLanguage = async (next: "en" | "hi") => {
    setLanguage(next);
    setLocale(next);
    try {
      await api.patch("/api/settings/profile", { locale: next });
    } catch {
      /* the local switch still applies */
    }
  };

  const removeAccount = async () => {
    try {
      await api.del("/api/settings/account?confirm=true");
      logout();
      navigate("/");
    } catch (error) {
      notify(error instanceof Error ? error.message : "Could not delete the account.", "error");
    }
  };

  return (
    <div>
      <PageHeader title={t("settings.title")} subtitle={t("settings.subtitle")} />

      <div className="grid gap-4 lg:grid-cols-[1.15fr_0.85fr]">
        <div className="space-y-4">
          <Card className="p-5">
            <h2 className="text-[15px] font-bold">{t("settings.profile")}</h2>
            <div className="mt-4 grid gap-4 sm:grid-cols-2">
              <Field label={t("settings.name")}>
                <Input value={name} onChange={(event) => setName(event.target.value)} />
              </Field>
              <Field label={t("settings.email")}>
                <Input value={user?.email || ""} disabled />
              </Field>
              <Field label={t("settings.language")} hint={t("settings.languageHelp")}>
                <Select value={locale} onChange={(event) => changeLanguage(event.target.value as "en" | "hi")}>
                  <option value="en">English</option>
                  <option value="hi">हिंदी</option>
                </Select>
              </Field>
              <div className="flex items-end">
                <Button loading={saving} onClick={save}>{t("common.save")}</Button>
              </div>
            </div>
            <div className="mt-3 flex flex-wrap gap-3 border-t border-line pt-3 text-[10.5px] text-ink-soft">
              <span>{profile.data?.counts.families || 0} households</span>
              <span>{profile.data?.counts.cases || 0} cases</span>
              <span>{profile.data?.counts.documents || 0} documents</span>
              <span>Joined {shortDate(profile.data?.user?.created_at, lang)}</span>
            </div>
          </Card>

          <Card className="p-5">
            <h2 className="text-[15px] font-bold">{t("settings.security")}</h2>
            <div className="mt-3 grid gap-4 sm:grid-cols-2">
              <div>
                <p className="flex items-center gap-1.5 text-[10.5px] font-bold uppercase tracking-[0.08em] text-teal">
                  <CheckCircle2 className="h-3.5 w-3.5" /> {t("settings.implemented")}
                </p>
                <ul className="mt-2 space-y-1.5">
                  {(notes.data?.implemented || []).map((item) => (
                    <li key={item} className="flex items-start gap-1.5 text-[10.5px] leading-4 text-ink-muted">
                      <CheckCircle2 className="mt-0.5 h-3 w-3 shrink-0 text-teal" /> {item}
                    </li>
                  ))}
                </ul>
              </div>
              <div>
                <p className="flex items-center gap-1.5 text-[10.5px] font-bold uppercase tracking-[0.08em] text-amber">
                  <AlertTriangle className="h-3.5 w-3.5" /> {t("settings.gaps")}
                </p>
                <ul className="mt-2 space-y-1.5">
                  {(notes.data?.not_implemented || []).map((item) => (
                    <li key={item} className="flex items-start gap-1.5 text-[10.5px] leading-4 text-ink-muted">
                      <span className="mt-1 h-1 w-1 shrink-0 rounded-full bg-amber" /> {item}
                    </li>
                  ))}
                </ul>
              </div>
            </div>
            <p className="mt-3 rounded-lg bg-amber-50 px-2.5 py-1.5 text-[10px] leading-4 text-[#6B4A10]">{notes.data?.note}</p>
          </Card>
        </div>

        <div className="space-y-4">
          <Card className="p-5">
            <h2 className="text-[15px] font-bold">{t("settings.export")}</h2>
            <p className="mt-1 text-[11px] leading-4 text-ink-muted">{t("settings.exportHelp")}</p>
            <Button
              variant="secondary"
              className="mt-3 w-full"
              icon={<Download className="h-4 w-4" />}
              onClick={async () => {
                try {
                  await downloadFile("/api/settings/export", "duco-agent-export.json");
                  notify("Export downloaded.", "success");
                } catch (error) {
                  notify(error instanceof Error ? error.message : "Export failed.", "error");
                }
              }}
            >
              {t("settings.export")}
            </Button>
          </Card>

          <Card className="p-5">
            <h2 className="text-[15px] font-bold">{t("settings.appInfo")}</h2>
            <dl className="mt-3 space-y-2 text-[11px]">
              <div className="flex justify-between gap-3"><dt className="text-ink-soft">{t("settings.version")}</dt><dd className="font-medium text-navy">{meta.data?.version || "—"}</dd></div>
              <div className="flex justify-between gap-3"><dt className="text-ink-soft">{t("settings.environment")}</dt><dd className="font-medium text-navy">{meta.data?.environment || "—"}</dd></div>
              <div className="flex justify-between gap-3"><dt className="text-ink-soft">{t("settings.database")}</dt><dd className="text-right font-medium text-navy">{meta.data?.database || "—"}</dd></div>
              <div className="flex justify-between gap-3"><dt className="text-ink-soft">{t("settings.mock")}</dt><dd className="font-medium text-amber">{t("settings.mockValue")}</dd></div>
              <div className="flex justify-between gap-3"><dt className="text-ink-soft">TTS</dt><dd className="font-medium text-navy">{meta.data?.tts ? "available" : "unavailable"}</dd></div>
              <div className="flex justify-between gap-3"><dt className="text-ink-soft">LLM enrichment</dt><dd className="font-medium text-navy">{meta.data?.llm_enrichment ? "enabled" : "not configured (local fallback)"}</dd></div>
            </dl>
            <div className="mt-3 flex flex-wrap gap-1.5">
              {(meta.data?.disclaimers || []).slice(0, 2).map((item: string) => (
                <Badge key={item} tone="slate">prototype</Badge>
              ))}
            </div>
          </Card>

          {isDemo && (
            <Card className="p-5">
              <h2 className="text-[15px] font-bold">{t("settings.resetDemo")}</h2>
              <p className="mt-1 text-[11px] leading-4 text-ink-muted">{t("settings.resetDemoHelp")}</p>
              <Button
                variant="secondary"
                className="mt-3 w-full"
                onClick={async () => {
                  try {
                    await api.post("/api/demo/reset", {});
                    logout();
                    navigate("/");
                  } catch (error) {
                    notify(error instanceof Error ? error.message : "Could not reset.", "error");
                  }
                }}
              >
                {t("settings.resetDemo")}
              </Button>
            </Card>
          )}

          <Card className="border-danger/20 p-5">
            <h2 className="text-[15px] font-bold text-danger">{t("settings.delete")}</h2>
            <p className="mt-1 text-[11px] leading-4 text-ink-muted">{t("settings.deleteHelp")}</p>
            <Button variant="danger" className="mt-3 w-full" onClick={() => setDeleteOpen(true)} icon={<Trash2 className="h-4 w-4" />}>
              {t("settings.delete")}
            </Button>
          </Card>
        </div>
      </div>

      <Modal
        open={deleteOpen}
        onClose={() => { setDeleteOpen(false); setConfirmText(""); }}
        title={t("settings.delete")}
        width="max-w-md"
        footer={
          <>
            <Button variant="ghost" onClick={() => { setDeleteOpen(false); setConfirmText(""); }}>{t("common.cancel")}</Button>
            <Button variant="danger" disabled={confirmText !== "DELETE"} onClick={removeAccount}>{t("common.delete")}</Button>
          </>
        }
      >
        <Alert tone="danger" title={t("results.disclaimer")}>{t("settings.deleteWarning")}</Alert>
        <Field label='Type DELETE to confirm' className="mt-4">
          <Input value={confirmText} onChange={(event) => setConfirmText(event.target.value)} placeholder="DELETE" />
        </Field>
      </Modal>
    </div>
  );
}
