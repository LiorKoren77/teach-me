import type { Language, UsageRow } from "@/lib/api/types";
import type { Strings } from "@/lib/i18n";

// Mirrors api/teachme/services/usage.py's UsageService.format_table: one row per purpose/model
// pair, a total row summing cost only (the other columns have no single meaningful total).
export function UsageTable({ rows, strings, language }: { rows: UsageRow[]; strings: Strings; language: Language }) {
  const cost = new Intl.NumberFormat(language, { style: "currency", currency: "USD", minimumFractionDigits: 4, maximumFractionDigits: 4 });
  const count = new Intl.NumberFormat(language);
  const total = rows.reduce((sum, row) => sum + row.cost_usd, 0);

  return (
    <table className="w-full text-start text-sm">
      <thead>
        <tr className="border-b border-stone-200 text-xs uppercase text-stone-500">
          <th className="px-2 py-1 text-start font-medium">{strings.usage.purpose}</th>
          <th className="px-2 py-1 text-start font-medium">{strings.usage.model}</th>
          <th className="px-2 py-1 text-end font-medium">{strings.usage.calls}</th>
          <th className="px-2 py-1 text-end font-medium">{strings.usage.input}</th>
          <th className="px-2 py-1 text-end font-medium">{strings.usage.output}</th>
          <th className="px-2 py-1 text-end font-medium">{strings.usage.cost}</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row, index) => (
          <tr key={`${row.purpose}-${row.model}-${index}`} className="border-b border-stone-100 text-stone-800">
            <td className="px-2 py-1">{row.purpose}</td>
            <td className="px-2 py-1">{row.model}</td>
            <td className="px-2 py-1 text-end">{count.format(row.calls)}</td>
            <td className="px-2 py-1 text-end">{count.format(row.input_tokens)}</td>
            <td className="px-2 py-1 text-end">{count.format(row.output_tokens)}</td>
            <td className="px-2 py-1 text-end">{cost.format(row.cost_usd)}</td>
          </tr>
        ))}
        <tr className="font-medium text-stone-900">
          <td className="px-2 py-1">{strings.usage.total}</td>
          <td className="px-2 py-1" />
          <td className="px-2 py-1" />
          <td className="px-2 py-1" />
          <td className="px-2 py-1" />
          <td className="px-2 py-1 text-end">{cost.format(total)}</td>
        </tr>
      </tbody>
    </table>
  );
}
