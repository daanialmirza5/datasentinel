import type { ButtonHTMLAttributes, ReactNode } from 'react';
import { ApiError } from '../api/client';
import type { AssetState, Health, ImpactClass, RuleStatus, Severity } from '../api/types';
import { cx, IMPACT_LABELS, type Tone } from '../lib/format';

export function PageHeader({ title, description, actions }: { title: string; description?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="mb-6 flex flex-wrap items-start justify-between gap-4">
      <div className="min-w-0">
        <h1 className="text-2xl font-semibold tracking-tight text-ink">{title}</h1>
        {description && <p className="mt-1 max-w-3xl text-sm text-ink-2">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </header>
  );
}

export function Card({ title, actions, children, className }: { title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={cx('rounded-xl border border-line bg-surface shadow-[0_1px_2px_rgba(16,24,40,0.04)]', className)}>
      {(title || actions) && (
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-5 py-3">
          {title && <h2 className="text-sm font-semibold text-ink">{title}</h2>}
          {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
        </div>
      )}
      <div className="p-5">{children}</div>
    </section>
  );
}

type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger';

export function Button({ variant = 'secondary', className, children, busy, ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant; busy?: boolean }) {
  const styles: Record<ButtonVariant, string> = {
    primary: 'bg-accent text-white hover:bg-accent-strong disabled:bg-accent/50',
    secondary: 'border border-line bg-surface text-ink hover:bg-canvas disabled:text-ink-3',
    ghost: 'text-ink-2 hover:bg-canvas hover:text-ink disabled:text-ink-3',
    danger: 'border border-critical/40 bg-surface text-critical hover:bg-critical/5 disabled:opacity-50',
  };
  return (
    <button
      type="button"
      className={cx(
        'inline-flex items-center justify-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed',
        styles[variant],
        className,
      )}
      disabled={busy || props.disabled}
      aria-busy={busy || undefined}
      {...props}
    >
      {busy && <Spinner small />}
      {children}
    </button>
  );
}

export function Spinner({ small }: { small?: boolean }) {
  return (
    <span
      aria-hidden="true"
      className={cx('inline-block animate-spin rounded-full border-2 border-current border-r-transparent', small ? 'h-3.5 w-3.5' : 'h-5 w-5')}
    />
  );
}

export function Loading({ label = 'Loading…' }: { label?: string }) {
  return (
    <div role="status" className="flex items-center gap-2 py-8 text-sm text-ink-2">
      <Spinner /> {label}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const message = error instanceof Error ? error.message : String(error);
  const requestId = error instanceof ApiError ? error.requestId : null;
  return (
    <div role="alert" className="rounded-lg border border-critical/30 bg-critical/5 px-4 py-3 text-sm">
      <p className="font-medium text-critical">
        <span aria-hidden="true">✕ </span>
        {message}
      </p>
      {error instanceof ApiError && error.details !== undefined && error.details !== null && (
        <pre className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap text-xs text-ink-2">{JSON.stringify(error.details, null, 2)}</pre>
      )}
      <div className="mt-2 flex items-center gap-3 text-xs text-ink-3">
        {requestId && <span>Request id: {requestId}</span>}
        {onRetry && (
          <Button variant="ghost" onClick={onRetry} className="px-2 py-1 text-xs">
            Retry
          </Button>
        )}
      </div>
    </div>
  );
}

export function EmptyState({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center rounded-lg border border-dashed border-line px-6 py-10 text-center">
      <p className="text-sm font-medium text-ink">{title}</p>
      {children && <div className="mt-1 max-w-md text-sm text-ink-2">{children}</div>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function StatCard({ label, value, hint, tone = 'neutral' }: { label: string; value: ReactNode; hint?: ReactNode; tone?: 'neutral' | 'bad' | 'good' }) {
  return (
    <div className="rounded-xl border border-line bg-surface px-5 py-4">
      <p className="text-xs font-medium uppercase tracking-wide text-ink-3">{label}</p>
      <p className={cx('mt-1 text-3xl font-semibold text-ink', tone === 'bad' && 'text-critical', tone === 'good' && 'text-good-ink')}>{value}</p>
      {hint && <p className="mt-1 text-xs text-ink-2">{hint}</p>}
    </div>
  );
}

const TONE_STYLES: Record<Tone, string> = {
  good: 'bg-good/10 text-good-ink ring-good/30',
  warning: 'bg-warning/15 text-warning-ink ring-warning/40',
  serious: 'bg-serious/15 text-serious-ink ring-serious/40',
  critical: 'bg-critical/10 text-critical ring-critical/30',
  neutral: 'bg-canvas text-ink-2 ring-line',
  info: 'bg-accent/10 text-accent-strong ring-accent/30',
};

const TONE_ICONS: Record<Tone, string> = { good: '✓', warning: '!', serious: '▲', critical: '✕', neutral: '•', info: 'i' };

export function Badge({ tone = 'neutral', children, title }: { tone?: Tone; children: ReactNode; title?: string }) {
  return (
    <span title={title} className={cx('inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset', TONE_STYLES[tone])}>
      <span aria-hidden="true" className="text-[10px] font-bold">
        {TONE_ICONS[tone]}
      </span>
      {children}
    </span>
  );
}

const SEVERITY_TONES: Record<Severity, Tone> = { info: 'info', low: 'neutral', medium: 'warning', high: 'serious', critical: 'critical' };

export function SeverityBadge({ severity }: { severity: Severity }) {
  return <Badge tone={SEVERITY_TONES[severity] ?? 'neutral'}>{severity}</Badge>;
}

const STATUS_TONES: Record<RuleStatus, Tone> = { passed: 'good', failed: 'critical', error: 'serious', not_evaluated: 'neutral' };
const STATUS_LABELS: Record<RuleStatus, string> = { passed: 'Passed', failed: 'Failed', error: 'Error', not_evaluated: 'Not evaluated' };

export function RuleStatusBadge({ status }: { status: RuleStatus }) {
  return <Badge tone={STATUS_TONES[status]}>{STATUS_LABELS[status]}</Badge>;
}

const HEALTH: Record<Health | AssetState, [Tone, string]> = {
  passing: ['good', 'Passing'],
  failing: ['critical', 'Failing'],
  incomplete: ['warning', 'Incomplete'],
  no_rules: ['neutral', 'No rules'],
  anomalous: ['serious', 'Anomalous'],
  unvalidated: ['neutral', 'Unvalidated'],
  no_checks: ['neutral', 'No own checks'],
};

export function HealthBadge({ state }: { state: Health | AssetState }) {
  const [tone, label] = HEALTH[state] ?? ['neutral', state];
  return <Badge tone={tone}>{label}</Badge>;
}

export function ImpactBadge({ value }: { value: ImpactClass }) {
  const [tone, label] = IMPACT_LABELS[value];
  return <Badge tone={tone}>{label}</Badge>;
}

export function Field({ label, htmlFor, hint, children }: { label: string; htmlFor: string; hint?: ReactNode; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={htmlFor} className="text-xs font-medium text-ink-2">
        {label}
      </label>
      {children}
      {hint && <p className="text-xs text-ink-3">{hint}</p>}
    </div>
  );
}

export function Tabs<T extends string>({ tabs, value, onChange, label }: { tabs: { id: T; label: string }[]; value: T; onChange: (id: T) => void; label: string }) {
  return (
    <div role="tablist" aria-label={label} className="mb-4 flex gap-1 overflow-x-auto border-b border-line">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          role="tab"
          type="button"
          aria-selected={value === tab.id}
          onClick={() => onChange(tab.id)}
          className={cx(
            '-mb-px whitespace-nowrap border-b-2 px-3 py-2 text-sm font-medium focus-visible:outline-2 focus-visible:outline-accent',
            value === tab.id ? 'border-accent text-accent-strong' : 'border-transparent text-ink-2 hover:text-ink',
          )}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}

export function Pagination({ offset, limit, total, onChange }: { offset: number; limit: number; total: number; onChange: (offset: number) => void }) {
  const end = Math.min(offset + limit, total);
  return (
    <nav aria-label="Pagination" className="mt-3 flex items-center justify-between text-sm text-ink-2">
      <span>
        {total === 0 ? 'No rows' : `Rows ${offset + 1}–${end} of ${total.toLocaleString()}`}
      </span>
      <div className="flex gap-2">
        <Button onClick={() => onChange(Math.max(0, offset - limit))} disabled={offset === 0}>
          Previous
        </Button>
        <Button onClick={() => onChange(offset + limit)} disabled={end >= total}>
          Next
        </Button>
      </div>
    </nav>
  );
}

export function KeyValue({ items }: { items: [string, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1.5 text-sm">
      {items.map(([key, value]) => (
        <div key={key} className="contents">
          <dt className="text-ink-3">{key}</dt>
          <dd className="min-w-0 break-words text-ink">{value}</dd>
        </div>
      ))}
    </dl>
  );
}
