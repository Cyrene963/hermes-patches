import React, { useState, useEffect } from 'react';
import { CheckCircle, XCircle, RefreshCw, TestTube, AlertTriangle } from 'lucide-react';
import { testDatabase } from '../../lib/api';

export default function DatabaseSection({ settings, dbStatus, onRefreshStatus, onSave }) {
  const currentUrl = settings?.database_url || '';
  const [pgUrl, setPgUrl] = useState('');
  const [testResult, setTestResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    if (!currentUrl) return;
    setPgUrl(currentUrl);
    setDirty(false);
  }, [currentUrl]);

  const handleTestOnly = async () => {
    const url = pgUrl.trim();
    if (!url) return;
    setBusy(true);
    setTestResult(null);
    try {
      const result = await testDatabase(url);
      setTestResult(result);
    } catch (e) {
      setTestResult({ success: false, message: e.response?.data?.detail || e.message });
    } finally {
      setBusy(false);
    }
  };

  const handleTestAndSave = async () => {
    const url = pgUrl.trim();
    if (!url) return;
    setBusy(true);
    setTestResult(null);
    try {
      const result = await testDatabase(url);
      if (result.success) {
        await onSave({ database_url: url });
        setDirty(false);
        setTestResult({ success: true, message: 'Connected & saved. Restart server to apply.' });
        onRefreshStatus();
      } else {
        setTestResult(result);
      }
    } catch (e) {
      setTestResult({ success: false, message: e.response?.data?.detail || e.message });
    } finally {
      setBusy(false);
    }
  };

  const hasInput = pgUrl.trim().length > 0;

  return (
    <div className="space-y-5 pt-4">
      {dbStatus && (
        <div className="bg-slate-900 border border-slate-700/50 shadow-sm rounded-lg p-3 text-sm space-y-1.5">
          <div className="flex items-center justify-between">
            <span className="text-slate-400">Type</span>
            <span className="text-slate-200 font-medium">{dbStatus.type === 'postgresql' ? 'PostgreSQL' : dbStatus.type}</span>
          </div>
          {dbStatus.url_masked && (
            <div className="flex items-center justify-between gap-4">
              <span className="text-slate-400 flex-shrink-0">URL</span>
              <span className="text-slate-300 font-mono text-xs truncate max-w-[380px]" title={dbStatus.url_masked}>{dbStatus.url_masked}</span>
            </div>
          )}
          <div className="flex items-center justify-end gap-3 pt-1">
            <button onClick={onRefreshStatus} className="text-xs text-indigo-400 hover:text-indigo-300 flex items-center gap-1">
              <RefreshCw size={11} /> Refresh
            </button>
          </div>
        </div>
      )}

      <div className="rounded-lg border border-amber-500/20 bg-amber-500/5 p-3 flex gap-2 text-xs text-amber-200">
        <AlertTriangle size={15} className="flex-shrink-0 mt-0.5" />
        <div>
          This deployment currently supports PostgreSQL URLs only. SQLite database creation/open-folder controls were removed because the backend does not implement those actions.
        </div>
      </div>

      <div className="space-y-2">
        <label className="block text-xs font-medium text-slate-400 uppercase tracking-wider">PostgreSQL Connection URL</label>
        <input
          type="text"
          value={pgUrl}
          onChange={e => { setPgUrl(e.target.value); setDirty(true); setTestResult(null); }}
          placeholder="postgresql+asyncpg://user:pass@host:5432/dbname"
          className="w-full bg-slate-950 border border-slate-700 text-slate-200 rounded-lg px-3 py-2 text-sm font-mono placeholder:text-slate-600 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 shadow-inner"
        />
        {hasInput && (
          <button
            onClick={dirty ? handleTestAndSave : handleTestOnly}
            disabled={busy}
            className="mt-1 px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 text-white rounded-lg text-sm flex items-center gap-1.5 transition-colors"
          >
            <TestTube size={14} />
            {busy ? 'Testing...' : (dirty ? 'Test & Save' : 'Test Connection')}
          </button>
        )}
        {testResult && (
          <div className={`flex items-center gap-2 text-sm ${testResult.success ? 'text-emerald-400' : 'text-red-400'}`}>
            {testResult.success ? <CheckCircle size={14} /> : <XCircle size={14} />}
            {testResult.message}
          </div>
        )}
      </div>
    </div>
  );
}
