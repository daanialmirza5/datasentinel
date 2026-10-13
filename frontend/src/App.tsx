import { lazy, Suspense } from 'react';
import { Route, Routes } from 'react-router-dom';
import { Layout } from './components/Layout';
import { EmptyState, Loading } from './components/ui';

// Route-level code splitting: React Flow and Recharts are only downloaded by the pages that use them.
const DashboardPage = lazy(() => import('./pages/DashboardPage').then((m) => ({ default: m.DashboardPage })));
const DatasetsPage = lazy(() => import('./pages/DatasetsPage').then((m) => ({ default: m.DatasetsPage })));
const RulesPage = lazy(() => import('./pages/RulesPage').then((m) => ({ default: m.RulesPage })));
const DriftPage = lazy(() => import('./pages/DriftPage').then((m) => ({ default: m.DriftPage })));
const LineagePage = lazy(() => import('./pages/LineagePage').then((m) => ({ default: m.LineagePage })));
const LabPage = lazy(() => import('./pages/LabPage').then((m) => ({ default: m.LabPage })));
const ReportsPage = lazy(() => import('./pages/ReportsPage').then((m) => ({ default: m.ReportsPage })));
const SettingsPage = lazy(() => import('./pages/SettingsPage').then((m) => ({ default: m.SettingsPage })));

export function App() {
  return (
    <Layout>
      <Suspense fallback={<Loading />}>
        <Routes>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/datasets" element={<DatasetsPage />} />
          <Route path="/rules" element={<RulesPage />} />
          <Route path="/drift" element={<DriftPage />} />
          <Route path="/lineage" element={<LineagePage />} />
          <Route path="/lab" element={<LabPage />} />
          <Route path="/reports" element={<ReportsPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="*" element={<EmptyState title="Page not found">The page you requested does not exist.</EmptyState>} />
        </Routes>
      </Suspense>
    </Layout>
  );
}
