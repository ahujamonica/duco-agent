import React, { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  ArrowRight,
  BadgeCheck,
  BrainCircuit,
  CheckCircle2,
  FileSearch,
  Fingerprint,
  FlaskConical,
  Languages,
  Layers,
  Lock,
  ReceiptIndianRupee,
  ShieldCheck,
  Sparkles,
  Wallet,
} from "lucide-react";
import { useAuth } from "../lib/auth";
import { useI18n } from "../lib/i18n";
import { Badge, Button, Card, cx, useToast } from "../components/ui";
import { inr } from "../lib/format";

function Logo() {
  return (
    <Link to="/" className="flex items-center gap-2.5">
      <span className="flex h-8 w-8 items-center justify-center rounded-[10px] bg-navy text-[13px] font-black tracking-tighter text-white">
        D<span className="text-teal">A</span>
      </span>
      <span className="text-[15px] font-bold tracking-[-0.02em] text-navy">
        DuCO <span className="text-teal">Agent</span>
      </span>
    </Link>
  );
}

function HeroPreview() {
  const { t } = useI18n();
  const steps = [
    { agent: "Document Intelligence", note: "3 documents read · 2 fields flagged", tone: "teal", icon: <FileSearch className="h-3.5 w-3.5" /> },
    { agent: "COB Agent", note: "HDFC ERGO primary · ICICI Lombard secondary", tone: "blue", icon: <Layers className="h-3.5 w-3.5" /> },
    { agent: "Financial Calculation", note: "All financial invariants passed", tone: "teal", icon: <CalculatorIcon /> },
  ];
  return (
    <div className="relative">
      <div className="absolute -inset-3 rounded-[28px] bg-white/55 blur-xl" aria-hidden="true" />
      <div className="relative overflow-hidden rounded-2xl border border-line bg-white shadow-lift">
        <div className="flex items-center justify-between border-b border-line px-5 py-3.5">
          <div>
            <p className="text-[10px] font-bold uppercase tracking-[0.14em] text-ink-soft">Illustrative preview</p>
            <p className="mt-0.5 text-[13px] font-semibold text-navy">{t("landing.previewTitle")}</p>
          </div>
          <Badge tone="amber">{t("common.simulated")}</Badge>
        </div>
        <div className="space-y-3 px-5 py-4">
          {steps.map((step) => (
            <div key={step.agent} className="flex items-start gap-3">
              <span
                className={cx(
                  "mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full",
                  step.tone === "teal" ? "bg-teal-50 text-teal-600" : "bg-brand-50 text-brand"
                )}
              >
                {step.icon}
              </span>
              <div className="min-w-0">
                <p className="text-[12px] font-semibold text-navy">{step.agent}</p>
                <p className="text-[11px] text-ink-muted">{step.note}</p>
              </div>
              <CheckCircle2 className="ml-auto h-4 w-4 shrink-0 text-teal" />
            </div>
          ))}
        </div>
        <div className="grid grid-cols-2 gap-px bg-line">
          <div className="bg-canvas px-5 py-3.5">
            <p className="text-[10px] font-semibold uppercase tracking-[0.09em] text-ink-soft">{t("landing.previewPaid")}</p>
            <p className="mt-0.5 text-[19px] font-bold tabular-nums text-navy">{inr(450820)}</p>
            <p className="text-[10px] text-ink-soft">90% of the bill</p>
          </div>
          <div className="bg-canvas px-5 py-3.5">
            <p className="text-[10px] font-semibold uppercase tracking-[0.09em] text-ink-soft">{t("landing.previewYou")}</p>
            <p className="mt-0.5 text-[19px] font-bold tabular-nums text-navy">{inr(29180)}</p>
            <p className="text-[10px] text-ink-soft">explained line by line</p>
          </div>
        </div>
        <div className="px-5 py-3">
          <div className="h-1.5 overflow-hidden rounded-full bg-slate-100">
            <div className="h-full w-[90%] rounded-full bg-teal" />
          </div>
          <p className="mt-1.5 text-[10px] text-ink-soft">Two claims · two policies · one household</p>
        </div>
      </div>
      <div className="absolute -top-4 right-5 hidden rounded-xl border border-line bg-white px-3 py-2 shadow-card sm:block">
        <p className="flex items-center gap-1.5 text-[10.5px] font-semibold text-navy">
          <ShieldCheck className="h-3.5 w-3.5 text-teal" /> Every rupee traceable
        </p>
      </div>
    </div>
  );
}

