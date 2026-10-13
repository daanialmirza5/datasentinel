import type { ReactNode } from 'react';
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ReferenceDot, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import type { ComparisonChart as ComparisonData, FrequencyItem, Histogram } from '../api/types';
import { formatNumber } from '../lib/format';

const BASE = '#2a78d6';
const CANDIDATE = '#eb6834';
const CRITICAL = '#d03b3b';
const AXIS = { stroke: '#c3c2b7', tick: { fill: '#6b7280', fontSize: 11 }, tickLine: false } as const;
const GRID = { stroke: '#e1e0d9', strokeDasharray: '0', vertical: false } as const;
const TOOLTIP_STYLE = { borderRadius: 8, border: '1px solid #e3e5e9', fontSize: 12, boxShadow: '0 4px 12px rgba(16,24,40,0.08)' };

/** Every chart is a figure with a caption and an equivalent data table (identity never by colour alone). */
function Figure({ label, children, table }: { label: string; children: ReactNode; table: { headers: string[]; rows: (string | number)[][] } }) {
  return (
    <figure className="m-0" aria-label={label}>
      <div className="h-56 w-full" role="img" aria-label={label}>
        {children}
      </div>
      <details className="mt-1 text-xs text-ink-2">
        <summary className="cursor-pointer select-none text-ink-3 hover:text-ink">Show data table</summary>
        <div className="mt-2 max-h-60 overflow-auto">
          <table className="tabular w-full text-left">
            <thead>
              <tr>{table.headers.map((h) => <th key={h} className="border-b border-line px-2 py-1 font-medium">{h}</th>)}</tr>
            </thead>
            <tbody>
              {table.rows.map((row, i) => (
                <tr key={i}>{row.map((cell, j) => <td key={j} className="border-b border-line/60 px-2 py-1">{cell}</td>)}</tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </figure>
  );
}

function binLabel(edges: (number | string)[], index: number): string {
  const lo = edges[index];
  const hi = edges[index + 1];
  if (typeof lo === 'string' && typeof hi === 'string') return lo.slice(0, 10);
  return `${formatNumber(Number(lo), 3)}–${formatNumber(Number(hi), 3)}`;
}

export function DistributionChart({ histogram, label }: { histogram: Histogram; label: string }) {
  const data =
    histogram.kind === 'discrete'
      ? (histogram.values ?? []).map((v, i) => ({ bin: String(v), count: histogram.counts[i] ?? 0 }))
      : histogram.counts.map((count, i) => ({ bin: binLabel(histogram.edges ?? [], i), count }));
  return (
    <Figure label={label} table={{ headers: ['Bin', 'Rows'], rows: data.map((d) => [d.bin, d.count]) }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 8, right: 8, bottom: 4, left: 0 }} barCategoryGap={2}>
          <CartesianGrid {...GRID} />
          <XAxis dataKey="bin" {...AXIS} interval="preserveStartEnd" minTickGap={24} />
          <YAxis {...AXIS} axisLine={false} width={44} allowDecimals={false} />
          <Tooltip contentStyle={TOOLTIP_STYLE} cursor={{ fill: 'rgba(42,120,214,0.08)' }} formatter={(v) => [formatNumber(Number(v)), 'Rows']} />
          <Bar dataKey="count" name="Rows" fill={BASE} radius={[4, 4, 0, 0]} isAnimationActive={false} />
        </BarChart>
      </ResponsiveContainer>
    </Figure>
  );
}

export function FrequencyChart({ items, label }: { items: FrequencyItem[]; label: string }) {
  const data = items.slice(0, 12).map((item) => ({ value: item.value, pct: item.pct, count: item.count }));
  return (
    <Figure label={label} table={{ headers: ['Value', 'Rows', 'Share %'], rows: data.map((d) => [d.value, d.count, formatNumber(d.pct)]) }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} layout="vertical" margin={{ top: 4, right: 16, bottom: 4, left: 8 }} barCategoryGap={2}>
          <CartesianGrid stroke="#e1e0d9" horizontal={false} />
          <XAxis type="number" {...AXIS} unit="%" />
          <YAxis type="category" dataKey="value" {...AXIS} width={110} axisLine={false} />
          <Tooltip contentStyle={TOOLTIP_STYLE} cursor={{ fill: 'rgba(42,120,214,0.08)' }} formatter={(v) => [`${formatNumber(Number(v))}%`, 'Share']} />
          <Bar dataKey="pct" name="Share" fill={BASE} radius={[0, 4, 4, 0]} isAnimationActive={false} />
        </BarChart>
      </ResponsiveContainer>
    </Figure>
  );
}

export function ComparisonChart({ chart, label, baseLabel = 'Baseline', candidateLabel = 'Candidate' }: { chart: ComparisonData; label: string; baseLabel?: string; candidateLabel?: string }) {
  const edges = chart.edges ?? [];
  const labels =
    chart.kind === 'categorical'
      ? (chart.labels ?? [])
      : chart.binning === 'baseline_quantiles_with_tails'
        ? [
            `< ${formatNumber(Number(edges[0]), 3)}`,
            ...edges.slice(0, -1).map((_, i) => binLabel(edges, i)),
            `> ${formatNumber(Number(edges[edges.length - 1]), 3)}`,
          ]
        : chart.base.map((_, i) => binLabel(edges, i));
  const data = labels.map((bin, i) => ({ bin, base: 100 * (chart.base[i] ?? 0), candidate: 100 * (chart.candidate[i] ?? 0) }));
  return (
    <Figure
      label={label}
      table={{ headers: ['Bin / value', `${baseLabel} %`, `${candidateLabel} %`], rows: data.map((d) => [d.bin, formatNumber(d.base), formatNumber(d.candidate)]) }}
    >
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 8, right: 8, bottom: 4, left: 0 }} barGap={2} barCategoryGap="18%">
          <CartesianGrid {...GRID} />
          <XAxis dataKey="bin" {...AXIS} interval="preserveStartEnd" minTickGap={24} />
          <YAxis {...AXIS} axisLine={false} width={44} unit="%" />
          <Tooltip contentStyle={TOOLTIP_STYLE} cursor={{ fill: 'rgba(42,120,214,0.08)' }} formatter={(v, name) => [`${formatNumber(Number(v))}%`, name]} />
          <Legend verticalAlign="top" height={24} iconType="square" itemSorter="dataKey" wrapperStyle={{ fontSize: 12, color: '#4b5260' }} />
          <Bar dataKey="base" name={baseLabel} fill={BASE} radius={[4, 4, 0, 0]} isAnimationActive={false} />
          <Bar dataKey="candidate" name={candidateLabel} fill={CANDIDATE} radius={[4, 4, 0, 0]} isAnimationActive={false} />
        </BarChart>
      </ResponsiveContainer>
    </Figure>
  );
}

export function TimeSeriesChart({ points, flagged, label, metric }: { points: { date: string; value: number | null }[]; flagged: { date: string; value: number }[]; label: string; metric: string }) {
  const flaggedDates = new Set(flagged.map((f) => f.date));
  return (
    <Figure
      label={label}
      table={{ headers: ['Date', metric, 'Flagged'], rows: points.map((p) => [p.date, formatNumber(p.value ?? NaN, 3), flaggedDates.has(p.date) ? 'yes' : '']) }}
    >
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={points} margin={{ top: 12, right: 12, bottom: 4, left: 0 }}>
          <CartesianGrid {...GRID} />
          <XAxis dataKey="date" {...AXIS} minTickGap={32} />
          <YAxis {...AXIS} axisLine={false} width={52} domain={['auto', 'auto']} />
          <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(v) => [formatNumber(Number(v), 3), metric]} />
          <Line type="monotone" dataKey="value" name={metric} stroke={BASE} strokeWidth={2} dot={false} isAnimationActive={false} />
          {flagged.map((f) => (
            <ReferenceDot key={f.date} x={f.date} y={f.value} r={5} fill={CRITICAL} stroke="#ffffff" strokeWidth={2} />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </Figure>
  );
}
