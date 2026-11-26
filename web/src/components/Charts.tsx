import React from "react";
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip as ReTooltip } from "recharts";
import { inr } from "../lib/format";
import { cx } from "./ui";

export function DonutChart({
  data,
  total,
  label,
}: {
  data: { name: string; value: number; color: string }[];
  total: number;
  label: string;
}) {
  const filtered = data.filter((item) => Number(item.value) > 0);
  return (
    <div className="relative h-[220px] w-full">
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie
            data={filtered.length ? filtered : [{ name: "Empty", value: 1, color: "#E6EAF2" }]}
            dataKey="value"
            nameKey="name"
            innerRadius={66}
            outerRadius={92}
            paddingAngle={filtered.length > 1 ? 3 : 0}
            stroke="none"
          >
            {(filtered.length ? filtered : [{ color: "#E6EAF2" }]).map((entry, index) => (
              <Cell key={index} fill={entry.color} />
            ))}
          </Pie>
          {filtered.length > 0 && (
            <ReTooltip
              formatter={(value: any, name: any) => [inr(Number(value)), name]}
              contentStyle={{
                borderRadius: 10,
                border: "1px solid #E6EAF2",
                fontSize: 12,
                boxShadow: "0 12px 30px -18px rgba(20,36,58,.4)",
              }}
            />
          )}
        </PieChart>
      </ResponsiveContainer>
      <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-[10.5px] font-semibold uppercase tracking-[0.08em] text-ink-soft">{label}</span>
        <span className="mt-0.5 text-[20px] font-bold tabular-nums text-navy">{inr(total)}</span>
      </div>
    </div>
  );
}

export function Waterfall({
  items,
  base,
}: {
  items: { label: string; amount: number; color: string; muted?: boolean }[];
  base: number;
}) {
  const max = Math.max(base, ...items.map((item) => Math.abs(item.amount)), 1);
  return (
    <div className="space-y-2.5">
      {items.map((item, index) => {
        const width = Math.max(0, Math.min(100, (Math.abs(item.amount) / max) * 100));
        return (
          <div key={`${item.label}-${index}`} className="grid grid-cols-[130px_1fr_100px] items-center gap-2 sm:grid-cols-[170px_1fr_120px]">
            <span className={cx("truncate text-[11.5px]", item.muted ? "text-ink-soft" : "text-ink-muted")}>{item.label}</span>
            <div className="h-2.5 overflow-hidden rounded-full bg-slate-100">
              <div
                className="h-full rounded-full transition-all duration-500"
                style={{ width: `${width}%`, backgroundColor: item.color }}
              />
            </div>
            <span className={cx("text-right text-[11.5px] font-semibold tabular-nums", item.muted ? "text-ink-soft" : "text-navy")}>
              {inr(item.amount)}
            </span>
          </div>
        );
      })}
    </div>
  );
}

export function Legend({ items }: { items: { label: string; color: string; value?: string }[] }) {
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-2">
      {items.map((item) => (
        <div key={item.label} className="flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-full" style={{ backgroundColor: item.color }} />
          <span className="text-[11px] text-ink-muted">{item.label}</span>
          {item.value && <span className="text-[11px] font-semibold text-navy tabular-nums">{item.value}</span>}
        </div>
      ))}
    </div>
  );
}
