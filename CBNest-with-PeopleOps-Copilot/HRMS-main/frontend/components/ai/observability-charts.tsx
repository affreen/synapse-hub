"use client";

import { useState } from "react";
import { CheckCircle2, Clock, HelpCircle, MinusCircle, ShieldAlert, XCircle } from "lucide-react";

// Sequential magnitude hue used across every single-series bar/line here —
// matches the app's existing --primary token (hsl(221.2 83.2% 53.3%) ~= #2563eb).
const SERIES_BLUE = "#2563eb";
const SERIES_BLUE_WASH = "rgba(37, 99, 235, 0.10)";

// Fixed status palette (never themed) — distinct from the categorical hue
// above so a status color never impersonates a series. Never used without
// an icon + label alongside it.
const STATUS_STYLE: Record<string, { color: string; icon: typeof CheckCircle2; label: string }> = {
  SUCCESS: { color: "#0ca30c", icon: CheckCircle2, label: "Success" },
  ERROR: { color: "#d03b3b", icon: XCircle, label: "Error" },
  REFUSED: { color: "#ec835a", icon: ShieldAlert, label: "Refused" },
  AWAITING_CONFIRMATION: { color: "#fab219", icon: Clock, label: "Awaiting confirmation" },
  CANCELLED: { color: "#64748b", icon: MinusCircle, label: "Cancelled" },
  NOT_APPLICABLE: { color: "#64748b", icon: MinusCircle, label: "Not applicable" },
  NO_ANSWER: { color: "#64748b", icon: HelpCircle, label: "No answer" },
};

function statusStyleFor(status: string) {
  return STATUS_STYLE[status] ?? { color: "#64748b", icon: HelpCircle, label: status };
}

function formatCompact(value: number): string {
  return new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(value);
}

export function StatTile({ label, value, sublabel }: { label: string; value: string; sublabel?: string }) {
  return (
    <div className="rounded-xl border border-border bg-card p-4 shadow-sm">
      <div className="text-xs font-medium text-muted-foreground">{label}</div>
      <div className="mt-1 text-2xl font-semibold text-foreground">{value}</div>
      {sublabel && <div className="mt-0.5 text-xs text-muted-foreground">{sublabel}</div>}
    </div>
  );
}

type BarListItem = {
  key: string;
  label: string;
  value: number;
  color?: string;
  icon?: typeof CheckCircle2;
};

