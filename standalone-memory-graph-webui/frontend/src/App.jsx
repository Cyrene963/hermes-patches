import React, { Suspense, useState, useEffect, useCallback } from 'react';
import { BrowserRouter, Routes, Route, NavLink, Navigate, useLocation } from 'react-router-dom';
import { ShieldCheck, Database, LayoutGrid, Sparkles, AlertCircle, Layers, Settings, LogOut, Loader2 } from 'lucide-react';
import clsx from 'clsx';

const ReviewPage = React.lazy(() => import('./features/review/ReviewPage'));
const MemoryBrowser = React.lazy(() => import('./features/memory/MemoryBrowser'));
const MaintenancePage = React.lazy(() => import('./features/maintenance/MaintenancePage'));
const SettingsDrawer = React.lazy(() => import('./features/settings/SettingsDrawer'));
import LoginForm from './components/LoginForm';
import { AUTH_ERROR_EVENT, getNamespaces, getMe, logout } from './lib/api';
import { I18nProvider, LanguageToggle, useI18n } from './lib/i18n';

// ---------------------------------------------------------------------------
// NamespaceSelector
// ---------------------------------------------------------------------------
function NamespaceSelector({ user }) {
  const ownNamespace = user?.namespace || '';
  const [knownNamespaces, setKnownNamespaces] = useState([]);
  const [selected, setSelected] = useState(
    () => localStorage.getItem('selected_namespace') ?? ''
  );
  const [inputValue, setInputValue] = useState(
    () => localStorage.getItem('selected_namespace') ?? ''
  );
  const [showInput, setShowInput] = useState(false);

  useEffect(() => {
    getNamespaces()
      .then(nsList => setKnownNamespaces(nsList.filter(ns => ns !== '')))
      .catch(() => setKnownNamespaces([]));
  }, []);

  const applyNamespace = (ns) => {
    const trimmed = ns.trim();
    setSelected(trimmed);
    setInputValue(trimmed);
    if (trimmed) {
      localStorage.setItem('selected_namespace', trimmed);
    } else {
      localStorage.removeItem('selected_namespace');
    }
    window.location.reload();
  };

  const handleSelectChange = (e) => {
    const val = e.target.value;
    if (val === '__custom__') {
      setShowInput(true);
      return;
    }
    applyNamespace(val);
  };

  const handleInputKeyDown = (e) => {
    if (e.key === 'Enter') applyNamespace(inputValue);
    if (e.key === 'Escape') setShowInput(false);
  };

  const activeLabel = selected
    ? (selected === ownNamespace ? '我的私有记忆' : selected)
    : '共享公开区';

  return (
    <div className="flex items-center gap-2 text-sm">
      <Layers size={14} className="text-slate-400 flex-shrink-0" />
      {showInput ? (
        <input
          autoFocus
          type="text"
          value={inputValue}
          onChange={e => setInputValue(e.target.value)}
          onKeyDown={handleInputKeyDown}
          onBlur={() => setShowInput(false)}
          placeholder="namespace (Enter to apply)"
          className="bg-slate-800 border border-indigo-500 text-slate-200 rounded px-2 py-1 text-xs w-40 focus:outline-none"
        />
      ) : (
        <select
          value={selected}
          onChange={handleSelectChange}
          className="bg-slate-800 border border-slate-700 text-slate-200 rounded px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-indigo-500"
          title={`Current namespace: ${activeLabel}`}
        >
          <option value="">共享公开区</option>
          {ownNamespace && (
            <option value={ownNamespace}>我的私有记忆</option>
          )}
          {knownNamespaces.filter(ns => ns !== ownNamespace).map(ns => (
            <option key={ns} value={ns}>{ns}</option>
          ))}
          {selected && !knownNamespaces.includes(selected) && (
            <option key={selected} value={selected}>{selected}</option>
          )}
          <option value="__custom__">+ enter custom…</option>
        </select>
      )}
    </div>
  );
}

