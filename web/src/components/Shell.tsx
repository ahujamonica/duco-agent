import React, { useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import {
  ChevronRight,
  FileText,
  FolderKanban,
  LayoutDashboard,
  LogOut,
  Menu,
  Plus,
  Settings,
  ShieldCheck,
  Users,
  X,
} from "lucide-react";
import { useAuth } from "../lib/auth";
import { useI18n } from "../lib/i18n";
import { initials } from "../lib/format";
import { Badge, Button, cx } from "./ui";

const NAV = [
  { to: "/app", key: "nav.dashboard", icon: LayoutDashboard, end: true },
  { to: "/app/family", key: "nav.family", icon: Users },
  { to: "/app/policies", key: "nav.policies", icon: ShieldCheck },
  { to: "/app/documents", key: "nav.documents", icon: FileText },
  { to: "/app/cases", key: "nav.cases", icon: FolderKanban },
  { to: "/app/settings", key: "nav.settings", icon: Settings },
];

function Logo({ compact = false }: { compact?: boolean }) {
  return (
    <div className="flex items-center gap-2.5">
      <span className="flex h-8 w-8 items-center justify-center rounded-[10px] bg-white text-[13px] font-black tracking-tighter text-navy">
        D<span className="text-teal">A</span>
      </span>
      {!compact && (
        <span className="text-[15px] font-bold tracking-[-0.02em] text-white">
          DuCO <span className="text-teal">Agent</span>
        </span>
      )}
    </div>
  );
}

function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const { t } = useI18n();
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  return (
    <div className="flex h-full flex-col">
      <div className="px-5 pb-5 pt-5">
        <button onClick={() => navigate("/app")} className="focus-ring rounded-lg text-left">
          <Logo />
        </button>
        <p className="mt-1 pl-[42px] text-[10.5px] font-medium text-white/45">{t("brand.tagline")}</p>
      </div>
      <div className="px-3">
        <Button
          size="sm"
          className="w-full justify-start bg-white/10 text-white hover:bg-white/15"
          icon={<Plus className="h-4 w-4" />}
          onClick={() => {
            navigate("/app/cases/new");
            onNavigate?.();
          }}
        >
          {t("nav.newCase")}
        </Button>
      </div>
      <nav className="mt-6 space-y-0.5 px-3" aria-label="Primary">
        <p className="px-2 pb-1.5 text-[10px] font-bold uppercase tracking-[0.14em] text-white/35">{t("nav.workspace")}</p>
        {NAV.slice(0, 5).map((item) => {
          const Icon = item.icon;
          return (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              onClick={onNavigate}
              className={({ isActive }) =>
                cx(
                  "group flex items-center gap-3 rounded-lg px-2.5 py-2 text-[13px] font-medium transition",
                  isActive ? "bg-white/12 text-white" : "text-white/60 hover:bg-white/6 hover:text-white"
                )
              }
            >
              {({ isActive }) => (
                <>
                  <Icon className={cx("h-4 w-4", isActive ? "text-teal" : "text-white/45 group-hover:text-white/80")} />
                  <span>{t(item.key)}</span>
                  {isActive && <span className="ml-auto h-1.5 w-1.5 rounded-full bg-teal" />}
                </>
              )}
            </NavLink>
          );
        })}
        <p className="px-2 pb-1.5 pt-5 text-[10px] font-bold uppercase tracking-[0.14em] text-white/35">{t("nav.account")}</p>
        <NavLink
          to="/app/settings"
          onClick={onNavigate}
          className={({ isActive }) =>
            cx(
              "group flex items-center gap-3 rounded-lg px-2.5 py-2 text-[13px] font-medium transition",
              isActive ? "bg-white/12 text-white" : "text-white/60 hover:bg-white/6 hover:text-white"
            )
          }
        >
          <Settings className="h-4 w-4 text-white/45 group-hover:text-white/80" />
          <span>{t("nav.settings")}</span>
        </NavLink>
      </nav>
      <div className="mt-auto px-3 pb-4">
        <div className="rounded-xl border border-white/10 bg-white/5 p-3">
          <div className="flex items-center gap-2.5">
            <span className="flex h-8 w-8 items-center justify-center rounded-full bg-teal/20 text-[11px] font-bold text-teal">
              {initials(user?.name || "Guest")}
            </span>
            <div className="min-w-0 flex-1">
              <p className="truncate text-[12px] font-semibold text-white">{user?.name}</p>
              <p className="truncate text-[10.5px] text-white/45">{user?.email}</p>
            </div>
          </div>
          <button
            onClick={() => {
              logout();
              navigate("/");
            }}
            className="focus-ring mt-2.5 flex w-full items-center gap-2 rounded-md px-1 py-1 text-[11.5px] text-white/50 hover:text-white"
          >
            <LogOut className="h-3.5 w-3.5" /> {t("common.signOut")}
          </button>
        </div>
      </div>
    </div>
  );
}

