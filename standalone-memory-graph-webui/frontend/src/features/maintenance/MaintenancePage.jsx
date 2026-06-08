import React, { useEffect, useState, useCallback } from 'react';
import {
  Trash2, Sparkles, AlertTriangle, RefreshCw,
  ChevronDown, ChevronUp, ArrowRight, Unlink, Archive, CheckSquare, Square, Minus, Activity
} from 'lucide-react';
import { format } from 'date-fns';
import DiffViewer from '../../components/DiffViewer';
import { api } from '../../lib/api';
import { useI18n } from '../../lib/i18n';

export default function MaintenancePage() {
  const { t } = useI18n();
  const [orphans, setOrphans] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // Expand / detail
  const [expandedId, setExpandedId] = useState(null);
  const [detailData, setDetailData] = useState({});
  const [detailLoading, setDetailLoading] = useState(null);

  // Multi-select
  const [selectedIds, setSelectedIds] = useState(new Set());
  const [batchDeleting, setBatchDeleting] = useState(false);

  const [logStats, setLogStats] = useState({ count: 0, oldest: null });
  const [clearingLogs, setClearingLogs] = useState(false);

  useEffect(() => {
    loadOrphans();
    loadStats();
  }, []);

  const loadStats = async () => {
    try {
      const res = await api.get('/maintenance/access-logs/stats');
      setLogStats(res.data);
    } catch (err) {
      console.error("Failed to load log stats:", err);
    }
  };

  const handleClearLogs = async () => {
    const daysStr = window.prompt("Keep logs for how many days? (Enter 0 to clear all logs)", "30");
    if (daysStr === null) return;
    const days = parseInt(daysStr, 10);
    if (isNaN(days) || days < 0) return;

    setClearingLogs(true);
    try {
      const res = await api.delete('/maintenance/access-logs', { data: { keep_days: days } });
      alert(`Cleared ${res.data.deleted} log entries.`);
      loadStats();
    } catch (err) {
      alert("Failed to clear logs: " + (err.response?.data?.detail || err.message));
    } finally {
      setClearingLogs(false);
    }
  };

  const loadOrphans = async () => {
    setLoading(true);
    setError(null);
    setSelectedIds(new Set());
    try {
      const res = await api.get('/maintenance/orphans');
      setOrphans(res.data);
    } catch (err) {
      setError("Failed to load orphans: " + (err.response?.data?.detail || err.message));
    } finally {
      setLoading(false);
    }
  };

  // Toggle single checkbox
  const toggleSelect = useCallback((id, e) => {
    e.stopPropagation();
    setSelectedIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  // Select/deselect all in a category
  const toggleSelectAll = useCallback((items) => {
    const ids = items.map(i => i.id);
    setSelectedIds(prev => {
      const next = new Set(prev);
      const allSelected = ids.every(id => next.has(id));
      if (allSelected) {
        ids.forEach(id => next.delete(id));
      } else {
        ids.forEach(id => next.add(id));
      }
      return next;
    });
  }, []);

  // Batch delete
  const handleBatchDelete = async () => {
    const count = selectedIds.size;
    if (count === 0) return;
    if (!confirm(`Permanently delete ${count} memories? This cannot be undone.`)) return;

    setBatchDeleting(true);
    const toDelete = [...selectedIds];
    let failed = [];

    for (const id of toDelete) {
      try {
        await api.delete(`/maintenance/orphans/${id}`);
      } catch {
        failed.push(id);
      }
    }

    // Remove successfully deleted from list
    const failedSet = new Set(failed);
    setOrphans(prev => prev.filter(item => !toDelete.includes(item.id) || failedSet.has(item.id)));
    setSelectedIds(new Set(failed));

    if (expandedId && toDelete.includes(expandedId) && !failedSet.has(expandedId)) {
      setExpandedId(null);
    }

    if (failed.length > 0) {
      alert(`${failed.length} of ${count} deletions failed. Failed IDs: ${failed.join(', ')}`);
    }

    setBatchDeleting(false);
  };

  // Expand card
  const handleExpand = async (id) => {
    if (expandedId === id) {
      setExpandedId(null);
      return;
    }
    setExpandedId(id);

    if (!detailData[id]) {
      setDetailLoading(id);
      try {
        const res = await api.get(`/maintenance/orphans/${id}`);
        setDetailData(prev => ({ ...prev, [id]: res.data }));
      } catch (err) {
        setDetailData(prev => ({ ...prev, [id]: { error: err.response?.data?.detail || err.message } }));
      } finally {
        setDetailLoading(null);
      }
    }
  };

  const deprecated = orphans.filter(o => o.category === 'deprecated');
  const orphaned = orphans.filter(o => o.category === 'orphaned');

  const renderCard = (item) => {
    const isExpanded = expandedId === item.id;
    const detail = detailData[item.id];
    const isLoadingDetail = detailLoading === item.id;
    const isChecked = selectedIds.has(item.id);

    return (
      <div key={item.id} className="group relative bg-[#0C0C16] border border-slate-700/40 hover:border-slate-600/60 rounded-lg transition-all">
        {/* Clickable Card Header */}
        <div
          className="flex items-start gap-3 p-4 cursor-pointer select-none"
          onClick={() => handleExpand(item.id)}
        >
          {/* Checkbox */}
          <button
            onClick={(e) => toggleSelect(item.id, e)}
            className="mt-0.5 flex-shrink-0 p-0.5 rounded transition-colors hover:bg-slate-700/30"
          >
            {isChecked ? (
              <CheckSquare size={18} className="text-indigo-400" />
            ) : (
              <Square size={18} className="text-slate-600 group-hover:text-slate-500" />
            )}
          </button>

          {/* Content area */}
          <div className="flex-1 min-w-0">
            {/* Top row: badges + time */}
            <div className="flex items-center gap-2 flex-wrap mb-1.5">
              <span className="text-[11px] font-mono text-slate-400 bg-slate-800/80 px-1.5 py-0.5 rounded">
                #{item.id}
              </span>
              {item.category === 'deprecated' ? (
                <span className="text-[10px] font-mono text-amber-300 bg-amber-900/40 px-1.5 py-0.5 rounded flex items-center gap-1">
                  <Archive size={9} /> deprecated
                </span>
              ) : (
                <span className="text-[10px] font-mono text-rose-300 bg-rose-900/40 px-1.5 py-0.5 rounded flex items-center gap-1">
                  <Unlink size={9} /> orphaned
                </span>
              )}
              {item.migrated_to && (
                <span className="text-[10px] font-mono text-indigo-300 bg-indigo-900/30 px-1.5 py-0.5 rounded">
                  → #{item.migrated_to}
                </span>
              )}
              <span className="text-[11px] text-slate-500">
                {item.created_at ? format(new Date(item.created_at), 'yyyy-MM-dd HH:mm') : 'Unknown'}
              </span>
            </div>

            {/* Migration target paths */}
            {item.migration_target && item.migration_target.paths.length > 0 && (
              <div className="flex items-center gap-1.5 flex-wrap mb-2">
                <ArrowRight size={12} className="text-indigo-400/70 flex-shrink-0" />
                {item.migration_target.paths.map((p, i) => (
                  <span key={i} className="text-[11px] font-mono text-indigo-300/90 bg-indigo-900/25 px-1.5 py-0.5 rounded border border-indigo-800/30">
                    {p}
                  </span>
                ))}
              </div>
            )}
            {item.migration_target && item.migration_target.paths.length === 0 && (
              <div className="flex items-center gap-1.5 mb-2">
                <ArrowRight size={12} className="text-slate-500 flex-shrink-0" />
                <span className="text-[11px] text-slate-500 italic">
                  target #{item.migration_target.id} also has no paths
                </span>
              </div>
            )}

            {/* Content snippet */}
            <div className="bg-slate-900/60 rounded p-2.5 text-[12px] text-slate-400 font-mono leading-relaxed line-clamp-3">
              {item.content_snippet}
            </div>
          </div>

          {/* Expand indicator */}
          <div className="mt-1 flex-shrink-0 text-slate-500">
            {isExpanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
          </div>
        </div>

        {/* Expanded Detail */}
        {isExpanded && (
          <div className="border-t border-slate-700/30 p-5 bg-[#09090F]">
            {isLoadingDetail ? (
              <div className="flex items-center gap-3 text-slate-500 py-4">
                <div className="w-4 h-4 border-2 border-indigo-500/30 border-t-indigo-500 rounded-full animate-spin"></div>
                <span className="text-xs">Loading full content...</span>
              </div>
            ) : detail?.error ? (
              <div className="text-rose-400 text-xs py-2">Error: {detail.error}</div>
            ) : detail ? (
              <div className="space-y-4">
                {/* Full content */}
                <div>
                  <h4 className="text-[11px] uppercase tracking-widest text-slate-500 mb-2 font-semibold">
                    {detail.migration_target ? 'Old Version (This Memory)' : 'Full Content'}
                  </h4>
                  <div className="bg-[#060610] rounded p-4 border border-slate-800/60 text-[12px] text-slate-300 font-mono leading-relaxed whitespace-pre-wrap max-h-64 overflow-y-auto custom-scrollbar">
                    {detail.content}
                  </div>
                </div>

                {/* Diff with migration target */}
                {detail.migration_target && (
                  <div>
                    <h4 className="text-[11px] uppercase tracking-widest text-slate-500 mb-2 font-semibold flex items-center gap-2">
                      <span>Diff: #{item.id} → #{detail.migration_target.id}</span>
                      {detail.migration_target.paths.length > 0 && (
                        <span className="text-indigo-400/70 normal-case tracking-normal font-normal">
                          ({detail.migration_target.paths[0]})
                        </span>
                      )}
                    </h4>
                    <div className="bg-[#060610] rounded border border-slate-800/60 p-4 max-h-96 overflow-y-auto custom-scrollbar">
                      <DiffViewer
                        oldText={detail.content}
                        newText={detail.migration_target.content}
                      />
                    </div>
                  </div>
                )}
              </div>
            ) : null}
          </div>
        )}
      </div>
    );
  };

  // Section header with select-all checkbox
  const renderSectionHeader = (icon, label, color, items) => {
    const allSelected = items.length > 0 && items.every(i => selectedIds.has(i.id));
    const someSelected = items.some(i => selectedIds.has(i.id));

    return (
      <div className="flex items-center gap-3 mb-4">
        <button
          onClick={() => toggleSelectAll(items)}
          className="p-0.5 rounded transition-colors hover:bg-slate-700/30"
          title={allSelected ? "Deselect all" : "Select all"}
        >
          {allSelected ? (
            <CheckSquare size={16} className={color} />
          ) : someSelected ? (
            <Minus size={16} className={color} />
          ) : (
            <Square size={16} className="text-slate-600" />
          )}
        </button>
        {icon}
        <h3 className={`text-xs font-bold uppercase tracking-widest ${color}`}>
          {label}
        </h3>
        <span className="text-[11px] text-slate-500 bg-slate-800/80 px-2 py-0.5 rounded-full">
          {items.length}
        </span>
      </div>
    );
  };

  return (
    <div className="flex h-full bg-[#07070D] text-slate-200 font-sans overflow-hidden">
      {/* Sidebar */}
      <div className="w-72 flex-shrink-0 bg-[#0A0A12] border-r border-slate-700/30 flex flex-col p-6">
        <div className="mb-8">
          <div className="w-12 h-12 bg-amber-950/30 rounded-xl flex items-center justify-center border border-amber-800/30 mb-4 shadow-[0_0_20px_rgba(245,158,11,0.1)]">
            <Sparkles className="text-amber-400" size={24} />
          </div>
          <h1 className="text-xl font-bold text-slate-100 mb-2">{t('maintenance.title')}</h1>
          <p className="text-[12px] text-slate-400 leading-relaxed">
            {t('maintenance.description')}
          </p>
        </div>

        <div className="space-y-3 mt-auto">
          <div className="bg-slate-800/40 rounded-lg p-4 border border-slate-700/40">
            <div className="text-slate-400 text-xs uppercase font-bold tracking-wider mb-1">{t('maintenance.deprecated')}</div>
            <div className="text-3xl font-mono text-amber-400">{deprecated.length}</div>
            <div className="text-slate-500 text-[11px] mt-1">{t('maintenance.deprecated_desc')}</div>
          </div>
          <div className="bg-slate-800/40 rounded-lg p-4 border border-slate-700/40">
            <div className="text-slate-400 text-xs uppercase font-bold tracking-wider mb-1">{t('maintenance.orphaned')}</div>
            <div className="text-3xl font-mono text-rose-400">{orphaned.length}</div>
            <div className="text-slate-500 text-[11px] mt-1">{t('maintenance.orphaned_desc')}</div>
          </div>
          <div className="bg-slate-800/40 rounded-lg p-4 border border-slate-700/40 mt-6 relative">
            <div className="text-slate-400 text-xs uppercase font-bold tracking-wider mb-1 flex justify-between items-center">
              {t('maintenance.access_logs')}
              <button 
                onClick={handleClearLogs}
                disabled={clearingLogs}
                className="text-xs text-rose-400 hover:text-rose-300 disabled:opacity-50"
              >
                {clearingLogs ? "Clearing..." : "Clear"}
              </button>
            </div>
            <div className="text-3xl font-mono text-indigo-400">{logStats.count}</div>
            <div className="text-slate-500 text-[11px] mt-1">
              {logStats.oldest ? `Oldest: ${format(new Date(logStats.oldest), 'MM-dd HH:mm')}` : "No records"}
            </div>
          </div>
        </div>
      </div>

      {/* Main Content */}
      <div className="flex-1 flex flex-col min-w-0 bg-[#07070D] relative overflow-hidden">
        {/* Header with batch actions */}
        <div className="h-14 flex items-center justify-between px-8 border-b border-slate-700/30 bg-[#07070D]/90 backdrop-blur-md sticky top-0 z-10">
          <h2 className="text-sm font-bold text-slate-300 uppercase tracking-widest flex items-center gap-2">
            <Trash2 size={14} /> {t('maintenance.orphan_memories')}
          </h2>
          <div className="flex items-center gap-2">
            {selectedIds.size > 0 && (
              <button
                onClick={handleBatchDelete}
                disabled={batchDeleting}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md bg-rose-900/40 text-rose-300 hover:bg-rose-900/60 border border-rose-800/40 transition-colors disabled:opacity-50"
              >
                {batchDeleting ? (
                  <div className="w-3 h-3 border-2 border-rose-400/30 border-t-rose-400 rounded-full animate-spin"></div>
                ) : (
                  <Trash2 size={13} />
                )}
                Delete {selectedIds.size} selected
              </button>
            )}
            <button
              onClick={loadOrphans}
              className="p-2 text-slate-400 hover:text-indigo-400 hover:bg-slate-700/40 rounded-full transition-all"
              title="Refresh"
            >
              <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
            </button>
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-8 custom-scrollbar">
          {loading ? (
            <div className="flex flex-col items-center justify-center h-64 text-slate-500 gap-4">
              <div className="w-6 h-6 border-2 border-amber-500/30 border-t-amber-500 rounded-full animate-spin"></div>
              <span className="text-xs tracking-widest uppercase">{t('maintenance.scanning')}</span>
            </div>
          ) : error ? (
            <div className="text-rose-400 bg-rose-950/20 border border-rose-800/40 p-6 rounded-lg flex items-center gap-4">
              <AlertTriangle size={24} />
              <div>
                <h3 className="font-bold text-rose-300">Error</h3>
                <p className="text-sm text-rose-400/80">{error}</p>
              </div>
            </div>
          ) : orphans.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full text-slate-600 gap-6 select-none">
              <Sparkles size={64} className="opacity-30" />
              <p className="text-lg font-light text-slate-500">{t('maintenance.system_clean')}</p>
              <p className="text-xs uppercase tracking-widest text-slate-600">{t('maintenance.no_orphans')}</p>
            </div>
          ) : (
            <div className="max-w-5xl mx-auto space-y-8">
              {/* Deprecated Section */}
              {deprecated.length > 0 && (
                <section>
                  {renderSectionHeader(
                    <Archive size={16} className="text-amber-400/80" />,
                    t('maintenance.deprecated_versions'),
                    "text-amber-400/80",
                    deprecated
                  )}
                  <div className="space-y-2">
                    {deprecated.map(renderCard)}
                  </div>
                </section>
              )}

              {/* Orphaned Section */}
              {orphaned.length > 0 && (
                <section>
                  {renderSectionHeader(
                    <Unlink size={16} className="text-rose-400/80" />,
                    t('maintenance.orphaned_memories'),
                    "text-rose-400/80",
                    orphaned
                  )}
                  <div className="space-y-2">
                    {orphaned.map(renderCard)}
                  </div>
                </section>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
