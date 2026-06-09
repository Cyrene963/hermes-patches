import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import { 
  Folder, 
  Edit3, 
  Save, 
  X, 
  Cpu, 
  Hash, 
  AlertTriangle,
  Link2,
  Star,
  Zap,
  Trash2,
  Search,
  FileText,
  Loader2,
} from 'lucide-react';
import clsx from 'clsx';
import { api, getSettingsBootUris, toggleSettingsBootUri, deleteNode, searchMemories } from '../../lib/api';
import { useI18n } from '../../lib/i18n';
import PriorityBadge from './components/PriorityBadge';
import GlossaryHighlighter from './components/GlossaryHighlighter';
import KeywordManager from './components/KeywordManager';
import VisibilityBadge from './components/VisibilityBadge';
import DomainNode from './components/MemorySidebar';
import Breadcrumb from './components/Breadcrumb';
import NodeGridCard from './components/NodeGridCard';
import { useConfirm, useToast } from '../../components/ui';

export default function MemoryBrowser() {
  const { t } = useI18n();
  const confirm = useConfirm();
  const toast = useToast();
  const [searchParams, setSearchParams] = useSearchParams();
  const domain = searchParams.get('domain') || 'core';
  const path = searchParams.get('path') || '';
  
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [data, setData] = useState({ node: null, children: [], breadcrumbs: [] });
  const [domains, setDomains] = useState([]);
  
  const [editing, setEditing] = useState(false);
  const [editContent, setEditContent] = useState('');
  const [editDisclosure, setEditDisclosure] = useState('');
  const [editPriority, setEditPriority] = useState(0);
  const [saving, setSaving] = useState(false);
  const [bootUris, setBootUris] = useState([]);

  // Delete
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [deleting, setDeleting] = useState(false);

  // Search
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState(null);
  const [searching, setSearching] = useState(false);
  const searchTimeoutRef = useRef(null);
  const searchSeqRef = useRef(0);

  const currentRouteRef = useRef({ domain, path });
  useEffect(() => {
    currentRouteRef.current = { domain, path };
  }, [domain, path]);

  useEffect(() => {
    api.get('/browse/domains').then(res => setDomains(res.data)).catch(() => {});
    getSettingsBootUris().then(res => setBootUris(res.uris)).catch(() => {});
  }, []);

  useEffect(() => {
    const fetchData = async () => {
      setLoading(true);
      setError(null);
      setEditing(false);
      try {
        const res = await api.get('/browse/node', { params: { domain, path } });
        setData(res.data);
        setEditContent(res.data.node?.content || '');
        setEditDisclosure(res.data.node?.disclosure || '');
        setEditPriority(res.data.node?.priority ?? 0);
      } catch (err) {
        setError(err.response?.data?.detail || err.message);
      } finally {
        setLoading(false);
      }
    };
    fetchData();
  }, [domain, path]);

  const navigateTo = (newPath, newDomain) => {
    const params = new URLSearchParams();
    params.set('domain', newDomain || domain);
    if (newPath) params.set('path', newPath);
    setSearchParams(params);
  };

  const refreshData = () => {
    return api.get('/browse/node', { params: { domain, path } })
      .then(res => {
        setData(currentData => {
          if (currentRouteRef.current.domain === domain && currentRouteRef.current.path === path) {
            return res.data;
          }
          return currentData;
        });
      });
  };

  const startEditing = () => {
    setEditContent(data.node?.content || '');
    setEditDisclosure(data.node?.disclosure || '');
    setEditPriority(data.node?.priority ?? 0);
    setEditing(true);
  };

  const cancelEditing = () => {
    setEditing(false);
    setEditContent(data.node?.content || '');
    setEditDisclosure(data.node?.disclosure || '');
    setEditPriority(data.node?.priority ?? 0);
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      const payload = {};
      if (editContent !== (data.node?.content || '')) payload.content = editContent;
      if (editPriority !== (data.node?.priority ?? 0)) payload.priority = editPriority;
      if (editDisclosure !== (data.node?.disclosure || '')) payload.disclosure = editDisclosure;
      
      if (Object.keys(payload).length === 0) {
        setEditing(false);
        return;
      }
      
      await api.put('/browse/node', payload, { params: { domain, path } });
      await refreshData();
      setEditing(false);
      toast.success(currentUri, { title: '记忆已保存' });
    } catch (err) {
      toast.error(err.response?.data?.detail || err.message, { title: '保存记忆失败' });
    } finally {
      setSaving(false);
    }
  };

  const handleBootToggle = async (uri) => {
    const isCurrentlyInBoot = bootUris.includes(uri);
    try {
      const result = await toggleSettingsBootUri(uri, !isCurrentlyInBoot);
      setBootUris(result.uris);
      toast.success(isCurrentlyInBoot ? '已从启动上下文移除。' : '已加入启动上下文。', { title: uri });
    } catch (err) {
      toast.error(err.response?.data?.detail || err.message, { title: '启动上下文更新失败' });
    }
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    const uri = `${deleteTarget.domain}://${deleteTarget.path || 'root'}`;
    const accepted = await confirm({
      title: '删除这条记忆节点？',
      description: '这会删除该节点以及后端定义的相关路径关系。删除后请通过审计/备份链路恢复。',
      details: [uri],
      confirmLabel: '删除节点',
      variant: 'danger',
      requireText: 'DELETE',
    });
    if (!accepted) return;
    setDeleting(true);
    try {
      await deleteNode(deleteTarget.domain, deleteTarget.path);
      setDeleteTarget(null);
      const parentPath = deleteTarget.path.includes('/') ? deleteTarget.path.substring(0, deleteTarget.path.lastIndexOf('/')) : '';
      navigateTo(parentPath, deleteTarget.domain);
      toast.success(uri, { title: '记忆节点已删除' });
    } catch (err) {
      toast.error(err.response?.data?.detail || err.message, { title: '删除记忆失败' });
    } finally {
      setDeleting(false);
    }
  };

  const handleSearch = useCallback((query) => {
    setSearchQuery(query);
    if (searchTimeoutRef.current) clearTimeout(searchTimeoutRef.current);
    if (!query.trim()) {
      searchSeqRef.current++;
      setSearchResults(null);
      setSearching(false);
      return;
    }
    setSearching(true);
    setSearchResults(null);
    const seq = ++searchSeqRef.current;
    searchTimeoutRef.current = setTimeout(async () => {
      try {
        const res = await searchMemories(query.trim());
        if (seq !== searchSeqRef.current) return;
        setSearchResults(res.results);
      } catch {
        if (seq !== searchSeqRef.current) return;
        setSearchResults([]);
      } finally {
        if (seq === searchSeqRef.current) setSearching(false);
      }
    }, 300);
  }, []);

  const clearSearch = () => {
    setSearchQuery('');
    setSearchResults(null);
    setSearching(false);
    searchSeqRef.current++;
    if (searchTimeoutRef.current) clearTimeout(searchTimeoutRef.current);
  };

  const isRoot = !path;
  const node = data.node;
  const currentUri = `${domain}://${path}`;

  return (
    <div className="flex h-full bg-[#05050A] text-slate-300 font-sans selection:bg-indigo-500/30 selection:text-indigo-200 overflow-hidden">
      
      {/* Sidebar */}
      <div className="w-64 flex-shrink-0 bg-[#08080E] border-r border-slate-800/30 flex flex-col">
        <div className="p-5 border-b border-slate-800/30">
          <div className="flex items-center gap-2 text-indigo-400 mb-1">
            <Cpu size={18} />
            <h1 className="font-bold tracking-tight text-sm text-slate-100">{t('memory.core')}</h1>
          </div>
          <p className="text-[10px] text-slate-600 pl-6 uppercase tracking-wider">{t('memory.neural_explorer')}</p>
        </div>
        
        <div className="p-3 flex-1 overflow-y-auto custom-scrollbar">
             <div className="mb-4">
                 <h3 className="px-3 text-[10px] font-bold text-slate-600 uppercase tracking-widest mb-2">{t('memory.domains')}</h3>
                 {domains.map(d => (
                   <DomainNode
                     key={d.domain}
                     domain={d.domain}
                     rootCount={d.root_count}
                     activeDomain={domain}
                     activePath={path}
                     onNavigate={navigateTo}
                   />
                 ))}
                 {domains.length === 0 && (
                   <DomainNode
                     domain="core"
                     activeDomain={domain}
                     activePath={path}
                     onNavigate={navigateTo}
                   />
                 )}
             </div>
        </div>

        <div className="mt-auto p-4 border-t border-slate-800/30">
             <div className="bg-slate-900/50 rounded p-3 border border-slate-800/50">
                 <div className="flex items-center gap-2 text-xs text-slate-500 mb-2">
                    <Hash size={12} />
                    <span>{t('memory.current_path')}</span>
                 </div>
                 <code className="block text-[10px] font-mono text-indigo-300/80 break-all leading-tight">
                    {domain}://{path || 'root'}
                 </code>
             </div>
        </div>
      </div>

      {/* Main Area */}
      <div className="flex-1 flex flex-col min-w-0 bg-[#05050A] relative">
         <div className="h-14 flex-shrink-0 border-b border-slate-800/30 flex items-center px-6 bg-[#05050A]/80 backdrop-blur-md sticky top-0 z-20 gap-4">
             <Breadcrumb items={data.breadcrumbs} onNavigate={navigateTo} />
             <div className="ml-auto relative flex-shrink-0 w-72">
               <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-600 pointer-events-none" />
               <input
                 type="text"
                 value={searchQuery}
                 onChange={e => handleSearch(e.target.value)}
                 placeholder={t('memory.search_placeholder')}
                 className="w-full bg-slate-900/60 border border-slate-800/50 rounded-lg pl-9 pr-8 py-1.5 text-sm text-slate-300 placeholder-slate-600 focus:outline-none focus:border-indigo-500/50 transition-colors"
               />
               {searchQuery && (searching
                 ? <Loader2 size={14} className="absolute right-2 top-1/2 -translate-y-1/2 text-indigo-400 animate-spin" />
                 : <button onClick={clearSearch} className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-600 hover:text-slate-400 transition-colors">
                     <X size={14} />
                   </button>
               )}
             </div>
         </div>

         {/* Search Results Overlay */}
         {searchResults !== null && (
           <div className="flex-1 overflow-y-auto p-6 custom-scrollbar">
             <div className="max-w-7xl mx-auto space-y-4">
               <div className="flex items-center justify-between">
                 <h2 className="text-sm font-bold text-slate-400 uppercase tracking-widest">
                   {searchResults.length > 0 
                     ? `${searchResults.length} result${searchResults.length > 1 ? 's' : ''} for "${searchQuery}"`
                     : `No results for "${searchQuery}"`}
                 </h2>
                 <button onClick={clearSearch} className="text-xs text-slate-600 hover:text-slate-400 transition-colors px-3 py-1 border border-slate-800 rounded hover:border-slate-700">
                   {t('memory.back_to_browser')}
                 </button>
               </div>
               {searchResults.map((item, i) => (
                 <button
                   key={`${item.uri}-${i}`}
                   onClick={() => { clearSearch(); navigateTo(item.path, item.domain); }}
                   className="w-full flex items-start gap-4 p-4 bg-[#0A0A12] border border-slate-800/50 rounded-xl hover:border-indigo-500/30 hover:shadow-[0_0_20px_rgba(99,102,241,0.08)] transition-all text-left group"
                 >
                   <div className="p-2 rounded-lg bg-slate-900 text-slate-500 group-hover:text-indigo-400 group-hover:bg-indigo-900/20 transition-colors flex-shrink-0 mt-0.5">
                     <FileText size={16} />
                   </div>
                   <div className="min-w-0 flex-1">
                     <div className="flex items-center gap-2 mb-1">
                       <span className="text-sm font-semibold text-slate-300 group-hover:text-indigo-200 transition-colors">{item.name}</span>
                       <PriorityBadge priority={item.priority} />
                       <VisibilityBadge namespace={item.namespace} visibilityLabel={item.visibility_label} securityLevel={item.security_level} compact />
                     </div>
                     <code className="text-[11px] font-mono text-slate-600 block mb-1.5">{item.uri}</code>
                     {item.snippet && <p className="text-xs text-slate-500 leading-relaxed line-clamp-2">{item.snippet}</p>}
                     {item.disclosure && (
                       <p className="text-[11px] text-amber-500/70 mt-1.5 flex items-center gap-1">
                         <AlertTriangle size={10} className="flex-shrink-0" />
                         <span className="italic truncate">{item.disclosure}</span>
                       </p>
                     )}
                   </div>
                 </button>
               ))}
             </div>
           </div>
         )}

         <div className={clsx("flex-1 overflow-y-auto p-6 custom-scrollbar", searchResults !== null && "hidden")}>
            {loading ? (
                <div className="h-full flex flex-col items-center justify-center gap-4 text-slate-600">
                    <div className="w-8 h-8 border-2 border-indigo-500/20 border-t-indigo-500 rounded-full animate-spin" />
                    <span className="text-xs tracking-widest uppercase">{t('memory.retrieving')}</span>
                </div>
            ) : error ? (
                <div className="h-full flex flex-col items-center justify-center text-rose-500 gap-4">
                    <p className="text-lg">{t('memory.access_denied')}</p>
                    <p className="text-sm opacity-60">{error}</p>
                    <button onClick={() => navigateTo('')} className="text-xs bg-slate-800 px-4 py-2 rounded hover:text-white transition-colors">{t('memory.return_root')}</button>
                </div>
            ) : (
                <div className="max-w-7xl mx-auto space-y-8 animate-in fade-in slide-in-from-bottom-4 duration-500">
                    
                    {node && (
                        <div className="space-y-4">
                            <div className="flex items-start justify-between gap-4">
                                <div className="space-y-3 min-w-0 flex-1">
                                    <div className="flex items-center gap-3 flex-wrap">
                                        <h1 className="text-2xl font-bold text-slate-100 tracking-tight">
                                            {node.name || path.split('/').pop()}
                                        </h1>
                                        <PriorityBadge priority={node.priority} size="lg" />
                                        <VisibilityBadge namespace={node.namespace} visibilityLabel={node.visibility_label} securityLevel={node.security_level} />
                                    </div>
                                    
                                    {node.disclosure && !editing && (
                                        <div className="inline-flex items-center gap-2 px-3 py-1.5 bg-amber-950/20 border border-amber-900/30 rounded-lg text-amber-500/80 text-xs max-w-full">
                                            <AlertTriangle size={14} className="flex-shrink-0" />
                                            <span className="font-medium mr-1">Disclosure:</span>
                                            <span className="italic truncate">{node.disclosure}</span>
                                        </div>
                                    )}
                                    
                                    {node.aliases && node.aliases.length > 0 && !editing && (
                                        <div className="flex items-start gap-2 text-xs text-slate-500">
                                            <Link2 size={13} className="flex-shrink-0 mt-0.5 text-slate-600" />
                                            <div className="flex flex-wrap gap-1.5">
                                                <span className="text-slate-600 font-medium">Also reachable via:</span>
                                                {node.aliases.map(alias => (
                                                    <code key={alias} className="px-1.5 py-0.5 bg-slate-800/60 rounded text-indigo-400/70 font-mono text-[11px]">
                                                        {alias}
                                                    </code>
                                                ))}
                                            </div>
                                        </div>
                                    )}

                                    {!editing && !node.is_virtual && (
                                        <KeywordManager
                                          keywords={node.glossary_keywords || []}
                                          nodeUuid={node.node_uuid}
                                          onUpdate={refreshData}
                                        />
                                    )}
                                </div>
                                
                                <div className="flex gap-2 flex-shrink-0">
                                    {!editing && (
                                        <button
                                            onClick={() => handleBootToggle(currentUri)}
                                            title={bootUris.includes(currentUri) ? "Remove from Boot" : "Add to Boot"}
                                            className={clsx(
                                                "flex items-center gap-2 px-3 py-2 rounded text-sm font-medium transition-all border",
                                                bootUris.includes(currentUri)
                                                    ? "bg-amber-950/40 border-amber-700/50 text-amber-400 hover:bg-amber-950/60 hover:border-amber-600/60 shadow-[0_0_12px_rgba(245,158,11,0.1)]"
                                                    : "bg-slate-800 border-slate-700 text-slate-500 hover:text-amber-400 hover:border-amber-800/40 hover:bg-slate-800/80"
                                            )}
                                        >
                                            <Zap size={15} className={bootUris.includes(currentUri) ? "fill-amber-400" : ""} />
                                            Boot
                                        </button>
                                    )}
                                    {editing ? (
                                        <>
                                            <button onClick={cancelEditing} className="p-2 hover:bg-slate-800 rounded text-slate-400 transition-colors"><X size={18} /></button>
                                            <button onClick={handleSave} disabled={saving} className="flex items-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded text-sm font-medium transition-colors shadow-lg shadow-indigo-900/20">
                                                <Save size={16} /> {saving ? t('memory.saving') : t('memory.save_changes')}
                                            </button>
                                        </>
                                    ) : !node.is_virtual && (
                                        <>
                                            <button onClick={startEditing} className="flex items-center gap-2 px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded text-sm font-medium transition-colors border border-slate-700 hover:border-slate-600">
                                                <Edit3 size={16} /> {t('common.edit')}
                                            </button>
                                            <button
                                              onClick={() => setDeleteTarget({ domain, path })}
                                              className="flex items-center gap-2 px-3 py-2 bg-slate-800 hover:bg-rose-950/60 text-slate-500 hover:text-rose-400 rounded text-sm font-medium transition-colors border border-slate-700 hover:border-rose-800/50"
                                              title="Delete this memory"
                                            >
                                              <Trash2 size={16} />
                                            </button>
                                        </>
                                    )}
                                </div>
                            </div>

                            {editing && (
                                <div className="grid grid-cols-1 md:grid-cols-2 gap-4 p-4 bg-slate-900/50 border border-slate-800/50 rounded-xl">
                                    <div className="space-y-1.5">
                                        <label className="flex items-center gap-1.5 text-xs font-medium text-slate-400">
                                            <Star size={12} />
                                            Priority
                                            <span className="text-slate-600 font-normal">(lower = higher priority)</span>
                                        </label>
                                        <input 
                                            type="number"
                                            min="0"
                                            value={editPriority}
                                            onChange={e => setEditPriority(parseInt(e.target.value) || 0)}
                                            className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 font-mono focus:outline-none focus:border-indigo-500/50 transition-colors"
                                        />
                                    </div>
                                    <div className="space-y-1.5">
                                        <label className="flex items-center gap-1.5 text-xs font-medium text-slate-400">
                                            <AlertTriangle size={12} />
                                            Disclosure
                                            <span className="text-slate-600 font-normal">(when to recall)</span>
                                        </label>
                                        <input 
                                            type="text"
                                            value={editDisclosure}
                                            onChange={e => setEditDisclosure(e.target.value)}
                                            placeholder="e.g. When I need to remember..."
                                            className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-indigo-500/50 transition-colors"
                                        />
                                    </div>
                                </div>
                            )}

                            {(!node.is_virtual || editing) && (
                                <div className={clsx(
                                    "relative rounded-xl border overflow-hidden transition-all duration-300",
                                    editing ? "bg-slate-900 border-indigo-500/50 shadow-[0_0_30px_rgba(99,102,241,0.1)]" : "bg-[#0A0A12]/50 border-slate-800/50"
                                )}>
                                    {editing ? (
                                        <textarea 
                                            value={editContent}
                                            onChange={e => setEditContent(e.target.value)}
                                            className="w-full h-96 p-6 bg-transparent text-slate-200 font-mono text-sm leading-relaxed focus:outline-none resize-y"
                                            spellCheck={false}
                                        />
                                    ) : (
                                        <div className="p-6 md:p-8 prose prose-invert prose-sm max-w-none">
                                            <GlossaryHighlighter
                                              key={node.node_uuid}
                                              content={node.content || ''}
                                              glossary={node.glossary_matches || []}
                                              currentNodeUuid={node.node_uuid}
                                              onNavigate={navigateTo}
                                            />
                                        </div>
                                    )}
                                </div>
                            )}
                        </div>
                    )}

                    {data.children && data.children.length > 0 && (
                        <div className="space-y-4 pt-4">
                            <div className="flex items-center gap-3 text-slate-500">
                                <h2 className="text-xs font-bold uppercase tracking-widest">
                                    {isRoot ? t('memory.clusters') : t('memory.sub_nodes')}
                                </h2>
                                <div className="h-px flex-1 bg-slate-800/50"></div>
                                <span className="text-xs bg-slate-800/50 px-2 py-0.5 rounded-full">{data.children.length}</span>
                            </div>
                            
                            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
                                {data.children.map(child => (
                                    <NodeGridCard 
                                        key={`${child.domain || domain}:${child.path}`} 
                                        node={child}
                                        currentDomain={domain}
                                        isInBoot={bootUris.includes(child.uri)}
                                        onBootToggle={() => handleBootToggle(child.uri)}
                                        onClick={() => navigateTo(child.path, child.domain)} 
                                    />
                                ))}
                            </div>
                        </div>
                    )}
                    
                    {!loading && !data.children?.length && !node && (
                        <div className="flex flex-col items-center justify-center py-20 text-slate-600 gap-4">
                            <Folder size={48} className="opacity-20" />
                            <p className="text-sm">Empty Sector</p>
                        </div>
                    )}
                </div>
            )}
         </div>
      </div>

      {/* Delete Confirmation Dialog */}
      {deleteTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={() => !deleting && setDeleteTarget(null)}>
          <div className="bg-[#0C0C14] border border-slate-800 rounded-xl p-6 max-w-md w-full mx-4 shadow-2xl" onClick={e => e.stopPropagation()}>
            <div className="flex items-center gap-3 mb-4">
              <div className="p-2.5 rounded-lg bg-rose-950/40 text-rose-400">
                <Trash2 size={20} />
              </div>
              <div>
                <h3 className="text-base font-bold text-slate-100">Delete Memory</h3>
                <p className="text-xs text-slate-500 mt-0.5">This action is irreversible</p>
              </div>
            </div>
            <div className="mb-5 p-3 bg-slate-900/60 border border-slate-800/50 rounded-lg">
              <code className="text-sm font-mono text-rose-300/80 break-all">{deleteTarget.domain}://{deleteTarget.path}</code>
            </div>
            <p className="text-sm text-slate-400 mb-6">
              Are you sure you want to delete this memory path? If this is the node's last path, the content will become an orphan.
            </p>
            <div className="flex gap-3 justify-end">
              <button
                onClick={() => setDeleteTarget(null)}
                disabled={deleting}
                className="px-4 py-2 text-sm text-slate-400 hover:text-slate-200 bg-slate-800 hover:bg-slate-700 rounded-lg border border-slate-700 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleDelete}
                disabled={deleting}
                className="px-4 py-2 text-sm font-medium text-white bg-rose-600 hover:bg-rose-500 rounded-lg transition-colors shadow-lg shadow-rose-900/20 disabled:opacity-50"
              >
                {deleting ? 'Deleting...' : 'Delete'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
