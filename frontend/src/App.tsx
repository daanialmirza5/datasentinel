import { Route, Routes } from 'react-router-dom';
import { Layout } from './components/Layout';
import { EmptyState } from './components/ui';
import { DashboardPage } from './pages/DashboardPage';
import { DatasetsPage } from './pages/DatasetsPage';
import { DriftPage } from './pages/DriftPage';
import { LabPage } from './pages/LabPage';
import { LineagePage } from './pages/LineagePage';
import { ReportsPage } from './pages/ReportsPage';
import { RulesPage } from './pages/RulesPage';
import { SettingsPage } from './pages/SettingsPage';

export function App() {
  return (
    <Layout>
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
    </Layout>
  );
}
