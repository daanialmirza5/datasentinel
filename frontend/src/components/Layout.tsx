import { useState, type ReactNode } from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import { api } from '../api/client';
import { useAsync } from '../hooks/useAsync';
import { cx } from '../lib/format';

const NAV = [
  { to: '/', label: 'Dashboard', icon: 'M3 12h7V3H3zm11 9h7v-9h-7zM3 21h7v-6H3zm11-12h7V3h-7z' },
  { to: '/datasets', label: 'Datasets', icon: 'M4 6c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3zm0 0v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3' },
  { to: '/rules', label: 'Quality rules', icon: 'M9 11l3 3 8-8M20 12v7a2 2 0 01-2 2H6a2 2 0 01-2-2V5a2 2 0 012-2h9' },
  { to: '/drift', label: 'Drift monitoring', icon: 'M3 17l6-6 4 4 8-8M14 7h7v7' },
  { to: '/lineage', label: 'Lineage', icon: 'M6 3v6m0 6v6M6 9a3 3 0 100 6 3 3 0 000-6zm12-3a3 3 0 100 6 3 3 0 000-6zM9 12h6' },
  { to: '/lab', label: 'Fault lab', icon: 'M9 3h6M10 3v6L4 19a1.5 1.5 0 001.3 2h13.4A1.5 1.5 0 0020 19l-6-10V3' },
  { to: '/reports', label: 'Reports', icon: 'M7 3h7l5 5v13H7zM14 3v5h5M10 13h6M10 17h6' },
  { to: '/settings', label: 'Settings & docs', icon: 'M12 15a3 3 0 100-6 3 3 0 000 6zm7.4-3a7.4 7.4 0 00-.1-1.3l2-1.6-2-3.4-2.4 1a7.6 7.6 0 00-2.2-1.3L14.3 3h-4l-.4 2.4a7.6 7.6 0 00-2.2 1.3l-2.4-1-2 3.4 2 1.6a7.4 7.4 0 000 2.6l-2 1.6 2 3.4 2.4-1a7.6 7.6 0 002.2 1.3l.4 2.4h4l.4-2.4a7.6 7.6 0 002.2-1.3l2.4 1 2-3.4-2-1.6c.1-.4.1-.9.1-1.3z' },
];

function Icon({ path }: { path: string }) {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" className="h-4 w-4 shrink-0" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round">
      <path d={path} />
    </svg>
  );
}

export function Logo() {
  return (
    <span className="flex items-center gap-2 font-semibold text-ink">
      <svg aria-hidden="true" viewBox="0 0 32 32" className="h-7 w-7">
        <rect width="32" height="32" rx="8" fill="#1c5cab" />
        <path d="M16 6l8 3.5v6.2c0 5-3.4 8.7-8 10.3-4.6-1.6-8-5.3-8-10.3V9.5z" fill="#fff" opacity="0.95" />
        <path d="M12 16.5l3 3 5.5-6" fill="none" stroke="#1c5cab" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      DataSentinel
    </span>
  );
}

export function Layout({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const location = useLocation();
  const [lastPath, setLastPath] = useState(location.pathname);
  const settings = useAsync(() => api.settings(), []);
  if (lastPath !== location.pathname) {
    setLastPath(location.pathname);
    setOpen(false);
  }
  return (
    <div className="min-h-full lg:flex">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-surface focus:px-3 focus:py-2">
        Skip to content
      </a>
      <header className="flex items-center justify-between border-b border-line bg-surface px-4 py-3 lg:hidden">
        <Logo />
        <button type="button" className="rounded-lg border border-line px-3 py-1.5 text-sm" aria-expanded={open} aria-controls="sidebar" onClick={() => setOpen((v) => !v)}>
          Menu
        </button>
      </header>
      <aside id="sidebar" className={cx('border-r border-line bg-surface lg:sticky lg:top-0 lg:block lg:h-screen lg:w-60 lg:shrink-0', open ? 'block' : 'hidden')}>
        <div className="hidden px-5 py-5 lg:block">
          <Logo />
          <p className="mt-1 text-xs text-ink-3">Explainable data observability</p>
        </div>
        <nav aria-label="Main" className="flex flex-col gap-0.5 px-3 pb-4 lg:pb-0">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === '/'}
              className={({ isActive }) =>
                cx(
                  'flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium focus-visible:outline-2 focus-visible:outline-accent',
                  isActive ? 'bg-accent/10 text-accent-strong' : 'text-ink-2 hover:bg-canvas hover:text-ink',
                )
              }
            >
              <Icon path={item.icon} />
              {item.label}
            </NavLink>
          ))}
        </nav>
      </aside>
      <main id="main" className="min-w-0 flex-1 px-4 py-6 sm:px-6 lg:px-8">
        <div className="mx-auto max-w-7xl">
          {settings.data?.demo_mode && (
            <p role="note" className="mb-4 rounded-lg border border-accent/30 bg-accent/5 px-4 py-2 text-sm text-accent-strong">
              Read-only public demo with synthetic data: uploads and edits are disabled; the fault lab and reports work. Run DataSentinel locally to use your own data.
            </p>
          )}
          {children}
        </div>
      </main>
    </div>
  );
}
