"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { ShieldAlert } from "lucide-react";

import { Sidebar } from "@/components/layout/sidebar";
import { Topbar } from "@/components/layout/topbar";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import {
  BarList,
  DailyVolumeChart,
  StatTile,
  StatusBarList,
  formatCompact,
} from "@/components/ai/observability-charts";
import { AiObservabilityData, fetchAiObservability, fetchProfile } from "@/lib/api";

const RANGE_PRESETS = [
  { label: "Last 7 days", days: 7 },
  { label: "Last 14 days", days: 14 },
  { label: "Last 30 days", days: 30 },
  { label: "Last 90 days", days: 90 },
];

function formatLatency(ms: number | null): string {
  if (ms === null) return "—";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

const REFUSAL_REASON_LABELS: Record<string, string> = {
  FORBIDDEN_COLUMN: "Forbidden column requested",
  BLOCKED_KEYWORD: "Blocked SQL keyword (DROP/DELETE/…)",
  DISALLOWED_TABLE: "Disallowed table",
  ROLE_SCOPE_VIOLATION: "Role-scope violation",
  NOT_SELECT: "Non-SELECT statement",
  MULTIPLE_STATEMENTS: "Multiple SQL statements",
  DISALLOWED_SYNTAX: "Disallowed syntax (comments/;)",
  EMPTY_SQL: "Empty SQL generated",
  EXECUTION_ERROR: "Query execution error",
  LLM_GENERATION_FAILED: "LLM failed to generate a query",
  AGENT_DISABLED: "Agent disabled",
  PERMISSION_DENIED: "Permission denied (role)",
  INTENT_EXTRACTION_FAILED: "Couldn't parse intent",
};

function formatReasonLabel(reason: string): string {
  return REFUSAL_REASON_LABELS[reason] ?? reason;
}

export default function AiObservabilityPage() {
  const [name, setName] = useState("User");
  const [role, setRole] = useState("EMPLOYEE");
  const [ready, setReady] = useState(false);
  const [days, setDays] = useState(14);
  const [data, setData] = useState<AiObservabilityData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [showTable, setShowTable] = useState(false);
  const router = useRouter();

  const token = useMemo(() => {
    if (typeof window === "undefined") return null;
    return localStorage.getItem("hrms_access_token");
  }, []);

  const clearAuthAndRedirect = () => {
    localStorage.removeItem("hrms_access_token");
    document.cookie = "hrms_auth=; path=/; max-age=0; samesite=lax";
    router.push("/login");
  };

  useEffect(() => {
    if (!token) {
      clearAuthAndRedirect();
      return;
    }
    (async () => {
      const profileResult = await fetchProfile(token);
      if (profileResult.status === 401) {
        clearAuthAndRedirect();
        return;
      }
      if (profileResult.ok && "success" in profileResult.body && profileResult.body.success) {
        setName(profileResult.body.data.name);
        setRole(profileResult.body.data.role);
      }
      setReady(true);
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  useEffect(() => {
    if (!token || !ready || role !== "ADMIN") return;
    let cancelled = false;
    setLoading(true);
    setError("");
    (async () => {
      const result = await fetchAiObservability(token, days);
      if (cancelled) return;
      if (result.ok && "success" in result.body && result.body.success) {
        setData(result.body.data);
      } else {
        setError("Couldn't load observability data. Try again shortly.");
      }
      setLoading(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [token, ready, role, days]);

  if (ready && role !== "ADMIN") {
    return (
      <main className="flex min-h-screen">
        <Sidebar />
        <section className="flex w-full flex-col">
          <Topbar name={name} title="AI Observability" />
          <div className="flex flex-1 flex-col items-center justify-center gap-3 p-6 text-center">
            <ShieldAlert className="h-8 w-8 text-muted-foreground" />
            <p className="text-sm text-muted-foreground">
              AI Observability is restricted to Admin accounts.
            </p>
          </div>
        </section>
      </main>
    );
  }

  return (
    <main className="flex min-h-screen">
      <Sidebar />
      <section className="flex w-full flex-col">
        <Topbar name={name} title="AI Observability" />
        <div className="space-y-4 p-6">
          <div>
            <h1 className="text-lg font-semibold text-foreground">PeopleOps Copilot — AI Observability</h1>
            <p className="text-sm text-muted-foreground">
              Request volume, latency, and LLM token cost across the Policy RAG, SQL, and HR Action agents.
            </p>
          </div>

          {/* Filter row — date range presets, scopes everything below it */}
          <div className="flex flex-wrap items-center gap-2">
            {RANGE_PRESETS.map((preset) => (
              <button
                key={preset.days}
                onClick={() => setDays(preset.days)}
                className={`rounded-full px-3 py-1.5 text-xs font-medium transition ${
                  days === preset.days
                    ? "bg-primary text-primary-foreground"
                    : "border border-border bg-card text-muted-foreground hover:bg-muted"
                }`}
              >
                {preset.label}
              </button>
            ))}
          </div>

          {error && <p className="text-sm text-red-600">{error}</p>}

          {!data && loading ? (
            <p className="text-sm text-muted-foreground">Loading…</p>
          ) : data ? (
            <div className={loading ? "space-y-4 opacity-60 transition-opacity" : "space-y-4 transition-opacity"}>
              <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
                <StatTile label="Total requests" value={formatCompact(data.totals.total_requests)} />
                <StatTile label="Avg latency" value={formatLatency(data.totals.avg_latency_ms)} />
                <StatTile
                  label="Input tokens"
                  value={formatCompact(data.totals.total_input_tokens)}
                  sublabel={`${formatCompact(data.totals.total_llm_calls)} LLM calls`}
                />
                <StatTile label="Output tokens" value={formatCompact(data.totals.total_output_tokens)} />
              </div>

              <DailyVolumeChart data={data.daily.map((d) => ({ date: d.date, count: d.count }))} />

              <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                <BarList
                  title="Requests by agent"
                  items={data.by_intent.map((row) => ({ key: row.intent, label: row.intent, value: row.count }))}
                />
                <StatusBarList items={data.by_status.map((row) => ({ status: row.status, count: row.count }))} />
                <BarList
                  title="Top tools invoked"
                  items={data.by_tool.map((row) => ({ key: row.tool_name, label: row.tool_name, value: row.count }))}
                  emptyLabel="No tool calls in this range yet."
                />
                <BarList
                  title="Requests by role"
                  items={data.by_role.map((row) => ({ key: row.role, label: row.role, value: row.count }))}
                />
              </div>

              <BarList
                title="Guardrail & refusal reasons"
                items={data.by_refusal_reason.map((row) => ({
                  key: row.reason,
                  label: formatReasonLabel(row.reason),
                  value: row.count,
                  color: "#ec835a",
                }))}
                emptyLabel="No guardrail blocks or failures in this range — every request either succeeded or was a normal not-applicable/cancelled outcome."
              />

              <div className="rounded-xl border border-border bg-card p-4 shadow-sm">
                <button
                  onClick={() => setShowTable((v) => !v)}
                  className="text-xs font-medium text-primary hover:underline"
                >
                  {showTable ? "Hide raw data table" : "View raw data as table"}
                </button>
                {showTable && (
                  <div className="mt-3 overflow-x-auto">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Date</TableHead>
                          <TableHead>Requests</TableHead>
                          <TableHead>Avg latency</TableHead>
                          <TableHead>Input tokens</TableHead>
                          <TableHead>Output tokens</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {data.daily.map((row) => (
                          <TableRow key={row.date}>
                            <TableCell>{row.date}</TableCell>
                            <TableCell className="tabular-nums">{row.count}</TableCell>
                            <TableCell className="tabular-nums">{formatLatency(row.avg_latency_ms)}</TableCell>
                            <TableCell className="tabular-nums">{row.input_tokens}</TableCell>
                            <TableCell className="tabular-nums">{row.output_tokens}</TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>
                )}
              </div>
            </div>
          ) : null}
        </div>
      </section>
    </main>
  );
}
