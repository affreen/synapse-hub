"use client";

import Link from "next/link";

type Mode = "policy" | "sql" | "action";

type CapabilityAction =
  | { kind: "prompt"; mode: Mode; label: string; prompt: string }
  | { kind: "link"; label: string; href: string; note: string };

interface CapabilityCategory {
  label: string;
  description: string;
  actions: CapabilityAction[];
}

interface RoleCopilot {
  title: string;
  categories: CapabilityCategory[];
}

// Prompts here mirror the cases in backend/evals/eval_set.json and
// docs/ai_eval_results.md, so every suggestion routes to a capability the
// assistant is actually built (and tested) to handle — not aspirational UI.
export const ROLE_COPILOT: Record<string, RoleCopilot> = {
  EMPLOYEE: {
    title: "Employee Copilot",
    categories: [
      {
        label: "Policy questions",
        description: "Answers grounded in the HR policy library, with sources cited.",
        actions: [
          { kind: "prompt", mode: "policy", label: "How many sick leaves do I get?", prompt: "How many sick leaves do I get?" },
          { kind: "prompt", mode: "policy", label: "Can I work from home?", prompt: "Can I work from home?" },
        ],
      },
      {
        label: "Own leave",
        description: "Apply for leave or check your balance.",
        actions: [
          { kind: "prompt", mode: "action", label: "Apply casual leave", prompt: "Apply casual leave for tomorrow because of personal work." },
          { kind: "prompt", mode: "action", label: "Check my leave balance", prompt: "What is my remaining leave balance?" },
        ],
      },
      {
        label: "Own tickets",
        description: "Raise a support ticket or check its status.",
        actions: [
          { kind: "prompt", mode: "action", label: "Raise a VPN ticket", prompt: "Create a ticket for VPN issue" },
          { kind: "prompt", mode: "action", label: "Check my ticket status", prompt: "What is the status of my tickets?" },
        ],
      },
      {
        label: "Own projects",
        description: "See what you're currently staffed on.",
        actions: [
          { kind: "prompt", mode: "sql", label: "Show my project assignments", prompt: "Show my current project assignments" },
        ],
      },
    ],
  },
  MANAGER: {
    title: "Manager Copilot",
    categories: [
      {
        label: "Team insights",
        description: "Read-only lookups over people, skills, and projects.",
        actions: [
          { kind: "prompt", mode: "sql", label: "Who knows Python?", prompt: "Which employees know Python?" },
          { kind: "prompt", mode: "sql", label: "Engineering + FastAPI", prompt: "Find Engineering employees with FastAPI skills" },
        ],
      },
      {
        label: "Leave approvals",
        description: "Approve or reject a specific pending leave request (asks for confirmation before acting).",
        actions: [
          { kind: "prompt", mode: "action", label: "Approve a leave request", prompt: "Approve leave request id " },
          { kind: "prompt", mode: "action", label: "Reject a leave request", prompt: "Reject leave request id " },
        ],
      },
      {
        label: "Ticket management",
        description: "Assign tickets or update their status.",
        actions: [
          { kind: "prompt", mode: "action", label: "Assign a ticket", prompt: "Assign ticket id 1 to employee id 3." },
          { kind: "prompt", mode: "action", label: "Mark a ticket resolved", prompt: "Mark ticket id 1 as resolved." },
        ],
      },
      {
        label: "Project staffing",
        description: "Staff an employee onto a project (asks for confirmation before acting).",
        actions: [
          {
            kind: "prompt",
            mode: "action",
            label: "Assign to a project",
            prompt: "Assign Employee User to HR Policy Copilot as AI Engineer.",
          },
        ],
      },
    ],
  },
  ADMIN: {
    title: "Admin Copilot",
    categories: [
      {
        label: "HR operations",
        description: "Company-wide people and project queries.",
        actions: [
          { kind: "prompt", mode: "sql", label: "Which projects are ongoing?", prompt: "Which projects are currently ongoing?" },
        ],
      },
      {
        label: "Announcements",
        description: "Post a company-wide announcement (asks for confirmation before acting).",
        actions: [
          {
            kind: "prompt",
            mode: "action",
            label: "Post an announcement",
            prompt: "Create an announcement that Friday's townhall is moved to 5 PM.",
          },
        ],
      },
      {
        label: "Employee lifecycle",
        description: "Create, update, or deactivate employees.",
        actions: [
          { kind: "link", label: "Manage in Employees", href: "/employees", note: "Not available through chat yet." },
        ],
      },
      {
        label: "Policy management",
        description: "Upload, edit, or remove HR policy documents.",
        actions: [
          {
            kind: "link",
            label: "Manage in HR Policies",
            href: "/hr-policies",
            note: "Chat can answer policy questions, but can't edit documents yet.",
          },
        ],
      },
    ],
  },
};

export function CopilotQuickActions({
  role,
  onPick,
}: {
  role: string;
  onPick: (mode: Mode, prompt: string) => void;
}) {
  const copilot = ROLE_COPILOT[role] ?? ROLE_COPILOT.EMPLOYEE;

  return (
    <div className="mx-auto max-w-2xl">
      <p className="mb-3 text-center text-sm font-medium text-foreground">{copilot.title} — quick actions</p>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {copilot.categories.map((category) => (
          <div key={category.label} className="rounded-xl border border-border bg-card p-3 text-left">
            <p className="text-sm font-semibold">{category.label}</p>
            <p className="mt-0.5 text-xs text-muted-foreground">{category.description}</p>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {category.actions.map((action) =>
                action.kind === "prompt" ? (
                  <button
                    key={action.label}
                    type="button"
                    onClick={() => onPick(action.mode, action.prompt)}
                    className="rounded-full border border-indigo-200 bg-indigo-50 px-2.5 py-1 text-xs font-medium text-indigo-700 hover:bg-indigo-100"
                  >
                    {action.label}
                  </button>
                ) : (
                  <Link
                    key={action.label}
                    href={action.href}
                    className="rounded-full border border-border bg-background px-2.5 py-1 text-xs font-medium text-muted-foreground hover:text-foreground"
                    title={action.note}
                  >
                    {action.label} →
                  </Link>
                )
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
