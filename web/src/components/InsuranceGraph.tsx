import React, { useEffect, useRef, useState } from "react";
import { ArrowRight, Building2, ShieldCheck, Users } from "lucide-react";
import { Family } from "../lib/types";
import { initials } from "../lib/format";
import { Badge, cx } from "./ui";
import { useI18n } from "../lib/i18n";

interface Edge {
  d: string;
  color: string;
  dashed?: boolean;
}

export function InsuranceGraph({ family }: { family: Family | null }) {
  const { t } = useI18n();
  const containerRef = useRef<HTMLDivElement>(null);
  const nodeRefs = useRef<Record<string, HTMLDivElement | null>>({});
  const [size, setSize] = useState({ width: 0, height: 0 });
  const [edges, setEdges] = useState<Edge[]>([]);

  const insurers = Array.from(new Set(family?.policies.map((policy) => policy.insurer_name) || []));

  useEffect(() => {
    if (!family) return;
    const compute = () => {
      const container = containerRef.current;
      if (!container) return;
      const rect = container.getBoundingClientRect();
      const nextEdges: Edge[] = [];
      const centre = (key: string, side: "left" | "right") => {
        const node = nodeRefs.current[key];
        if (!node) return null;
        const box = node.getBoundingClientRect();
        return {
          x: (side === "right" ? box.right : box.left) - rect.left,
          y: box.top - rect.top + box.height / 2,
        };
      };
      const slug = (value: string) => value.toLowerCase().replace(/[^a-z0-9]+/g, "-");
      for (const policy of family.policies) {
        const from = centre(`p-${policy.id}`, "left");
        const to = centre(`i-${slug(policy.insurer_name)}`, "right");
        if (from && to) {
          const mid = (from.x + to.x) / 2;
          nextEdges.push({
            d: `M ${from.x} ${from.y} C ${mid} ${from.y}, ${mid} ${to.y}, ${to.x} ${to.y}`,
            color: policy.status === "active" ? "#3867D6" : "#C53030",
            dashed: policy.status !== "active",
          });
        }
        for (const link of policy.members) {
          const memberFrom = centre(`m-${link.member_id}`, "right");
          const policyTo = centre(`p-${policy.id}`, "left");
          if (memberFrom && policyTo) {
            const mid = (memberFrom.x + policyTo.x) / 2;
            nextEdges.push({
              d: `M ${memberFrom.x} ${memberFrom.y} C ${mid} ${memberFrom.y}, ${mid} ${policyTo.y}, ${policyTo.x} ${policyTo.y}`,
              color: policy.status === "active" ? "#16A39A" : "#C53030",
              dashed: policy.status !== "active",
            });
          }
        }
      }
      setSize({ width: rect.width, height: rect.height });
      setEdges(nextEdges);
    };
    const raf = requestAnimationFrame(() => requestAnimationFrame(compute));
    const observer = new ResizeObserver(compute);
    if (containerRef.current) observer.observe(containerRef.current);
    window.addEventListener("resize", compute);
    return () => {
      cancelAnimationFrame(raf);
      observer.disconnect();
      window.removeEventListener("resize", compute);
    };
  }, [family]);

  if (!family) {
    return <p className="py-8 text-center text-[12.5px] text-ink-soft">Create a household to see its coverage graph.</p>;
  }

  return (
    <div>
      <div ref={containerRef} className="relative hidden gap-6 lg:grid lg:grid-cols-[1fr_1.1fr_0.8fr]">
        <svg
          className="pointer-events-none absolute inset-0"
          width={size.width}
          height={size.height}
          viewBox={`0 0 ${size.width} ${size.height}`}
          aria-hidden="true"
        >
          {edges.map((edge, index) => (
            <path
              key={index}
              d={edge.d}
              fill="none"
              stroke={edge.color}
              strokeWidth={1.4}
              strokeOpacity={0.55}
              strokeDasharray={edge.dashed ? "4 4" : undefined}
            />
          ))}
        </svg>

        <div className="relative space-y-3">
          <p className="flex items-center gap-1.5 text-[10.5px] font-bold uppercase tracking-[0.12em] text-ink-soft">
            <Users className="h-3.5 w-3.5" /> {t("family.membersCount")}
          </p>
          {family.members.map((member) => (
            <div
              key={member.id}
              ref={(node) => {
                nodeRefs.current[`m-${member.id}`] = node;
              }}
              className="relative z-10 rounded-xl border border-line bg-white p-3 shadow-sm"
            >
              <div className="flex items-center gap-2.5">
                <span className="flex h-8 w-8 items-center justify-center rounded-full bg-teal-50 text-[10.5px] font-bold text-teal-600">
                  {initials(member.name)}
                </span>
                <div className="min-w-0">
                  <p className="truncate text-[12.5px] font-semibold text-navy">{member.name}</p>
                  <p className="text-[10.5px] capitalize text-ink-soft">
                    {member.relation}
                    {member.age ? ` · ${member.age}` : ""}
                  </p>
                </div>
              </div>
            </div>
          ))}
        </div>

        <div className="relative space-y-3">
          <p className="flex items-center gap-1.5 text-[10.5px] font-bold uppercase tracking-[0.12em] text-ink-soft">
            <ShieldCheck className="h-3.5 w-3.5" /> {t("family.policies")}
          </p>
          {family.policies.length === 0 && (
            <div className="rounded-xl border border-dashed border-line p-4 text-[12px] text-ink-soft">{t("family.noPolicies")}</div>
          )}
          {family.policies.map((policy) => (
            <div
              key={policy.id}
              ref={(node) => {
                nodeRefs.current[`p-${policy.id}`] = node;
              }}
              className="relative z-10 rounded-xl border border-line bg-white p-3 shadow-sm"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="truncate text-[12.5px] font-semibold text-navy">{policy.insurer_name}</p>
                  <p className="truncate text-[10.5px] text-ink-soft">{policy.plan_name}</p>
                </div>
                <Badge tone={policy.status === "active" ? "teal" : "red"}>{policy.status}</Badge>
              </div>
              <div className="mt-2 flex flex-wrap gap-1">
                {policy.members.map((member) => (
                  <span
                    key={member.member_id}
                    className={cx(
                      "rounded-full px-1.5 py-0.5 text-[9.5px] font-semibold",
                      member.role === "policyholder" ? "bg-brand-50 text-brand" : "bg-slate-100 text-slate-600"
                    )}
                  >
                    {member.name?.split(" ")[0]} · {member.role}
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>

        <div className="relative space-y-3">
          <p className="flex items-center gap-1.5 text-[10.5px] font-bold uppercase tracking-[0.12em] text-ink-soft">
            <Building2 className="h-3.5 w-3.5" /> Insurers
          </p>
          {insurers.map((insurer) => (
            <div
              key={insurer}
              ref={(node) => {
                nodeRefs.current[`i-${insurer.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`] = node;
              }}
              className="relative z-10 rounded-xl border border-line bg-white p-3 shadow-sm"
            >
              <p className="truncate text-[12.5px] font-semibold text-navy">{insurer}</p>
              <p className="text-[10.5px] text-ink-soft">
                {family.policies.filter((policy) => policy.insurer_name === insurer).length} policy lines
              </p>
            </div>
          ))}
        </div>
      </div>

      <div className="space-y-4 lg:hidden">
        {family.members.map((member) => (
          <div key={member.id} className="rounded-xl border border-line bg-white p-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="flex h-7 w-7 items-center justify-center rounded-full bg-teal-50 text-[10px] font-bold text-teal-600">
                  {initials(member.name)}
                </span>
                <span className="text-[12.5px] font-semibold text-navy">{member.name}</span>
              </div>
              <span className="text-[10.5px] text-ink-soft">{member.policies.length} policies</span>
            </div>
            <div className="mt-2 space-y-1">
              {member.policies.map((link) => (
                <div key={link.policy_id} className="flex items-center justify-between rounded-lg bg-canvas px-2 py-1.5">
                  <span className="text-[11px] text-ink-muted">
                    {link.insurer} · {link.plan_name}
                  </span>
                  <span className="text-[10px] font-semibold text-brand">{link.role}</span>
                </div>
              ))}
              {member.policies.length === 0 && <p className="text-[11px] text-ink-soft">Not covered yet.</p>}
            </div>
          </div>
        ))}
      </div>

      <div className="mt-5 border-t border-line pt-4">
        <div className="flex items-center justify-between">
          <p className="text-[10.5px] font-bold uppercase tracking-[0.12em] text-ink-soft">Claim flow</p>
          <p className="text-[10px] text-ink-soft">patient → case → claim / procedures → adjudications</p>
        </div>
        <div className="mt-2.5 grid gap-2 lg:grid-cols-2">
          {[...(family.cases || [])]
            .sort((a, b) => (a.status === "complete" ? 0 : 1) - (b.status === "complete" ? 0 : 1))
            .slice(0, 6)
            .map((item) => {
            const patient = family.members.find((member) => member.id === item.patient_member_id);
            return (
              <div key={item.id} className="rounded-xl border border-line bg-white p-3">
                <div className="flex items-start justify-between gap-2">
                  <p className="truncate text-[11.5px] font-semibold text-navy">{item.title}</p>
                  <span className={`shrink-0 rounded-full px-1.5 py-0.5 text-[8.5px] font-bold uppercase ${item.status === "complete" ? "bg-teal-50 text-teal-600" : item.status === "awaiting_review" ? "bg-amber-50 text-amber" : "bg-brand-50 text-brand"}`}>
                    {item.status.replace("_", " ")}
                  </span>
                </div>
                <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[9.5px]">
                  <span className="rounded-full bg-navy-100 px-2 py-0.5 font-medium text-navy">{patient?.name || "Patient"}</span>
                  <ArrowRight className="h-3 w-3 text-ink-soft" />
                  <span className="rounded-full bg-canvas px-2 py-0.5 text-ink-muted">{item.claim_count || 0} claims</span>
                  <ArrowRight className="h-3 w-3 text-ink-soft" />
                  <span className="rounded-full bg-brand-50 px-2 py-0.5 text-brand">{item.procedure_count || 0} procedures</span>
                  <ArrowRight className="h-3 w-3 text-ink-soft" />
                  <span className="rounded-full bg-teal-50 px-2 py-0.5 text-teal-600">{item.adjudication_count || 0} adjudications</span>
                </div>
              </div>
            );
          })}
          {(family.cases || []).length === 0 && (
            <p className="text-[11px] text-ink-soft">No cases yet. A case carries the patient, the claims, the procedures and the adjudications.</p>
          )}
        </div>
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-1.5 border-t border-line pt-3 text-[10.5px] text-ink-soft">
        <span className="flex items-center gap-1.5">
          <span className="h-1.5 w-5 rounded-full bg-teal" /> member → policy
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-1.5 w-5 rounded-full bg-brand" /> policy → insurer
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-1.5 w-5 rounded-full bg-danger opacity-60" /> inactive policy
        </span>
        <span className="ml-auto flex items-center gap-1">
          <ArrowRight className="h-3 w-3" /> {family.counts.policies} policies · {family.counts.members} members
        </span>
      </div>
    </div>
  );
}
