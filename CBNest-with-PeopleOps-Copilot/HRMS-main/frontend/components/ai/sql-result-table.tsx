export function SqlResultTable({
  rows,
  sql,
  showSql,
}: {
  rows: Record<string, unknown>[];
  sql?: string | null;
  showSql: boolean;
}) {
  if (!rows || rows.length === 0) return null;
  const columns = Object.keys(rows[0]);

  return (
    <div className="mt-3 overflow-hidden rounded-lg border border-border">
      {showSql && sql && (
        <div className="border-b border-border bg-muted/50 px-3 py-2">
          <code className="whitespace-pre-wrap break-all text-xs text-muted-foreground">{sql}</code>
        </div>
      )}
      <div className="max-h-64 overflow-auto">
        <table className="w-full text-left text-xs">
          <thead className="bg-muted/50 text-muted-foreground">
            <tr>
              {columns.map((c) => (
                <th key={c} className="px-3 py-2 font-medium">
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr key={i} className="border-t border-border">
                {columns.map((c) => (
                  <td key={c} className="px-3 py-2">
                    {String(row[c] ?? "")}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
