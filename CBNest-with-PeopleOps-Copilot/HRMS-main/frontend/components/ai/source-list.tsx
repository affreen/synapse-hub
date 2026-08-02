import { PolicySource } from "@/lib/api";

export function SourceList({ sources }: { sources: PolicySource[] }) {
  if (!sources || sources.length === 0) return null;

  return (
    <div className="mt-2 flex flex-wrap gap-2">
      {sources.map((s, i) => (
        <span
          key={`${s.title}-${i}`}
          title={s.filename || undefined}
          className="inline-flex items-center gap-1 rounded-full bg-indigo-50 px-2.5 py-1 text-xs font-medium text-indigo-700"
        >
          📄 {s.title}
          <span className="text-indigo-400">· {s.category}</span>
        </span>
      ))}
    </div>
  );
}
