import React, { useState, useEffect } from 'react';
import { Save, AlertTriangle, RefreshCw, Copy, Eye, EyeOff } from 'lucide-react';

export default function AdvancedSection({ settings, lockedFields = [], onSave }) {
  const isLocked = (field) => lockedFields.includes(field);
  const [host, setHost] = useState('127.0.0.1');
  const [token, setToken] = useState('');
  const [readonlyMcp, setReadonlyMcp] = useState(false);
  const [showToken, setShowToken] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (settings?.host != null) setHost(settings.host);
    if (settings?.api_token != null) setToken(settings.api_token);
    if (settings?.public_readonly_mcp != null) setReadonlyMcp(settings.public_readonly_mcp);
  }, [settings?.host, settings?.api_token, settings?.public_readonly_mcp]);

  const handleSave = async () => {
    setSaving(true);
    try {
      const updates = { public_readonly_mcp: readonlyMcp };
      if (!isLocked('host')) updates.host = host.trim();
      if (token.trim()) updates.api_token = token.trim();
      await onSave(updates);
      setDirty(false);
    } catch (e) {
      alert('Failed: ' + (e.response?.data?.detail || e.message));
    } finally {
      setSaving(false);
    }
  };

  const isRemote = host.trim() !== '127.0.0.1' && host.trim() !== 'localhost' && host.trim() !== '::1';

  return (
    <div className="space-y-5 pt-4">
      <div className="space-y-3">
        <div className="space-y-2">
          <label className="block text-xs font-medium text-slate-400 uppercase tracking-wider">Listen Host</label>
          <input
            type="text"
            value={host}
            onChange={e => { setHost(e.target.value); setDirty(true); }}
            disabled={isLocked('host')}
            placeholder="127.0.0.1"
            className="bg-slate-950 border border-slate-700 text-slate-200 rounded-lg px-3 py-2 text-sm w-full font-mono focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 shadow-inner disabled:opacity-50 disabled:cursor-not-allowed"
          />
          {isLocked('host') ? (
            <p className="text-[11px] text-slate-500">Managed by docker-compose.yml — not editable in Docker.</p>
          ) : (
            <p className="text-[11px] text-slate-500">
              {isRemote
                ? <>LAN / remote access mode. Clients can connect from other devices.</>
                : <>Default: only this machine can connect. Change to <code className="text-slate-400">0.0.0.0</code> to allow LAN / remote access.</>
              }
            </p>
          )}
        </div>

        {isRemote && (
          <div className="space-y-2">
            <label className="block text-xs font-medium text-slate-400 uppercase tracking-wider">API Token</label>
            <div className="flex gap-1.5">
              <div className="relative flex-1">
                <input
                  type={showToken ? 'text' : 'password'}
                  value={token}
                  onChange={e => { setToken(e.target.value); setDirty(true); }}
                  placeholder={settings?.api_token ? '(already set)' : 'Not set (required)'}
                  className="bg-slate-950 border border-slate-700 text-slate-200 rounded-lg px-3 py-2 pr-9 text-sm w-full font-mono focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 shadow-inner"
                />
                {token && (
                  <button
                    type="button"
                    onClick={() => setShowToken(!showToken)}
                    className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300 transition-colors"
                  >
                    {showToken ? <EyeOff size={14} /> : <Eye size={14} />}
                  </button>
                )}
              </div>
              <button
                type="button"
                onClick={() => {
                  const arr = new Uint8Array(32);
                  crypto.getRandomValues(arr);
                  const generated = Array.from(arr, b => b.toString(16).padStart(2, '0')).join('');
                  setToken(generated);
                  setDirty(true);
                }}
                className="px-2.5 py-2 bg-slate-700 hover:bg-slate-600 text-slate-200 rounded-lg text-xs flex items-center gap-1.5 transition-colors flex-shrink-0"
                title="Generate random token"
              >
                <RefreshCw size={12} /> Generate
              </button>
              {token && (
                <button
                  type="button"
                  onClick={() => { navigator.clipboard.writeText(token); }}
                  className="px-2.5 py-2 bg-slate-700 hover:bg-slate-600 text-slate-200 rounded-lg text-xs flex items-center gap-1.5 transition-colors flex-shrink-0"
                  title="Copy token"
                >
                  <Copy size={12} />
                </button>
              )}
            </div>
            <p className="text-[11px] text-slate-500">
              Clients must send <code className="text-slate-400">Authorization: Bearer &lt;token&gt;</code> to access the API.
            </p>
            {!settings?.api_token && !token.trim() && (
              <p className="text-[11px] text-amber-400 flex items-center gap-1">
                <AlertTriangle size={11} /> Required: server will refuse to start without a token in remote mode.
              </p>
            )}
          </div>
        )}
      </div>

      <div className="border-t border-slate-800/50 pt-4">
        <div className="flex items-center gap-3">
          <label className="relative inline-flex items-center cursor-pointer">
            <input
              type="checkbox"
              checked={readonlyMcp}
              onChange={e => { setReadonlyMcp(e.target.checked); setDirty(true); }}
              className="sr-only peer"
            />
            <div className="w-9 h-5 bg-slate-700 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full rtl:peer-checked:after:-translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:start-[2px] after:bg-slate-400 after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-red-600 peer-checked:after:bg-white"></div>
          </label>
          <div>
            <span className="text-sm text-slate-300 block font-medium">Read-only MCP Mode</span>
            <span className="text-xs text-slate-500 block">If enabled, MCP tools will only allow read operations. Useful for public deployments.</span>
          </div>
        </div>
      </div>

      {dirty && (
        <div className="flex items-center justify-between pt-1">
          <p className="text-xs text-amber-400 flex items-center gap-1">
            <AlertTriangle size={12} /> Saved after clicking. Restart the server process to apply.
          </p>
          <button
            onClick={handleSave}
            disabled={saving || (isRemote && !token.trim() && !settings?.api_token)}
            className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white rounded-lg text-sm font-medium flex items-center gap-2 transition-colors"
          >
            <Save size={14} />
            {saving ? 'Saving...' : 'Save'}
          </button>
        </div>
      )}
    </div>
  );
}
