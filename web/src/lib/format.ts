export function inr(value: string | number | null | undefined, decimals = 0): string {
  const numeric = Number(value ?? 0);
  if (!Number.isFinite(numeric)) return "₹0";
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: decimals,
    minimumFractionDigits: decimals,
  }).format(numeric);
}

export function inr2(value: string | number | null | undefined): string {
  return inr(value, 2);
}

export function pct(value: string | number | null | undefined, digits = 0): string {
  const numeric = Number(value ?? 0);
  if (!Number.isFinite(numeric)) return "0%";
  return `${(numeric * 100).toFixed(digits)}%`;
}

export function fileSize(bytes: number): string {
  if (!bytes) return "0 KB";
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function shortDate(value: string | null | undefined, lang: "en" | "hi" = "en"): string {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleDateString(lang === "hi" ? "hi-IN" : "en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

export function dateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}

export function ago(value: string | null | undefined): string {
  if (!value) return "—";
  const seconds = Math.max(1, (Date.now() - new Date(value).getTime()) / 1000);
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

export function initials(name: string): string {
  return name
    .split(" ")
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join("");
}

export function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

export const STATUS_LABELS: Record<string, { en: string; hi: string; tone: string }> = {
  draft: { en: "Draft", hi: "ड्राफ़्ट", tone: "slate" },
  ready: { en: "Ready", hi: "तैयार", tone: "blue" },
  queued: { en: "Queued", hi: "कतार में", tone: "blue" },
  running: { en: "Running", hi: "चल रहा है", tone: "blue" },
  awaiting_review: { en: "Needs review", hi: "समीक्षा आवश्यक", tone: "amber" },
  complete: { en: "Complete", hi: "पूर्ण", tone: "teal" },
  failed: { en: "Needs attention", hi: "ध्यान आवश्यक", tone: "red" },
  active: { en: "Active", hi: "सक्रिय", tone: "teal" },
  inactive: { en: "Inactive", hi: "निष्क्रिय", tone: "red" },
  expired: { en: "Expired", hi: "समाप्त", tone: "amber" },
  uploaded: { en: "Uploaded", hi: "अपलोड हुआ", tone: "slate" },
  processed: { en: "Processed", hi: "प्रोसेस हुआ", tone: "blue" },
  needs_review: { en: "Needs review", hi: "समीक्षा आवश्यक", tone: "amber" },
  confirmed: { en: "Confirmed", hi: "पुष्ट", tone: "teal" },
  pending: { en: "Pending", hi: "लंबित", tone: "amber" },
  approved: { en: "Approved", hi: "स्वीकृत", tone: "teal" },
  rejected: { en: "Rejected", hi: "अस्वीकृत", tone: "red" },
  not_required: { en: "Not required", hi: "आवश्यक नहीं", tone: "slate" },
};
