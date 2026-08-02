"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import { Sidebar } from "@/components/layout/sidebar";
import { Topbar } from "@/components/layout/topbar";
import { Badge } from "@/components/ui/badge";
import { ChatPanel } from "@/components/ai/chat-panel";
import { fetchProfile } from "@/lib/api";

export default function AICopilotPage() {
  const [name, setName] = useState("User");
  const [role, setRole] = useState("EMPLOYEE");
  const [ready, setReady] = useState(false);
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

  return (
    <main className="flex min-h-screen">
      <Sidebar />
      <section className="flex w-full flex-col">
        <Topbar name={name} title="PeopleOps Copilot" />
        <div className="space-y-4 p-6">
          <div className="flex items-center gap-3">
            <h1 className="text-lg font-semibold">NovaWorks PeopleOps Copilot</h1>
            <Badge className="bg-indigo-100 text-indigo-700">{role}</Badge>
          </div>
          <p className="text-sm text-muted-foreground">
            Ask HR policy questions, look up people &amp; project data, or automate HR tasks like leave requests
            and tickets — all scoped to what your role is allowed to see and do.
          </p>

          {ready && token ? (
            <ChatPanel token={token} role={role} name={name} />
          ) : (
            <div className="rounded-xl border border-border bg-card p-6 text-sm text-muted-foreground">Loading...</div>
          )}
        </div>
      </section>
    </main>
  );
}
