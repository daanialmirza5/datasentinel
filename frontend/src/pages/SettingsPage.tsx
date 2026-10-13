import { useState } from 'react';
import { api } from '../api/client';
import { Badge, Button, Card, ErrorState, KeyValue, Loading, PageHeader } from '../components/ui';
import { formatBytes } from '../lib/format';
import { useAsync } from '../hooks/useAsync';

export function SettingsPage() {
  const settings = useAsync(() => api.settings(), []);
  const ready = useAsync(() => api.ready(), []);
  const health = useAsync(() => api.health(), []);
  const [message, setMessage] = useState<string>();
  const [error, setError] = useState<unknown>();
  const [busy, setBusy] = useState<string>();

  async function act(key: string, fn: () => Promise<string>) {
    setBusy(key);
    setError(undefined);
    setMessage(undefined);
    try {
      setMessage(await fn());
      settings.reload();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(undefined);
    }
  }

  return (
    <>
      <PageHeader title="Settings & documentation" description="Local configuration, data handling, retention, service health and a short usage guide." />
      <div className="grid gap-6 xl:grid-cols-2">
        <Card title="Service health" actions={<Button onClick={() => { ready.reload(); health.reload(); }}>Re-check</Button>}>
          {health.error ? (
            <ErrorState error={health.error} />
          ) : (
            <p className="mb-3 text-sm">
              API {health.data ? <Badge tone="good">{health.data.status}</Badge> : <Loading label="" />} version {health.data?.version}
            </p>
          )}
          {ready.error && <ErrorState error={ready.error} />}
          {ready.data && (
            <ul className="space-y-1 text-sm">
              {Object.entries(ready.data.checks).map(([name, check]) => (
                <li key={name} className="flex items-center gap-2">
                  {check.ok ? <Badge tone="good">ok</Badge> : <Badge tone="critical">failing</Badge>} {name}
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card title="Data handling & privacy">
          {settings.error && <ErrorState error={settings.error} onRetry={settings.reload} />}
          {!settings.data && !settings.error && <Loading />}
          {settings.data && (
            <>
              <p className="mb-3 text-sm">{settings.data.privacy.statement}</p>
              <KeyValue
                items={[
                  ['External services', settings.data.privacy.external_services.length ? settings.data.privacy.external_services.join(', ') : 'None'],
                  ['Database', settings.data.database_backend],
                  ['Stored data', formatBytes(settings.data.storage.usage_bytes)],
                  ['Storage location', settings.data.storage.location],
                  ['Your data retention', settings.data.retention.user_data],
                  ['Lab data retention', settings.data.retention.lab_data],
                  ['Optional ML detector', settings.data.ml_detector_available ? 'installed' : 'not installed'],
                ]}
              />
            </>
          )}
        </Card>

        <Card title="Limits">
          {settings.data && (
            <KeyValue items={Object.entries(settings.data.limits).map(([k, v]) => [k.replace(/_/g, ' '), String(v)])} />
          )}
          <p className="mt-3 text-xs text-ink-3">Change limits with DATASENTINEL_* environment variables (see .env.example) and restart the API.</p>
        </Card>

        <Card title="Detection thresholds">
          {settings.data && <KeyValue items={Object.entries(settings.data.detection_config).map(([k, v]) => [k.replace(/_/g, ' '), String(v)])} />}
          <p className="mt-3 text-xs text-ink-3">A statistical signal needs p &lt; alpha and an effect above its floor. See docs/methodology.md.</p>
        </Card>

        <Card title="Sample data & maintenance">
          <div className="flex flex-wrap gap-2">
            <Button busy={busy === 'samples'} onClick={() => act('samples', async () => { const r = await api.loadSamples(); return `Loaded ${r.datasets} datasets, ${r.versions} versions and ${r.rules} rules.`; })}>
              Load demo workspace
            </Button>
            <Button busy={busy === 'retention'} onClick={() => act('retention', async () => { const r = await api.runRetention(); return `Removed ${r.expired_experiments_removed} expired experiment(s).`; })}>
              Apply retention now
            </Button>
            <a className="rounded-lg border border-line px-3 py-1.5 text-sm font-medium hover:bg-canvas" href="/api/v1/docs" target="_blank" rel="noreferrer">
              API documentation
            </a>
          </div>
          {message && <p role="status" className="mt-3 text-sm text-good-ink">✓ {message}</p>}
          {error !== undefined && <div className="mt-3"><ErrorState error={error} /></div>}
        </Card>

        <Card title="Usage guide">
          <ol className="list-decimal space-y-2 pl-5 text-sm text-ink-2">
            <li><strong>Import</strong> a CSV/JSON/JSONL file on the Datasets page, or load the demo workspace. Each upload of the same dataset becomes a new version.</li>
            <li><strong>Profile</strong>: every version is profiled exactly on import; inspect it in the dataset explorer.</li>
            <li><strong>Declare rules</strong> on the Quality rules page (or accept suggestions). Rules run automatically on every new version.</li>
            <li><strong>Compare versions</strong> on the Drift page; each signal shows its test, effect size and evidence.</li>
            <li><strong>Declare lineage</strong> and trace downstream impact; follow the evidence-backed recommendations.</li>
            <li><strong>Stress-test</strong> detection in the Fault lab with seeded faults and see what was caught or missed.</li>
            <li><strong>Report</strong>: generate and export Markdown or JSON for your team.</li>
          </ol>
        </Card>
      </div>
    </>
  );
}
