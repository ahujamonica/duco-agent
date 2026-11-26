import React, { useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { ArrowRight, CheckCircle2, FlaskConical, Lock, ShieldCheck } from "lucide-react";
import { useAuth } from "../lib/auth";
import { useI18n } from "../lib/i18n";
import { Alert, Button, Card, Field, Input, cx, useToast } from "../components/ui";

export default function AuthPage({ mode }: { mode: "login" | "register" }) {
  const { t, lang, setLanguage } = useI18n();
  const { user, login, register, demoLogin } = useAuth();
  const navigate = useNavigate();
  const { notify } = useToast();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [demoBusy, setDemoBusy] = useState(false);

  if (user) return <Navigate to="/app" replace />;

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      if (mode === "register") {
        if (name.trim().length < 2) throw new Error("Enter your name.");
        if (password.length < 8) throw new Error("Use a password of at least 8 characters.");
        await register(name.trim(), email.trim(), password);
        navigate("/app/family?welcome=1");
      } else {
        await login(email.trim(), password);
        navigate("/app");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not sign you in.");
    } finally {
      setBusy(false);
    }
  };

  const openDemo = async () => {
    setError(null);
    setDemoBusy(true);
    try {
      const data = await demoLogin();
      notify("Demo household ready. Start the surgery scenario to watch the agents.", "success");
      navigate(`/app/cases/${data.case_id}/run`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not open the demo.");
    } finally {
      setDemoBusy(false);
    }
  };

  return (
    <div className="min-h-screen bg-canvas lg:grid lg:grid-cols-[1.02fr_0.98fr]">
      <aside className="relative hidden overflow-hidden bg-navy px-12 py-10 text-white lg:flex lg:flex-col">
        <div className="hero-grid absolute inset-0 opacity-[0.12]" aria-hidden="true" />
        <Link to="/" className="relative flex items-center gap-2.5">
          <span className="flex h-9 w-9 items-center justify-center rounded-[11px] bg-white text-[14px] font-black tracking-tighter text-navy">
            D<span className="text-teal">A</span>
          </span>
          <span className="text-[16px] font-bold tracking-[-0.02em]">
            DuCO <span className="text-teal">Agent</span>
          </span>
        </Link>
        <div className="relative mt-auto max-w-lg pb-8">
          <p className="text-[11px] font-bold uppercase tracking-[0.18em] text-teal">Coordination of benefits</p>
          <h1 className="mt-3 text-[38px] font-bold leading-[1.12] tracking-[-0.03em]">{t("auth.leftTitle")}</h1>
          <p className="mt-4 text-[13.5px] leading-6 text-white/60">{t("auth.leftBody")}</p>
          <ul className="mt-8 space-y-3.5">
            {[t("auth.leftPoint1"), t("auth.leftPoint2"), t("auth.leftPoint3")].map((point) => (
              <li key={point} className="flex items-start gap-2.5 text-[12.5px] leading-5 text-white/75">
                <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-teal" />
                {point}
              </li>
            ))}
          </ul>
          <div className="mt-10 rounded-xl border border-white/10 bg-white/5 p-4">
            <div className="flex items-center justify-between text-[10px] font-semibold uppercase tracking-[0.1em] text-white/45">
              <span>Illustrative cost flow</span>
              <span className="flex items-center gap-1 text-amber"><ShieldCheck className="h-3 w-3" /> Simulated insurer data</span>
            </div>
            <div className="mt-3 space-y-2.5">
              {[
                { label: "Billed", width: "100%", color: "bg-white/30", amount: "₹4,80,000" },
                { label: "Insurers", width: "95%", color: "bg-teal", amount: "₹4,57,570" },
                { label: "You", width: "5%", color: "bg-amber", amount: "₹22,430" },
              ].map((row) => (
                <div key={row.label} className="grid grid-cols-[54px_1fr_64px] items-center gap-2 text-[10.5px]">
                  <span className="text-white/45">{row.label}</span>
                  <div className="h-1.5 rounded-full bg-white/10">
                    <div className={cx("h-full rounded-full", row.color)} style={{ width: row.width }} />
                  </div>
                  <span className="text-right font-semibold tabular-nums text-white/80">{row.amount}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
        <p className="relative text-[10.5px] text-white/30">Prototype · not medical advice · insurer responses are simulated.</p>
      </aside>

      <main className="flex min-h-screen flex-col px-5 py-6 sm:px-10">
        <div className="flex items-center justify-between">
          <Link to="/" className="flex items-center gap-2 lg:invisible">
            <span className="flex h-8 w-8 items-center justify-center rounded-[10px] bg-navy text-[12px] font-black text-white">
              D<span className="text-teal">A</span>
            </span>
            <span className="text-[14px] font-bold text-navy">DuCO Agent</span>
          </Link>
          <div className="flex items-center rounded-lg border border-line bg-white p-0.5" role="group" aria-label={t("common.language")}>
            {(["en", "hi"] as const).map((option) => (
              <button
                key={option}
                onClick={() => setLanguage(option)}
                className={cx(
                  "rounded-md px-2 py-1 text-[10.5px] font-bold",
                  lang === option ? "bg-navy text-white" : "text-ink-soft"
                )}
              >
                {option === "en" ? "EN" : "हिं"}
              </button>
            ))}
          </div>
        </div>

        <div className="mx-auto flex w-full max-w-[420px] flex-1 flex-col justify-center py-10">
          <h2 className="text-[27px] font-bold tracking-[-0.025em] text-navy">
            {mode === "login" ? t("auth.signInTitle") : t("auth.registerTitle")}
          </h2>
          <p className="mt-1.5 text-[13px] text-ink-muted">
            {mode === "login" ? t("auth.signInSub") : t("auth.registerSub")}
          </p>

          <form onSubmit={submit} className="mt-7 space-y-4">
            {mode === "register" && (
              <Field label={t("auth.name")} htmlFor="name">
                <Input id="name" value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" placeholder="Asha Rao" required />
              </Field>
            )}
            <Field label={t("auth.email")} htmlFor="email">
              <Input
                id="email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                autoComplete="email"
                placeholder="you@example.com"
                required
              />
            </Field>
            <Field
              label={t("auth.password")}
              hint={mode === "register" ? t("auth.passwordHint") : undefined}
              htmlFor="password"
            >
              <Input
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete={mode === "register" ? "new-password" : "current-password"}
                placeholder="••••••••"
                required
              />
            </Field>
            {error && <Alert tone="danger">{error}</Alert>}
            <Button type="submit" className="w-full" size="lg" loading={busy} icon={<ArrowRight className="h-4 w-4" />}>
              {mode === "login" ? t("common.signIn") : t("auth.createAccount")}
            </Button>
          </form>

          <p className="mt-4 text-center text-[12px] text-ink-muted">
            {mode === "login" ? t("auth.noAccount") : t("auth.haveAccount")}{" "}
            <Link to={mode === "login" ? "/register" : "/login"} className="font-semibold text-brand hover:text-brand-600">
              {mode === "login" ? t("auth.createAccount") : t("common.signIn")}
            </Link>
          </p>

          <div className="my-7 flex items-center gap-3">
            <span className="h-px flex-1 bg-line" />
            <span className="text-[10px] font-semibold uppercase tracking-[0.12em] text-ink-soft">or</span>
            <span className="h-px flex-1 bg-line" />
          </div>

          <Card className="border-dashed p-4">
            <div className="flex items-start gap-3">
              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-amber-50 text-amber">
                <FlaskConical className="h-4 w-4" />
              </span>
              <div className="min-w-0">
                <p className="text-[13px] font-bold text-navy">{t("auth.demoTitle")}</p>
                <p className="mt-0.5 text-[11.5px] leading-4 text-ink-muted">{t("auth.demoSub")}</p>
                <Button size="sm" variant="secondary" className="mt-2.5" loading={demoBusy} onClick={openDemo}>
                  {t("auth.demoButton")}
                </Button>
                <p className="mt-2 flex items-start gap-1 text-[10px] leading-3.5 text-ink-soft">
                  <Lock className="mt-0.5 h-3 w-3 shrink-0" /> {t("auth.demoNote")}
                </p>
              </div>
            </div>
          </Card>
        </div>
      </main>
    </div>
  );
}