function CalculatorIcon() {
  return <ReceiptIndianRupee className="h-3.5 w-3.5" />;
}

export default function Landing() {
  const { t, lang, setLanguage } = useI18n();
  const { demoLogin, user } = useAuth();
  const navigate = useNavigate();
  const { notify } = useToast();
  const [loadingDemo, setLoadingDemo] = useState(false);

  const openDemo = async () => {
    if (user) {
      navigate("/app");
      return;
    }
    setLoadingDemo(true);
    try {
      const data = await demoLogin();
      notify("Demo household ready. Run the surgery scenario to see the full workflow.", "success");
      navigate(`/app/cases/${data.case_id}/run`);
    } catch (error) {
      notify(error instanceof Error ? error.message : "Could not open the demo.", "error");
    } finally {
      setLoadingDemo(false);
    }
  };

  const features = [
    { icon: <FileSearch className="h-5 w-5" />, title: t("landing.f1Title"), body: t("landing.f1Body") },
    { icon: <Layers className="h-5 w-5" />, title: t("landing.f2Title"), body: t("landing.f2Body") },
    { icon: <ReceiptIndianRupee className="h-5 w-5" />, title: t("landing.f3Title"), body: t("landing.f3Body") },
    { icon: <BrainCircuit className="h-5 w-5" />, title: t("landing.f4Title"), body: t("landing.f4Body") },
    { icon: <FileTextIcon />, title: t("landing.f5Title"), body: t("landing.f5Body") },
    { icon: <Languages className="h-5 w-5" />, title: t("landing.f6Title"), body: t("landing.f6Body") },
  ];

  return (
    <div className="min-h-screen bg-white">
      <header className="sticky top-0 z-30 border-b border-line/70 bg-white/90 backdrop-blur">
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-5">
          <Logo />
          <nav className="hidden items-center gap-7 text-[12.5px] font-medium text-ink-muted md:flex" aria-label="Landing">
            <a href="#product" className="hover:text-navy">{t("landing.nav.product")}</a>
            <a href="#how" className="hover:text-navy">{t("landing.nav.how")}</a>
            <a href="#security" className="hover:text-navy">{t("landing.nav.security")}</a>
          </nav>
          <div className="flex items-center gap-2">
            <div className="hidden items-center rounded-lg border border-line p-0.5 sm:flex" role="group" aria-label={t("common.language")}>
              {(["en", "hi"] as const).map((option) => (
                <button
                  key={option}
                  onClick={() => setLanguage(option)}
                  className={cx(
                    "rounded-md px-2 py-1 text-[10.5px] font-bold transition",
                    lang === option ? "bg-navy text-white" : "text-ink-soft hover:text-navy"
                  )}
                >
                  {option === "en" ? "EN" : "हिं"}
                </button>
              ))}
            </div>
            <Link to="/login" className="hidden px-2 text-[12.5px] font-semibold text-navy hover:text-brand sm:block">
              {t("common.signIn")}
            </Link>
            <Link to="/register">
              <Button size="sm">{t("common.getStarted")}</Button>
            </Link>
          </div>
        </div>
      </header>

      <section className="relative overflow-hidden border-b border-line bg-canvas">
        <div className="hero-grid absolute inset-0 opacity-70" aria-hidden="true" />
        <div className="relative mx-auto grid max-w-6xl gap-12 px-5 py-16 lg:grid-cols-[1.08fr_0.92fr] lg:items-center lg:py-24">
          <div>
            <Badge tone="blue" className="mb-5">
              <Sparkles className="mr-1 h-3 w-3" /> {t("landing.eyebrow")}
            </Badge>
            <h1 className="max-w-[620px] text-[38px] font-bold leading-[1.08] tracking-[-0.035em] text-navy sm:text-[50px]">
              {t("landing.headline")}
            </h1>
            <p className="mt-5 max-w-[520px] text-[15px] leading-7 text-ink-muted sm:text-[16.5px]">
              {t("landing.subheadline")}
            </p>
            <div className="mt-8 flex flex-wrap items-center gap-3">
              <Link to={user ? "/app" : "/register"}>
                <Button size="lg" icon={<ArrowRight className="h-4 w-4" />}>
                  {t("landing.ctaPrimary")}
                </Button>
              </Link>
              <Button size="lg" variant="secondary" loading={loadingDemo} onClick={openDemo} icon={<FlaskConical className="h-4 w-4" />}>
                {t("landing.ctaSecondary")}
              </Button>
            </div>
            <p className="mt-5 flex items-start gap-2 text-[11.5px] leading-4 text-ink-soft">
              <Lock className="mt-0.5 h-3.5 w-3.5 shrink-0" /> {t("landing.trust")}
            </p>
          </div>
          <HeroPreview />
        </div>
      </section>

      <section id="product" className="mx-auto max-w-6xl px-5 py-20">
        <div className="max-w-2xl">
          <p className="text-[11px] font-bold uppercase tracking-[0.16em] text-brand">{t("landing.featuresEyebrow")}</p>
          <h2 className="mt-2 text-[30px] font-bold tracking-[-0.025em] sm:text-[34px]">{t("landing.featuresTitle")}</h2>
          <p className="mt-2 text-[14px] leading-6 text-ink-muted">{t("landing.featuresSub")}</p>
        </div>
        <div className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {features.map((feature) => (
            <Card key={feature.title} className="group p-5 transition hover:-translate-y-0.5 hover:border-brand/30 hover:shadow-lift">
              <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-brand-50 text-brand">{feature.icon}</span>
              <h3 className="mt-3.5 text-[14.5px] font-bold tracking-[-0.01em]">{feature.title}</h3>
              <p className="mt-1.5 text-[12.5px] leading-5 text-ink-muted">{feature.body}</p>
            </Card>
          ))}
        </div>
      </section>

      <section id="how" className="border-y border-line bg-canvas">
        <div className="mx-auto max-w-6xl px-5 py-20">
          <p className="text-[11px] font-bold uppercase tracking-[0.16em] text-brand">{t("landing.howEyebrow")}</p>
          <h2 className="mt-2 max-w-2xl text-[30px] font-bold tracking-[-0.025em] sm:text-[34px]">{t("landing.howTitle")}</h2>
          <div className="mt-10 grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
            {[1, 2, 3, 4].map((step) => (
              <div key={step} className="relative">
                <div className="flex h-9 w-9 items-center justify-center rounded-full border border-brand/20 bg-white text-[12px] font-bold text-brand">
                  {String(step).padStart(2, "0")}
                </div>
                <h3 className="mt-4 text-[14px] font-bold">{t(`landing.how${step}`)}</h3>
                <p className="mt-1.5 text-[12.5px] leading-5 text-ink-muted">{t(`landing.how${step}Body`)}</p>
                {step < 4 && <ArrowRight className="absolute -right-3 top-1.5 hidden h-4 w-4 text-line lg:block" />}
              </div>
            ))}
          </div>
        </div>
      </section>

      <section id="security" className="mx-auto max-w-6xl px-5 py-20">
        <div className="grid gap-10 lg:grid-cols-[0.95fr_1.05fr] lg:items-center">
          <div>
            <p className="text-[11px] font-bold uppercase tracking-[0.16em] text-brand">{t("landing.securityEyebrow")}</p>
            <h2 className="mt-2 text-[30px] font-bold tracking-[-0.025em] sm:text-[34px]">{t("landing.securityTitle")}</h2>
            <p className="mt-3 text-[13.5px] leading-6 text-ink-muted">{t("landing.securityBody")}</p>
          </div>
          <Card className="p-6">
            <ul className="space-y-4">
              {[t("landing.securityPoint1"), t("landing.securityPoint2"), t("landing.securityPoint3")].map((point) => (
                <li key={point} className="flex items-start gap-3 text-[13px] leading-5 text-ink">
                  <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-teal-50 text-teal-600">
                    <CheckCircle2 className="h-3.5 w-3.5" />
                  </span>
                  {point}
                </li>
              ))}
            </ul>
            <div className="mt-5 flex items-center gap-2 rounded-lg bg-amber-50 px-3 py-2 text-[11.5px] leading-4 text-[#6B4A10]">
              <Fingerprint className="h-3.5 w-3.5 shrink-0" />
              Production gaps — encryption at rest, audit-on-read and DPDP erasure workflows — are documented, not hidden.
            </div>
          </Card>
        </div>
      </section>

      <section className="border-t border-line bg-navy">
        <div className="mx-auto flex max-w-6xl flex-col items-start justify-between gap-6 px-5 py-14 sm:flex-row sm:items-center">
          <div>
            <h2 className="text-[26px] font-bold tracking-[-0.02em] text-white">Bring clarity to the next medical bill.</h2>
            <p className="mt-1.5 text-[13px] text-white/60">Create a household in a minute. Add a policy, upload a bill, watch the agents work.</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Link to="/register">
              <Button variant="teal" size="lg" icon={<ArrowRight className="h-4 w-4" />}>
                {t("landing.ctaPrimary")}
              </Button>
            </Link>
            <Button size="lg" variant="secondary" className="border-white/20 bg-transparent text-white hover:bg-white/10 hover:text-white" loading={loadingDemo} onClick={openDemo}>
              {t("landing.ctaSecondary")}
            </Button>
          </div>
        </div>
      </section>

      <footer className="bg-navy pb-10 text-white/50">
        <div className="mx-auto grid max-w-6xl gap-8 border-t border-white/10 px-5 pt-10 sm:grid-cols-2 lg:grid-cols-4">
          <div>
            <Logo />
            <p className="mt-3 max-w-xs text-[11.5px] leading-4 text-white/45">{t("landing.footerNote")}</p>
          </div>
          <div>
            <p className="text-[11px] font-bold uppercase tracking-[0.12em] text-white/70">Product</p>
            <ul className="mt-3 space-y-2 text-[12px]">
              <li><a href="#product" className="hover:text-white">{t("landing.nav.product")}</a></li>
              <li><a href="#how" className="hover:text-white">{t("landing.nav.how")}</a></li>
              <li><Link to="/register" className="hover:text-white">Get started</Link></li>
            </ul>
          </div>
          <div>
            <p className="text-[11px] font-bold uppercase tracking-[0.12em] text-white/70">Trust</p>
            <ul className="mt-3 space-y-2 text-[12px]">
              <li><a href="#security" className="hover:text-white">Security</a></li>
              <li><span>Simulated insurer sandbox</span></li>
              <li><span>Not medical advice</span></li>
            </ul>
          </div>
          <div>
            <p className="text-[11px] font-bold uppercase tracking-[0.12em] text-white/70">Built for</p>
            <ul className="mt-3 space-y-2 text-[12px]">
              <li className="flex items-center gap-1.5"><Wallet className="h-3.5 w-3.5" /> Multi-policy households</li>
              <li className="flex items-center gap-1.5"><BadgeCheck className="h-3.5 w-3.5" /> Auditable decisions</li>
              <li className="flex items-center gap-1.5"><Languages className="h-3.5 w-3.5" /> English and Hindi</li>
            </ul>
          </div>
        </div>
        <div className="mx-auto mt-8 max-w-6xl px-5 text-[10.5px] text-white/35">
          © {new Date().getFullYear()} DuCO Agent · A coordination-of-benefits prototype · INR · All patient data in the demo is fictional.
        </div>
      </footer>
    </div>
  );
}

function FileTextIcon() {
  return <FileSearch className="h-5 w-5" />;
}
