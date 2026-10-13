import { Background, Controls, Handle, Position, ReactFlow, type Edge, type Node, type NodeProps } from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { useMemo, useState, type FormEvent } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api/client';
import type { AssetState, ImpactClass, ImpactResponse, LineageGraph, LineageNode } from '../api/types';
import { Badge, Button, Card, EmptyState, ErrorState, Field, HealthBadge, ImpactBadge, KeyValue, Loading, PageHeader, SeverityBadge } from '../components/ui';
import { cx, IMPACT_LABELS, inputClass } from '../lib/format';
import { useAsync } from '../hooks/useAsync';

const IMPACT_COLORS: Record<ImpactClass, string> = {
  confirmed_failure: '#d03b3b',
  suspected_impact: '#ec835a',
  unverified_risk: '#fab219',
  no_known_impact: '#c3c2b7',
};
const KIND_LABEL: Record<string, string> = { source: 'Source', dataset: 'Dataset', transformation: 'Transformation', report: 'Report', model: 'Model' };

type AssetNodeData = { asset: LineageNode; impact?: ImpactClass; origin?: boolean; selected?: boolean };

function AssetNode({ data }: NodeProps<Node<AssetNodeData>>) {
  const { asset, impact, origin, selected } = data;
  const border = origin ? '#1c5cab' : impact ? IMPACT_COLORS[impact] : '#e3e5e9';
  return (
    <div
      className={cx('w-52 rounded-lg border-2 bg-white px-3 py-2 text-left shadow-sm', selected && 'ring-2 ring-accent ring-offset-2')}
      style={{ borderColor: border }}
    >
      <Handle type="target" position={Position.Left} className="!bg-ink-3" />
      <p className="text-[10px] font-semibold uppercase tracking-wide text-ink-3">{KIND_LABEL[asset.kind] ?? asset.kind}</p>
      <p className="truncate text-sm font-semibold text-ink" title={asset.name}>
        {asset.name}
      </p>
      <div className="mt-1 flex flex-wrap gap-1">
        {asset.kind === 'dataset' && <HealthBadge state={asset.health.state as AssetState} />}
        {origin && <Badge tone="info">Origin</Badge>}
        {impact && !origin && <ImpactBadge value={impact} />}
      </div>
      <Handle type="source" position={Position.Right} className="!bg-ink-3" />
    </div>
  );
}

const nodeTypes = { asset: AssetNode };

export function LineagePage() {
  const graph = useAsync(() => api.lineage(), []);
  const [selected, setSelected] = useState<string | null>(null);
  const [impact, setImpact] = useState<ImpactResponse | null>(null);

  return (
    <>
      <PageHeader
        title="Lineage explorer"
        description="Declared dependencies between sources, datasets, transformations, reports and models. Select an asset to inspect it and trace downstream impact."
        actions={<Button onClick={graph.reload}>Refresh</Button>}
      />
      {graph.loading && !graph.data && <Loading label="Loading lineage…" />}
      {graph.error && <ErrorState error={graph.error} onRetry={graph.reload} />}
      {graph.data && graph.data.nodes.length === 0 && (
        <EmptyState title="No assets yet">Importing a dataset creates a lineage node automatically. Load the demo workspace from the dashboard to see a full pipeline.</EmptyState>
      )}
      {graph.data && graph.data.nodes.length > 0 && (
        <div className="space-y-6">
            <Card
              title="Dependency graph"
              actions={impact && (
                <Button variant="ghost" onClick={() => setImpact(null)}>
                  Clear impact highlight
                </Button>
              )}
            >
              <GraphView graph={graph.data} selected={selected} impact={impact} onSelect={(id) => setSelected(id)} />
              <Legend />
              {graph.data.cycles.length > 0 && (
                <p role="alert" className="mt-2 text-sm text-critical">
                  ✕ Cycles detected (lineage should be acyclic): {graph.data.cycles.map((c) => c.length).join(', ')} node(s) involved.
                </p>
              )}
            </Card>
          <div className="grid items-start gap-6 xl:grid-cols-2">
            {selected ? (
              <AssetPanel
                key={selected}
                assetId={selected}
                graph={graph.data}
                onSelect={setSelected}
                onImpact={setImpact}
                impact={impact?.origin.id === selected ? impact : null}
                onChanged={() => { graph.reload(); setSelected(null); setImpact(null); }}
              />
            ) : (
              <Card title="Asset details">
                <p className="text-sm text-ink-2">Select a node in the graph or below to see its versions, failed rules, schema changes and dependencies.</p>
                <ul className="mt-3 space-y-1 text-sm">
                  {graph.data.nodes.map((n) => (
                    <li key={n.id}>
                      <button type="button" className="text-accent-strong hover:underline" onClick={() => setSelected(n.id)}>
                        {n.name}
                      </button>{' '}
                      <span className="text-xs text-ink-3">{n.kind}</span>
                    </li>
                  ))}
                </ul>
              </Card>
            )}
          </div>
          <ManageLineage graph={graph.data} onChanged={() => { graph.reload(); setImpact(null); }} />
        </div>
      )}
    </>
  );
}

