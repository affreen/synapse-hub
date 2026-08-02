"use client";

import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  ActionChatData,
  PendingAction,
  PolicyChatData,
  SqlChatData,
  askPolicy,
  askSql,
  runAction,
} from "@/lib/api";
import { SourceList } from "./source-list";
import { SqlResultTable } from "./sql-result-table";
import { ActionResultCard } from "./action-result-card";
import { CopilotQuickActions } from "./copilot-quick-actions";

type Mode = "policy" | "sql" | "action";

interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "error";
  text: string;
  policyData?: PolicyChatData;
  sqlData?: SqlChatData;
  actionData?: ActionChatData;
}

const MODES: { key: Mode; label: string; placeholder: string; hint: string }[] = [
  {
    key: "policy",
    label: "Ask HR Policy",
    placeholder: "e.g. What is the sick leave policy?",
    hint: "Answers are grounded in the HR policy library, with sources cited.",
  },
  {
    key: "sql",
    label: "Ask About People & Projects",
    placeholder: "e.g. Which employees know Python?",
    hint: "Read-only lookups over employees, projects, skills, and your own HR data.",
  },
  {
    key: "action",
    label: "Automate HR Task",
    placeholder: "e.g. Apply casual leave for tomorrow",
    hint: "Performs HR actions like leave requests, tickets, and approvals via existing APIs.",
  },
];

function uid() {
  return Math.random().toString(36).slice(2);
}

export function ChatPanel({ token, role, name }: { token: string; role: string; name: string }) {
  const [mode, setMode] = useState<Mode>("policy");
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loading, setLoading] = useState(false);
  const [pendingAction, setPendingAction] = useState<PendingAction | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  async function send(overrideText?: string) {
    const text = (overrideText ?? input).trim();
    if (!text || loading) return;

    setMessages((prev) => [...prev, { id: uid(), role: "user", text }]);
    setInput("");
    setLoading(true);

    try {
      if (mode === "policy") {
        const res = await askPolicy(token, text);
        if (!res.ok || !("success" in res.body) || !res.body.success) {
          throw new Error(("error" in res.body && res.body.error?.message) || "No response");
        }
        setMessages((prev) => [...prev, { id: uid(), role: "assistant", text: res.body.data.answer, policyData: res.body.data }]);
      } else if (mode === "sql") {
        const res = await askSql(token, text);
        if (!res.ok || !("success" in res.body) || !res.body.success) {
          throw new Error(("error" in res.body && res.body.error?.message) || "No response");
        }
        setMessages((prev) => [...prev, { id: uid(), role: "assistant", text: res.body.data.answer, sqlData: res.body.data }]);
      } else {
        const res = await runAction(token, text, pendingAction);
        if (!res.ok || !("success" in res.body) || !res.body.success) {
          throw new Error(("error" in res.body && res.body.error?.message) || "No response");
        }
        setMessages((prev) => [...prev, { id: uid(), role: "assistant", text: res.body.data.answer, actionData: res.body.data }]);
        setPendingAction(res.body.data.pending_action || null);
      }
    } catch (err: any) {
      setMessages((prev) => [...prev, { id: uid(), role: "error", text: err.message || "Something went wrong" }]);
    } finally {
      setLoading(false);
    }
  }

  function handleConfirm(pending: PendingAction) {
    setPendingAction(pending);
    send("yes, confirm");
  }

  function handleCancel() {
    setPendingAction(null);
    send("no, cancel");
  }

  const activeModeMeta = MODES.find((m) => m.key === mode)!;
  const canSeeSql = role === "MANAGER" || role === "ADMIN";

  return (
    <div className="flex h-[calc(100vh-140px)] flex-col overflow-hidden rounded-xl border border-border bg-card">
      {/* Mode tabs */}
      <div className="flex gap-1 border-b border-border px-4 pt-3">
        {MODES.map((m) => (
          <button
            key={m.key}
            type="button"
            onClick={() => setMode(m.key)}
            className={`rounded-t-lg px-3 py-2 text-sm font-medium transition ${
              mode === m.key ? "border border-b-0 border-border bg-background text-indigo-700" : "text-muted-foreground hover:text-foreground"
            }`}
          >
            {m.label}
          </button>
        ))}
      </div>
      <p className="border-b border-border bg-background px-4 py-2 text-xs text-muted-foreground">{activeModeMeta.hint}</p>

      {/* Message history */}
      <div className="flex-1 overflow-y-auto bg-muted/30 px-4 py-4">
        {messages.length === 0 && (
          <div className="mt-6 space-y-6">
            <p className="text-center text-sm text-muted-foreground">
              Hi {name.split(" ")[0]}, ask me anything about HR.
            </p>
            <CopilotQuickActions
              role={role}
              onPick={(pickedMode, prompt) => {
                setMode(pickedMode);
                setInput(prompt);
              }}
            />
          </div>
        )}
        <div className="space-y-3">
          {messages.map((m) => (
            <div key={m.id} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
              <div
                className={`max-w-[80%] rounded-2xl px-4 py-2.5 text-sm shadow-sm ${
                  m.role === "user"
                    ? "bg-indigo-600 text-white"
                    : m.role === "error"
                    ? "border border-red-200 bg-red-50 text-red-700"
                    : "border border-border bg-card"
                }`}
              >
                <p className="whitespace-pre-wrap">{m.text}</p>
                {m.policyData && <SourceList sources={m.policyData.sources} />}
                {m.sqlData && <SqlResultTable rows={m.sqlData.rows} sql={m.sqlData.sql} showSql={canSeeSql} />}
                {m.actionData && <ActionResultCard data={m.actionData} onConfirm={handleConfirm} onCancel={handleCancel} />}
              </div>
            </div>
          ))}
          {loading && (
            <div className="flex justify-start">
              <div className="rounded-2xl border border-border bg-card px-4 py-2.5 text-sm text-muted-foreground shadow-sm">
                Thinking...
              </div>
            </div>
          )}
        </div>
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          send();
        }}
        className="flex gap-2 border-t border-border bg-card p-3"
      >
        <Input value={input} onChange={(e) => setInput(e.target.value)} placeholder={activeModeMeta.placeholder} />
        <Button type="submit" disabled={loading || !input.trim()}>
          Send
        </Button>
      </form>
    </div>
  );
}
