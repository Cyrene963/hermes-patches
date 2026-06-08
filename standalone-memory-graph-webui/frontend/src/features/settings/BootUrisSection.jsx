import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  Plus, Trash2, GripVertical, Save, ChevronDown, ChevronUp, Layers
} from 'lucide-react';
import clsx from 'clsx';
import {
  getAllBootUris, setBootUrisForNs, deleteBootUrisForNs, getNamespaces
} from '../../lib/api';

function NamespaceBootPanel({ namespace, uris: initialUris, isDefault, onDelete, onSaved }) {
  const [uris, setUris] = useState(initialUris);
  const [newUri, setNewUri] = useState('');
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [open, setOpen] = useState(isDefault);
  const [deleting, setDeleting] = useState(false);
  const dragItem = useRef(null);
  const dragOver = useRef(null);

  useEffect(() => { setUris(initialUris); setDirty(false); }, [initialUris]);

  const handleDragStart = (idx) => { dragItem.current = idx; };
  const handleDragEnter = (idx) => { dragOver.current = idx; };
  const handleDragEnd = () => {
    if (dragItem.current === null || dragOver.current === null) return;
    if (dragItem.current === dragOver.current) {
      dragItem.current = null;
      dragOver.current = null;
      return;
    }
    const items = [...uris];
    const [removed] = items.splice(dragItem.current, 1);
    items.splice(dragOver.current, 0, removed);
    setUris(items);
    setDirty(true);
    dragItem.current = null;
    dragOver.current = null;
  };

  const handleAdd = () => {
    const trimmed = newUri.trim();
    if (!trimmed || uris.includes(trimmed)) return;
    setUris([...uris, trimmed]);
    setNewUri('');
    setDirty(true);
  };

  const handleRemove = (idx) => {
    setUris(uris.filter((_, i) => i !== idx));
    setDirty(true);
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      await setBootUrisForNs(namespace, uris);
      setDirty(false);
      onSaved?.();
    } catch (e) {
      alert('Failed to save: ' + (e.response?.data?.detail || e.message));
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!confirm(`Remove override for "${namespace}"? This namespace will fall back to the default boot URIs.`)) return;
    setDeleting(true);
    try {
      await deleteBootUrisForNs(namespace);
      onDelete?.(namespace);
    } catch (e) {
      alert('Failed to delete: ' + (e.response?.data?.detail || e.message));
    } finally {
      setDeleting(false);
    }
  };

  const label = isDefault ? 'Default (fallback)' : namespace;

  return (
    <div className="bg-slate-900/60 border border-slate-800 rounded-lg overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-2.5 px-3 py-2.5 hover:bg-slate-800/40 transition-colors"
      >
        <Layers size={14} className={clsx(isDefault ? "text-indigo-400" : "text-slate-500")} />
        <span className={clsx("text-sm font-medium", isDefault ? "text-slate-200" : "text-slate-300")}>{label}</span>
        {isDefault && <span className="text-[10px] px-1.5 py-0.5 rounded bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">fallback</span>}
        <span className="text-xs text-slate-600 ml-auto mr-2">{uris.length} URI{uris.length !== 1 ? 's' : ''}</span>
        {open ? <ChevronUp size={14} className="text-slate-500" /> : <ChevronDown size={14} className="text-slate-500" />}
      </button>

      {open && (
        <div className="px-3 pb-3 pt-1 border-t border-slate-800/50 space-y-2">
          <div className="space-y-1">
            {uris.map((uri, idx) => (
              <div
                key={uri}
                draggable
                onDragStart={() => handleDragStart(idx)}
                onDragEnter={() => handleDragEnter(idx)}
                onDragEnd={handleDragEnd}
                onDragOver={e => e.preventDefault()}
                className="flex items-center gap-2 bg-slate-950/60 border border-slate-800 hover:border-slate-700 rounded-md px-2.5 py-1.5 group cursor-grab active:cursor-grabbing transition-all"
              >
                <GripVertical size={12} className="text-slate-600 group-hover:text-slate-400 flex-shrink-0" />
                <span className="text-xs font-mono text-slate-300 flex-1 truncate">{uri}</span>
                <button
                  onClick={() => handleRemove(idx)}
                  className="opacity-0 group-hover:opacity-100 text-red-400 hover:text-red-300 transition-opacity"
                >
                  <Trash2 size={12} />
                </button>
              </div>
            ))}
            {uris.length === 0 && (
              <p className="text-xs text-slate-600 italic py-1.5">No boot URIs configured</p>
            )}
          </div>

          <div className="flex gap-1.5">
            <input
              type="text"
              value={newUri}
              onChange={e => setNewUri(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleAdd()}
              placeholder="core://agent"
              className="flex-1 bg-slate-950 border border-slate-700 text-slate-200 rounded-md px-2.5 py-1.5 text-xs font-mono placeholder:text-slate-600 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 shadow-inner"
            />
            <button
              onClick={handleAdd}
              disabled={!newUri.trim()}
              className="px-2.5 py-1.5 bg-slate-700 hover:bg-slate-600 disabled:opacity-40 text-slate-200 rounded-md text-xs flex items-center gap-1 transition-colors"
            >
              <Plus size={12} /> Add
            </button>
          </div>

          <div className="flex items-center justify-between pt-1">
            {!isDefault && (
              <button
                onClick={handleDelete}
                disabled={deleting}
                className="text-xs text-red-400/70 hover:text-red-400 flex items-center gap-1 transition-colors"
              >
                <Trash2 size={11} />
                {deleting ? 'Removing...' : 'Remove override'}
              </button>
            )}
            {isDefault && <div />}
            {dirty && (
              <button
                onClick={handleSave}
                disabled={saving}
                className="px-3 py-1.5 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white rounded-md text-xs font-medium flex items-center gap-1.5 transition-colors"
              >
                <Save size={12} />
                {saving ? 'Saving...' : 'Save'}
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export default function BootUrisSection() {
  const [allBootUris, setAllBootUris] = useState({});
  const [knownNamespaces, setKnownNamespaces] = useState([]);
  const [loading, setLoading] = useState(true);
  const [addingNs, setAddingNs] = useState(false);
  const [newNs, setNewNs] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [bootData, nsList] = await Promise.all([
        getAllBootUris(),
        getNamespaces().catch(() => []),
      ]);
      setAllBootUris(bootData || {});
      setKnownNamespaces(nsList.filter(ns => ns !== ''));
    } catch (e) {
      console.error('Failed to load boot URIs:', e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleAddNamespace = () => {
    const trimmed = newNs.trim();
    if (!trimmed || trimmed in allBootUris) return;
    setAllBootUris(prev => ({ ...prev, [trimmed]: [] }));
    setNewNs('');
    setAddingNs(false);
  };

  const handleDeleteNs = (ns) => {
    setAllBootUris(prev => {
      const next = { ...prev };
      delete next[ns];
      return next;
    });
  };

  if (loading) return <div className="pt-4 text-sm text-slate-500">Loading...</div>;

  const defaultUris = allBootUris[''] || [];
  const otherNamespaces = Object.keys(allBootUris).filter(ns => ns !== '').sort();
  const availableToAdd = knownNamespaces.filter(ns => !(ns in allBootUris));

  return (
    <div className="space-y-3 pt-4">
      <p className="text-xs text-slate-500">
        URIs loaded into <code className="text-indigo-400">system://boot</code> when an agent starts.
        Agents without a specific override use the default list.
      </p>

      <div className="space-y-2">
        <NamespaceBootPanel
          key="__default__"
          namespace=""
          uris={defaultUris}
          isDefault
          onSaved={load}
        />
        {otherNamespaces.map(ns => (
          <NamespaceBootPanel
            key={ns}
            namespace={ns}
            uris={allBootUris[ns] || []}
            isDefault={false}
            onDelete={handleDeleteNs}
            onSaved={load}
          />
        ))}
      </div>

      {addingNs ? (
        <div className="flex gap-1.5 items-center">
          {availableToAdd.length > 0 ? (
            <select
              value={newNs}
              onChange={e => setNewNs(e.target.value === '__custom__' ? '' : e.target.value)}
              className="bg-slate-950 border border-slate-700 text-slate-200 rounded-md px-2.5 py-1.5 text-xs focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"
            >
              <option value="">select or type below...</option>
              {availableToAdd.map(ns => (
                <option key={ns} value={ns}>{ns}</option>
              ))}
              <option value="__custom__">+ custom name...</option>
            </select>
          ) : null}
          <input
            autoFocus={availableToAdd.length === 0}
            type="text"
            value={newNs}
            onChange={e => setNewNs(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter') handleAddNamespace();
              if (e.key === 'Escape') { setAddingNs(false); setNewNs(''); }
            }}
            placeholder="namespace name"
            className="flex-1 bg-slate-950 border border-slate-700 text-slate-200 rounded-md px-2.5 py-1.5 text-xs font-mono placeholder:text-slate-600 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 shadow-inner"
          />
          <button
            onClick={handleAddNamespace}
            disabled={!newNs.trim() || newNs.trim() in allBootUris}
            className="px-2.5 py-1.5 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 text-white rounded-md text-xs flex items-center gap-1 transition-colors"
          >
            <Plus size={12} /> Add
          </button>
          <button
            onClick={() => { setAddingNs(false); setNewNs(''); }}
            className="px-2 py-1.5 text-slate-400 hover:text-slate-200 text-xs transition-colors"
          >
            Cancel
          </button>
        </div>
      ) : (
        <button
          onClick={() => setAddingNs(true)}
          className="w-full py-2 border border-dashed border-slate-700 hover:border-slate-500 rounded-lg text-xs text-slate-500 hover:text-slate-300 flex items-center justify-center gap-1.5 transition-colors"
        >
          <Plus size={12} /> Add namespace override
        </button>
      )}
    </div>
  );
}