function GraphView({ graph, selected, impact, onSelect }: { graph: LineageGraph; selected: string | null; impact: ImpactResponse | null; onSelect: (id: string) => void }) {
  const impactById = useMemo(() => new Map((impact?.impacted ?? []).map((i) => [i.id, i])), [impact]);
  const pathEdges = useMemo(() => {
    const set = new Set<string>();
    for (const item of impact?.impacted ?? []) {
      for (let i = 0; i < item.path_ids.length - 1; i += 1) set.add(`${item.path_ids[i]}->${item.path_ids[i + 1]}`);
    }
    return set;
  }, [impact]);

  const nodes: Node<AssetNodeData>[] = graph.nodes.map((asset) => ({
    id: asset.id,
    type: 'asset',
    position: asset.position,
    data: { asset, impact: impactById.get(asset.id)?.classification, origin: impact?.origin.id === asset.id, selected: selected === asset.id },
  }));
  const edges: Edge[] = graph.edges.map((edge) => {
    const onPath = pathEdges.has(`${edge.source}->${edge.target}`);
    return {
      id: edge.id,
      source: edge.source,
      target: edge.target,
      label: edge.description || undefined,
      animated: onPath,
      style: { stroke: onPath ? '#ec835a' : '#c3c2b7', strokeWidth: onPath ? 2.5 : 1.5 },
      labelStyle: { fontSize: 10, fill: '#6b7280' },
    };
  });
  return (
    <div className="h-[520px] w-full rounded-lg border border-line bg-canvas" aria-label="Lineage graph">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodeClick={(_, node) => onSelect(node.id)}
        fitView
        fitViewOptions={{ padding: 0.15 }}
        nodesConnectable={false}
        proOptions={{ hideAttribution: true }}
        minZoom={0.3}
      >
        <Background gap={20} color="#e1e0d9" />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}

function Legend() {
  return (
    <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-ink-2">
      <span>Impact:</span>
      {(Object.keys(IMPACT_LABELS) as ImpactClass[]).filter((k) => k !== 'no_known_impact').map((k) => (
        <ImpactBadge key={k} value={k} />
      ))}
      <span className="ml-2">Highlighted edges show how impact propagates.</span>
    </div>
  );
}

function AssetPanel({ assetId, graph, onSelect, onImpact, impact, onChanged }: {
  assetId: string;
  graph: LineageGraph;
  onSelect: (id: string) => void;
  onImpact: (impact: ImpactResponse) => void;
  impact: ImpactResponse | null;
  onChanged: () => void;
}) {
  const details = useAsync(() => api.asset(assetId), [assetId]);
  const [busy, setBusy] = useState<string>();
  const [error, setError] = useState<unknown>();
  const byName = new Map(graph.nodes.map((n) => [n.name, n.id]));

  async function act(key: string, fn: () => Promise<void>) {
    setBusy(key);
    setError(undefined);
    try {
      await fn();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(undefined);
    }
  }

  if (details.error) return <ErrorState error={details.error} onRetry={details.reload} />;
  if (!details.data) return <Loading />;
  const a = details.data;
  const h = a.health;
  const incoming = graph.edges.filter((e) => e.target === a.id);
  const outgoing = graph.edges.filter((e) => e.source === a.id);
  const name = (id: string) => graph.nodes.find((n) => n.id === id)?.name ?? id;

  return (
    <>
      <Card
        title={a.name}
        actions={
          <Button variant="primary" busy={busy === 'impact'} onClick={() => act('impact', async () => onImpact(await api.impact(a.id)))}>
            Trace downstream impact
          </Button>
        }
      >
        {error !== undefined && <div className="mb-3"><ErrorState error={error} /></div>}
        <KeyValue
          items={[
            ['Kind', KIND_LABEL[a.kind] ?? a.kind],
            ['Owner', a.owner || '—'],
            ['Health', <HealthBadge key="h" state={h.state} />],
            ['Description', a.description || '—'],
          ]}
        />
        {a.dataset_id && (
          <p className="mt-2 text-sm">
            <Link className="text-accent-strong hover:underline" to={`/datasets?dataset=${a.dataset_id}`}>
              Open in dataset explorer
            </Link>
            {' · '}
            <Link className="text-accent-strong hover:underline" to={`/drift?dataset=${a.dataset_id}`}>
              View drift
            </Link>
          </p>
        )}
        {h.failed_rules && h.failed_rules.length > 0 && (
          <div className="mt-4">
            <p className="text-xs font-semibold uppercase text-ink-3">Failed rules (v{h.version_number})</p>
            <ul className="mt-1 space-y-1 text-sm">
              {h.failed_rules.map((r) => (
                <li key={r.rule_name} className="flex gap-2">
                  <SeverityBadge severity={r.severity} /> <span>{r.rule_name}: {r.message}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
        {h.schema_changes && h.schema_changes.length > 0 && (
          <div className="mt-4">
            <p className="text-xs font-semibold uppercase text-ink-3">Schema changes</p>
            <ul className="mt-1 space-y-1 text-sm">
              {h.schema_changes.map((c, i) => (
                <li key={i}>
                  <SeverityBadge severity={c.severity} /> {c.change_type.replace(/_/g, ' ')} <code className="text-xs">{c.column}</code>
                </li>
              ))}
            </ul>
          </div>
        )}
        {a.versions.length > 0 && (
          <div className="mt-4">
            <p className="text-xs font-semibold uppercase text-ink-3">Versions</p>
            <ul className="tabular mt-1 text-sm">
              {a.versions.map((v) => (
                <li key={v.id}>
                  v{v.version_number} · {v.row_count.toLocaleString()} rows · {v.status}
                </li>
              ))}
            </ul>
          </div>
        )}
        <DependencyList title="Upstream" items={a.upstream} onSelect={(n) => { const id = byName.get(n); if (id) onSelect(id); }} />
        <DependencyList title="Downstream" items={a.downstream} onSelect={(n) => { const id = byName.get(n); if (id) onSelect(id); }} />
        <div className="mt-4 border-t border-line pt-3">
          <p className="text-xs font-semibold uppercase text-ink-3">Declared edges</p>
          <ul className="mt-1 space-y-1 text-sm">
            {[...incoming, ...outgoing].map((e) => (
              <li key={e.id} className="flex items-center justify-between gap-2">
                <span>
                  {name(e.source)} → {name(e.target)}
                </span>
                <Button variant="ghost" className="px-2 py-0.5 text-xs" busy={busy === e.id} onClick={() => act(e.id, async () => { await api.deleteEdge(e.id); onChanged(); })}>
                  Remove
                </Button>
              </li>
            ))}
            {incoming.length + outgoing.length === 0 && <li className="text-ink-3">Disconnected: no declared dependencies.</li>}
          </ul>
          {!a.dataset_id && (
            <Button variant="danger" className="mt-3" busy={busy === 'del'} onClick={() => window.confirm(`Delete asset "${a.name}" and its edges?`) && act('del', async () => { await api.deleteAsset(a.id); onChanged(); })}>
              Delete asset
            </Button>
          )}
        </div>
      </Card>
      {impact && <ImpactPanel impact={impact} onActed={async () => onImpact(await api.impact(a.id))} />}
    </>
  );
}

function DependencyList({ title, items, onSelect }: { title: string; items: { id: string; name: string; distance: number; path: string[] }[]; onSelect: (name: string) => void }) {
  return (
    <div className="mt-4">
      <p className="text-xs font-semibold uppercase text-ink-3">
        {title} ({items.length})
      </p>
      <ul className="mt-1 space-y-1 text-sm">
        {items.map((d) => (
          <li key={d.id}>
            <button type="button" className="text-accent-strong hover:underline" onClick={() => onSelect(d.name)}>
              {d.name}
            </button>{' '}
            <span className="text-xs text-ink-3">{d.distance === 1 ? 'direct' : `${d.distance} hops`}</span>
          </li>
        ))}
        {items.length === 0 && <li className="text-ink-3">None</li>}
      </ul>
    </div>
  );
}

function ImpactPanel({ impact, onActed }: { impact: ImpactResponse; onActed: () => Promise<void> }) {
  const [busy, setBusy] = useState<number>();
  const [error, setError] = useState<unknown>();
  async function runAction(rec: ImpactResponse['recommendations'][number]) {
    if (!rec.action) return;
    if (!window.confirm('Quarantine this version? The data is kept and the previous active version becomes current.')) return;
    setBusy(rec.priority);
    setError(undefined);
    try {
      await api.quarantine(rec.action.dataset_id, rec.action.version_id, `Quarantined from impact analysis: ${rec.title}`);
      await onActed();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(undefined);
    }
  }
  return (
    <Card title="Downstream impact">
      <p className="text-sm text-ink">{impact.assessment}</p>
      <div className="mt-3 flex flex-wrap gap-2">
        {(Object.keys(impact.counts) as ImpactClass[]).filter((k) => impact.counts[k] > 0).map((k) => (
          <span key={k} className="flex items-center gap-1 text-xs">
            <ImpactBadge value={k} /> {impact.counts[k]}
          </span>
        ))}
      </div>
      <ul className="mt-3 divide-y divide-line">
        {impact.impacted.map((i) => (
          <li key={i.id} className="py-2 text-sm">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-medium">{i.name}</span>
              <ImpactBadge value={i.classification} />
              <span className="text-xs text-ink-3">{i.distance === 1 ? 'direct' : `transitive (${i.distance} hops)`}</span>
            </div>
            <p className="text-xs text-ink-2">{i.path.join(' → ')}</p>
            {i.evidence?.slice(1).map((e) => (
              <p key={e} className="text-xs text-ink-3">• {e}</p>
            ))}
          </li>
        ))}
        {impact.impacted.length === 0 && <li className="py-2 text-sm text-ink-3">No downstream assets are declared.</li>}
      </ul>
      {impact.recommendations.length > 0 && (
        <div className="mt-4 border-t border-line pt-3">
          <p className="text-xs font-semibold uppercase text-ink-3">Recommended actions</p>
          {error !== undefined && <ErrorState error={error} />}
          <ol className="mt-2 space-y-3 text-sm">
            {impact.recommendations.map((rec) => (
              <li key={rec.priority}>
                <div className="flex flex-wrap items-center gap-2">
                  <Badge tone={rec.kind === 'contain' ? 'critical' : rec.kind === 'recover' ? 'good' : 'info'}>{rec.kind}</Badge>
                  <span className="font-medium">{rec.title}</span>
                </div>
                <p className="mt-1 text-ink-2">{rec.rationale}</p>
                {rec.evidence.length > 0 && <p className="text-xs text-ink-3">Evidence: {rec.evidence.join('; ')}</p>}
                {rec.action?.type === 'quarantine_version' && (
                  <Button className="mt-1 px-2 py-1 text-xs" busy={busy === rec.priority} onClick={() => runAction(rec)}>
                    Quarantine version
                  </Button>
                )}
              </li>
            ))}
          </ol>
        </div>
      )}
    </Card>
  );
}

function ManageLineage({ graph, onChanged }: { graph: LineageGraph; onChanged: () => void }) {
  const [assetName, setAssetName] = useState('');
  const [kind, setKind] = useState('transformation');
  const [owner, setOwner] = useState('');
  const [source, setSource] = useState('');
  const [target, setTarget] = useState('');
  const [busy, setBusy] = useState<string>();
  const [error, setError] = useState<unknown>();

  async function run(key: string, fn: () => Promise<unknown>) {
    setBusy(key);
    setError(undefined);
    try {
      await fn();
      onChanged();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(undefined);
    }
  }

  return (
    <Card title="Declare assets and dependencies">
      <div className="grid gap-6 md:grid-cols-2">
        <form
          aria-label="Add asset"
          className="space-y-3"
          onSubmit={(e: FormEvent) => {
            e.preventDefault();
            void run('asset', async () => {
              await api.createAsset({ name: assetName, kind, owner });
              setAssetName('');
              setOwner('');
            });
          }}
        >
          <Field label="Asset name" htmlFor="asset-name">
            <input id="asset-name" required maxLength={120} className={inputClass} value={assetName} onChange={(e) => setAssetName(e.target.value)} />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Kind" htmlFor="asset-kind">
              <select id="asset-kind" className={inputClass} value={kind} onChange={(e) => setKind(e.target.value)}>
                <option value="source">Source</option>
                <option value="transformation">Transformation</option>
                <option value="report">Report</option>
                <option value="model">Model</option>
              </select>
            </Field>
            <Field label="Owner" htmlFor="asset-owner">
              <input id="asset-owner" maxLength={120} className={inputClass} value={owner} onChange={(e) => setOwner(e.target.value)} />
            </Field>
          </div>
          <Button type="submit" busy={busy === 'asset'}>
            Add asset
          </Button>
        </form>
        <form
          aria-label="Add dependency"
          className="space-y-3"
          onSubmit={(e: FormEvent) => {
            e.preventDefault();
            void run('edge', () => api.createEdge({ source_id: source, target_id: target }));
          }}
        >
          <Field label="Upstream (feeds)" htmlFor="edge-source">
            <select id="edge-source" required className={inputClass} value={source} onChange={(e) => setSource(e.target.value)}>
              <option value="">Choose…</option>
              {graph.nodes.map((n) => (
                <option key={n.id} value={n.id}>
                  {n.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Downstream (reads)" htmlFor="edge-target" hint="Edges that would create a cycle are rejected with the cycle path.">
            <select id="edge-target" required className={inputClass} value={target} onChange={(e) => setTarget(e.target.value)}>
              <option value="">Choose…</option>
              {graph.nodes.map((n) => (
                <option key={n.id} value={n.id}>
                  {n.name}
                </option>
              ))}
            </select>
          </Field>
          <Button type="submit" busy={busy === 'edge'}>
            Add dependency
          </Button>
        </form>
      </div>
      {error !== undefined && <div className="mt-4"><ErrorState error={error} /></div>}
    </Card>
  );
}