export function BarList({
  title,
  items,
  valueFormatter = formatCompact,
  emptyLabel = "No data in this range yet.",
}: {
  title: string;
  items: BarListItem[];
  valueFormatter?: (value: number) => string;
  emptyLabel?: string;
}) {
  const [hovered, setHovered] = useState<string | null>(null);
  const max = Math.max(1, ...items.map((item) => item.value));

  return (
    <div className="rounded-xl border border-border bg-card p-4 shadow-sm">
      <h3 className="text-sm font-semibold text-foreground">{title}</h3>
      {items.length === 0 ? (
        <p className="mt-3 text-xs text-muted-foreground">{emptyLabel}</p>
      ) : (
        <div className="mt-3 space-y-2.5">
          {items.map((item) => {
            const widthPct = Math.max(2, (item.value / max) * 100);
            const color = item.color ?? SERIES_BLUE;
            const Icon = item.icon;
            const isHovered = hovered === item.key;
            return (
              <div
                key={item.key}
                className="group relative flex items-center gap-3"
                onMouseEnter={() => setHovered(item.key)}
                onMouseLeave={() => setHovered((current) => (current === item.key ? null : current))}
                onFocus={() => setHovered(item.key)}
                onBlur={() => setHovered((current) => (current === item.key ? null : current))}
                tabIndex={0}
              >
                <div className="flex w-40 shrink-0 items-center gap-1.5 truncate text-xs text-foreground">
                  {Icon && <Icon className="h-3.5 w-3.5 shrink-0" style={{ color }} />}
                  <span className="truncate">{item.label}</span>
                </div>
                <div
                  className="h-5 flex-1 rounded-full bg-muted transition-all"
                  style={{ outline: isHovered ? `1px solid ${color}` : "none", outlineOffset: 1 }}
                >
                  <div
                    className="h-5 rounded-full transition-all"
                    style={{
                      width: `${widthPct}%`,
                      backgroundColor: color,
                      opacity: isHovered ? 1 : 0.85,
                    }}
                  />
                </div>
                <div className="w-14 shrink-0 text-right text-xs font-medium tabular-nums text-foreground">
                  {valueFormatter(item.value)}
                </div>
                {isHovered && (
                  <div className="absolute -top-8 left-40 z-10 rounded-md border border-border bg-foreground px-2 py-1 text-xs text-background shadow-md">
                    <span className="font-semibold">{valueFormatter(item.value)}</span>{" "}
                    <span className="opacity-80">{item.label}</span>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export function StatusBarList({ items }: { items: { status: string; count: number }[] }) {
  return (
    <BarList
      title="Requests by outcome"
      items={items.map((item) => {
        const style = statusStyleFor(item.status);
        return { key: item.status, label: style.label, value: item.count, color: style.color, icon: style.icon };
      })}
    />
  );
}

export function DailyVolumeChart({ data }: { data: { date: string; count: number }[] }) {
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const width = 600;
  const height = 160;
  const padTop = 12;
  const padBottom = 24;
  const padLeft = 8;
  const padRight = 8;
  const plotWidth = width - padLeft - padRight;
  const plotHeight = height - padTop - padBottom;

  if (data.length === 0) {
    return (
      <div className="rounded-xl border border-border bg-card p-4 shadow-sm">
        <h3 className="text-sm font-semibold text-foreground">Daily request volume</h3>
        <p className="mt-3 text-xs text-muted-foreground">No data in this range yet.</p>
      </div>
    );
  }

  const maxCount = Math.max(1, ...data.map((d) => d.count));
  const stepX = data.length > 1 ? plotWidth / (data.length - 1) : 0;
  const points = data.map((d, i) => ({
    x: padLeft + stepX * i,
    y: padTop + plotHeight - (d.count / maxCount) * plotHeight,
    ...d,
  }));

  const linePath = points.map((p, i) => `${i === 0 ? "M" : "L"}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ");
  const areaPath =
    `M${points[0].x.toFixed(1)},${(padTop + plotHeight).toFixed(1)} ` +
    points.map((p) => `L${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ") +
    ` L${points[points.length - 1].x.toFixed(1)},${(padTop + plotHeight).toFixed(1)} Z`;

  const handleMove = (event: React.MouseEvent<SVGSVGElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const relativeX = ((event.clientX - rect.left) / rect.width) * width;
    let nearest = 0;
    let nearestDist = Infinity;
    points.forEach((p, i) => {
      const dist = Math.abs(p.x - relativeX);
      if (dist < nearestDist) {
        nearestDist = dist;
        nearest = i;
      }
    });
    setHoverIndex(nearest);
  };

  const hovered = hoverIndex !== null ? points[hoverIndex] : null;

  return (
    <div className="rounded-xl border border-border bg-card p-4 shadow-sm">
      <h3 className="text-sm font-semibold text-foreground">Daily request volume</h3>
      <div className="relative mt-3">
        <svg
          viewBox={`0 0 ${width} ${height}`}
          className="w-full"
          style={{ height: 160 }}
          onMouseMove={handleMove}
          onMouseLeave={() => setHoverIndex(null)}
        >
          {[0, 0.5, 1].map((t) => (
            <line
              key={t}
              x1={padLeft}
              x2={width - padRight}
              y1={padTop + plotHeight * t}
              y2={padTop + plotHeight * t}
              stroke="#e1e0d9"
              strokeWidth={1}
            />
          ))}
          <path d={areaPath} fill={SERIES_BLUE_WASH} stroke="none" />
          <path d={linePath} fill="none" stroke={SERIES_BLUE} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
          {hovered && (
            <line
              x1={hovered.x}
              x2={hovered.x}
              y1={padTop}
              y2={padTop + plotHeight}
              stroke="#c3c2b7"
              strokeWidth={1}
            />
          )}
          {points.map((p, i) => (
            <circle
              key={p.date}
              cx={p.x}
              cy={p.y}
              r={hoverIndex === i ? 5 : 0}
              fill={SERIES_BLUE}
              stroke="#fcfcfb"
              strokeWidth={2}
            />
          ))}
          <text x={padLeft} y={height - 6} fontSize={10} fill="#898781">
            {points[0].date}
          </text>
          <text x={width - padRight} y={height - 6} fontSize={10} fill="#898781" textAnchor="end">
            {points[points.length - 1].date}
          </text>
        </svg>
        {hovered && (
          <div
            className="pointer-events-none absolute top-0 rounded-md border border-border bg-foreground px-2 py-1 text-xs text-background shadow-md"
            style={{ left: `${(hovered.x / width) * 100}%`, transform: "translate(-50%, -110%)" }}
          >
            <div className="font-semibold">{hovered.count} request{hovered.count === 1 ? "" : "s"}</div>
            <div className="opacity-80">{hovered.date}</div>
          </div>
        )}
      </div>
    </div>
  );
}

export { formatCompact };