export function Shell() {
  const [open, setOpen] = useState(false);
  const { user } = useAuth();
  const { lang, setLanguage, t } = useI18n();
  const location = useLocation();
  const isDemo = user?.email === "demo@duco.health";

  return (
    <div className="min-h-screen bg-canvas">
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-[236px] bg-navy lg:block">
        <Sidebar />
      </aside>
      {open && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-navy/50" onClick={() => setOpen(false)} />
          <aside className="absolute inset-y-0 left-0 w-[260px] bg-navy shadow-lift">
            <button
              onClick={() => setOpen(false)}
              aria-label="Close menu"
              className="absolute right-3 top-3 rounded-lg p-1.5 text-white/70 hover:bg-white/10"
            >
              <X className="h-4.5 w-4.5" />
            </button>
            <Sidebar onNavigate={() => setOpen(false)} />
          </aside>
        </div>
      )}
      <div className="lg:pl-[236px]">
        <header className="sticky top-0 z-20 flex h-14 items-center justify-between gap-3 border-b border-line bg-white/85 px-4 backdrop-blur sm:px-6">
          <div className="flex min-w-0 items-center gap-2">
            <button
              onClick={() => setOpen(true)}
              className="focus-ring rounded-lg p-1.5 text-ink-muted hover:bg-navy/5 lg:hidden"
              aria-label="Open menu"
            >
              <Menu className="h-5 w-5" />
            </button>
            <div className="hidden items-center gap-1.5 text-[11.5px] text-ink-soft sm:flex">
              <span className="font-semibold text-navy">DuCO Agent</span>
              <ChevronRight className="h-3 w-3" />
              <span className="truncate">
                {(() => {
                  const parts = location.pathname.split("/").filter(Boolean).slice(1);
                  const label = (value: string) =>
                    /^\d+$/.test(value)
                      ? "Case"
                      : value.replace(/-/g, " ").replace(/^\w/, (letter) => letter.toUpperCase());
                  return parts.length ? parts.map(label).join(" / ") : "Dashboard";
                })()}
              </span>
            </div>
            {isDemo && (
              <Badge tone="amber" className="ml-1">
                {t("common.demo")}
              </Badge>
            )}
          </div>
          <div className="flex items-center gap-2">
            <div className="flex items-center rounded-lg border border-line bg-white p-0.5" role="group" aria-label={t("common.language")}>
              {(["en", "hi"] as const).map((option) => (
                <button
                  key={option}
                  onClick={() => setLanguage(option)}
                  className={cx(
                    "rounded-md px-2 py-1 text-[11px] font-bold transition",
                    lang === option ? "bg-navy text-white" : "text-ink-soft hover:text-navy"
                  )}
                  aria-pressed={lang === option}
                >
                  {option === "en" ? "EN" : "हिं"}
                </button>
              ))}
            </div>
            <div className="hidden h-7 w-px bg-line sm:block" />
            <div className="flex items-center gap-2">
              <span className="flex h-7 w-7 items-center justify-center rounded-full bg-navy text-[10px] font-bold text-white">
                {initials(user?.name || "Guest")}
              </span>
              <span className="hidden max-w-[140px] truncate text-[12px] font-medium text-navy sm:block">{user?.name}</span>
            </div>
          </div>
        </header>
        <main className="mx-auto w-full max-w-[1240px] px-4 py-6 sm:px-6 sm:py-8">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