function PageFallback() {
  return (
    <div className="flex h-full items-center justify-center bg-slate-950 text-slate-300" role="status" aria-live="polite">
      <div className="flex items-center gap-3 rounded-2xl border border-white/10 bg-white/[0.04] px-5 py-4 shadow-2xl shadow-indigo-950/20">
        <Loader2 className="h-5 w-5 animate-spin text-indigo-300" />
        <span className="text-sm font-medium">Loading workspace…</span>
      </div>
    </div>
  );
}

function Layout({ user, onLogout }) {
  const location = useLocation();
  const isReviewPage = location.pathname.startsWith('/review');
  const { t } = useI18n();

  return (
    <div className="flex h-dvh flex-col bg-slate-950 text-slate-200">
      {/* Top Navigation Bar */}
      <header className="min-h-12 border-b border-slate-800 bg-slate-900/95 backdrop-blur flex flex-wrap items-center px-3 sm:px-4 gap-2 sm:gap-4 flex-shrink-0 z-10">
        <div className="font-bold text-slate-100 flex items-center gap-2 mr-4">
          <LayoutGrid className="w-5 h-5 text-indigo-500" />
          <span>{t('nav.memory_graph')}</span>
        </div>

        <nav className="flex h-12 items-center gap-1 overflow-x-auto" aria-label="Primary navigation">
          <NavLink
            to="/review"
            className={({ isActive }) => clsx(
              "h-full flex items-center gap-2 px-4 text-sm font-medium border-b-2 transition-colors",
              isActive ? "border-indigo-500 text-indigo-400 bg-slate-800/50" : "border-transparent text-slate-400 hover:text-slate-200 hover:bg-slate-800/30"
            )}
          >
            <ShieldCheck size={16} />
            {t('nav.review')}
          </NavLink>

          <NavLink
            to="/memory"
            className={({ isActive }) => clsx(
              "h-full flex items-center gap-2 px-4 text-sm font-medium border-b-2 transition-colors",
              isActive ? "border-emerald-500 text-emerald-400 bg-slate-800/50" : "border-transparent text-slate-400 hover:text-slate-200 hover:bg-slate-800/30"
            )}
          >
            <Database size={16} />
            {t('nav.memory')}
          </NavLink>

          <NavLink
            to="/maintenance"
            className={({ isActive }) => clsx(
              "h-full flex items-center gap-2 px-4 text-sm font-medium border-b-2 transition-colors",
              isActive ? "border-amber-500 text-amber-400 bg-slate-800/50" : "border-transparent text-slate-400 hover:text-slate-200 hover:bg-slate-800/30"
            )}
          >
            <Sparkles size={16} />
            {t('nav.maintenance')}
          </NavLink>
        </nav>

        <div className="ml-auto flex min-h-12 flex-wrap items-center justify-end gap-2 sm:gap-3">
          {!isReviewPage && <NamespaceSelector user={user} />}
          <LanguageToggle />
          <button
            onClick={() => window.dispatchEvent(new CustomEvent('open-settings'))}
            className="flex items-center gap-2 px-3 py-1.5 rounded-md text-sm font-medium transition-colors text-slate-400 hover:text-slate-200 hover:bg-slate-800/50"
          >
            <Settings size={16} />
            {t('nav.settings')}
          </button>
          {user && (
            <button
              onClick={onLogout}
              className="flex items-center gap-2 px-3 py-1.5 rounded-md text-sm font-medium transition-colors text-slate-400 hover:text-slate-200 hover:bg-slate-800/50"
              title={`Signed in as ${user.display_name || user.username}`}
            >
              <LogOut size={16} />
              {user.display_name || user.username}
            </button>
          )}
        </div>
      </header>
      <main className="flex-1 min-h-0 overflow-hidden">
        <Suspense fallback={<PageFallback />}>
          <Routes>
            <Route path="/" element={<Navigate to="/memory" replace />} />
            <Route path="/review" element={<ReviewPage />} />
            <Route path="/memory" element={<MemoryBrowser />} />
            <Route path="/maintenance" element={<MaintenancePage />} />
          </Routes>
        </Suspense>
      </main>

      <Suspense fallback={null}>
        <SettingsDrawer />
      </Suspense>
    </div>
  );
}

function App() {
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [isCheckingAuth, setIsCheckingAuth] = useState(true);
  const [backendError, setBackendError] = useState(false);
  const [user, setUser] = useState(null);

  return (
    <I18nProvider>
      <AppInner />
    </I18nProvider>
  );
}

function AppInner() {
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [isCheckingAuth, setIsCheckingAuth] = useState(true);
  const [backendError, setBackendError] = useState(false);
  const [user, setUser] = useState(null);
  const { t } = useI18n();

  const handleAuthError = useCallback(() => {
    setIsAuthenticated(false);
    setUser(null);
  }, []);

  const handleAuthenticated = useCallback(() => {
    setIsAuthenticated(true);
    setBackendError(false);
    // Fetch user info
    getMe().then(data => {
      if (data.authenticated) {
        setUser(data);
      }
    }).catch(() => {});
  }, []);

  const handleLogout = useCallback(async () => {
    try {
      await logout();
    } catch {
      // ignore errors
    }
    setIsAuthenticated(false);
    setUser(null);
  }, []);

  // Check auth status on mount
  useEffect(() => {
    let mounted = true;

    const checkAuthStatus = async () => {
      try {
        const me = await getMe();
        if (mounted) {
          if (me.authenticated) {
            setIsAuthenticated(true);
            setUser(me);
          } else {
            setIsAuthenticated(false);
          }
          setBackendError(false);
          setIsCheckingAuth(false);
        }
      } catch (error) {
        if (mounted) {
          if (!error.response) {
            setBackendError(true);
          } else if (error.response.status === 401) {
            setIsAuthenticated(false);
            setBackendError(false);
          } else {
            setBackendError(false);
          }
          setIsCheckingAuth(false);
        }
      }
    };

    checkAuthStatus();

    return () => {
      mounted = false;
    };
  }, []);

  // Listen for 401 events
  useEffect(() => {
    window.addEventListener(AUTH_ERROR_EVENT, handleAuthError);
    return () => {
      window.removeEventListener(AUTH_ERROR_EVENT, handleAuthError);
    };
  }, [handleAuthError]);

  if (isCheckingAuth) {
    return (
      <div className="flex flex-col items-center justify-center h-screen bg-slate-950 text-slate-400">
        <div className="w-8 h-8 rounded-full border-2 border-indigo-500/30 border-t-indigo-500 animate-spin mb-4"></div>
        <div className="text-sm">{t('status.connecting')}</div>
      </div>
    );
  }

  if (backendError) {
    return (
      <div className="flex flex-col items-center justify-center h-screen bg-slate-950 text-slate-400">
        <div className="w-12 h-12 rounded-xl bg-red-500/10 border border-red-500/20 flex items-center justify-center mb-4">
          <AlertCircle className="w-6 h-6 text-red-500" />
        </div>
        <div className="text-lg font-bold text-slate-100 mb-1">{t('status.cannot_connect')}</div>
        <div className="text-sm text-slate-500 max-w-md text-center mt-2">
          <p>{t('status.check_port')}</p>
        </div>
        <button 
          onClick={() => window.location.reload()}
          className="mt-6 px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-sm transition-colors"
        >
          Retry
        </button>
      </div>
    );
  }

  if (!isAuthenticated) {
    return <LoginForm onAuthenticated={handleAuthenticated} />;
  }

  return (
    <BrowserRouter>
      <Layout user={user} onLogout={handleLogout} />
    </BrowserRouter>
  );
}

export default App;
