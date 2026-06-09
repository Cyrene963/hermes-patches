import React, { useEffect, useState, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { getGroups, getGroupDiff, rollbackGroup, approveGroup, clearAll, getProposalInbox, rejectProposal, approveProposal, getMe } from '../../lib/api';
import SnapshotList from '../../components/SnapshotList';
import DiffViewer from '../../components/DiffViewer';
import { AnimatedButton, AnimatedBadge, EmptyState } from '../../components/AnimatedUI';
import { useConfirm, useToast } from '../../components/ui';
import { useI18n } from '../../lib/i18n';
import {
  Activity,
  Check,
  FileText,
  Layout,
  RotateCcw,
  ShieldCheck,
  Database,
  Trash2,
  Box,
  Link as LinkIcon,
  BookOpen
} from 'lucide-react';
import clsx from 'clsx';

function ReviewPage() {
  const { t } = useI18n();
  const confirm = useConfirm();
  const toast = useToast();
  const [changes, setChanges] = useState([]);
  const [selectedChange, setSelectedChange] = useState(null);
  const [diffData, setDiffData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [diffError, setDiffError] = useState(null);
  const [activeQueue, setActiveQueue] = useState('graph');
  const [proposalInbox, setProposalInbox] = useState(null);
  const [proposalStage, setProposalStage] = useState('ready_memory');
  const [selectedProposal, setSelectedProposal] = useState(null);
  const [proposalLoading, setProposalLoading] = useState(false);
  const [proposalError, setProposalError] = useState(null);
  const [proposalActionLoading, setProposalActionLoading] = useState(false);
  const [proposalActionError, setProposalActionError] = useState(null);
  const [canReviewGraph, setCanReviewGraph] = useState(null);

  const diffRequestRef = useRef(0);

  useEffect(() => {
    let cancelled = false;
    const boot = async () => {
      let graphAllowed = false;
      try {
        const me = await getMe();
        graphAllowed = Boolean(me?.authenticated && (me?.role === 'admin' || me?.username === 'admin'));
      } catch {
        graphAllowed = false;
      }
      if (cancelled) return;
      setCanReviewGraph(graphAllowed);
      if (graphAllowed) {
        await loadChanges();
      } else {
        setActiveQueue('proposals');
        setChanges([]);
        setSelectedChange(null);
        setDiffData(null);
      }
      await loadProposals();
    };
    void boot();
    return () => { cancelled = true; };
  }, []);

  const loadChanges = async () => {
    if (canReviewGraph === false) {
      setChanges([]);
      setSelectedChange(null);
      setDiffData(null);
      return [];
    }
    setLoading(true);
    try {
      const list = await getGroups();
      setChanges(list);
      if (selectedChange && !list.find(c => c.node_uuid === selectedChange.node_uuid)) {
        setSelectedChange(list.length > 0 ? list[0] : null);
      } else if (list.length > 0 && !selectedChange) {
        setSelectedChange(list[0]);
      }
      if (list.length === 0) {
        setSelectedChange(null);
        setDiffData(null);
      }
      return list;
    } catch (err) {
      if (err.response?.status === 403) {
        setCanReviewGraph(false);
        setActiveQueue('proposals');
        setChanges([]);
        setSelectedChange(null);
        setDiffData(null);
      } else {
        setDiffError("Disconnected from Neural Core (Backend offline).");
      }
      return [];
    } finally {
      setLoading(false);
    }
  };

  const loadProposals = async () => {
    setProposalLoading(true);
    setProposalError(null);
    try {
      const data = await getProposalInbox({ status: 'pending', stage: proposalStage, limit: 100 });
      setProposalInbox(data);
      const proposals = data?.inbox?.proposals || [];
      if (selectedProposal && !proposals.find(p => p.proposal_id === selectedProposal.proposal_id)) {
        setSelectedProposal(proposals.length > 0 ? proposals[0] : null);
      } else if (proposals.length > 0 && !selectedProposal) {
        setSelectedProposal(proposals[0]);
      }
      if (proposals.length === 0) setSelectedProposal(null);
      return data;
    } catch (err) {
      setProposalError(err.response?.data?.detail || err.message || 'Failed to load candidate queue.');
      return null;
    } finally {
      setProposalLoading(false);
    }
  };

  useEffect(() => {
    if (activeQueue === 'proposals') loadProposals();
  }, [proposalStage]);

  useEffect(() => {
    if (selectedChange) {
      loadDiff(selectedChange.node_uuid);
    }
  }, [selectedChange]);

  const loadDiff = async (nodeUuid) => {
    const requestId = ++diffRequestRef.current;
    setDiffError(null);
    setDiffData(null);
    try {
      const data = await getGroupDiff(nodeUuid);
      if (requestId === diffRequestRef.current) setDiffData(data);
    } catch (err) {
      if (requestId === diffRequestRef.current) {
        setDiffError(err.response?.data?.detail || "Failed to retrieve memory fragment.");
        setDiffData(null);
      }
    }
  };

  const handleRollback = async () => {
    if (!selectedChange) return;
    const accepted = await confirm({
      title: '拒绝这组记忆变更？',
      description: '系统会回滚当前快照组，并保留后端能够提供的审计记录。',
      details: [selectedChange.display_uri, `变更类型：${selectedChange.action || 'unknown'}`],
      confirmLabel: '拒绝并回滚',
      variant: 'danger',
    });
    if (!accepted) return;
    try {
      const res = await rollbackGroup(selectedChange.node_uuid);
      if (res && res.success === false) {
        throw new Error(res.message || "Unknown error during rollback");
      }
      const list = await loadChanges();
      if (list.find(c => c.node_uuid === selectedChange.node_uuid)) {
        await loadDiff(selectedChange.node_uuid);
      }
      toast.success('已回滚这组记忆变更。', { title: '回滚完成' });
    } catch (err) {
      const errorMsg = err.response?.data?.detail || err.message;
      toast.error(errorMsg, { title: t('review.rejection_failed') });
    }
  };

  const handleApprove = async () => {
    if (!selectedChange) return;
    try {
      await approveGroup(selectedChange.node_uuid);
      await loadChanges();
      toast.success(selectedChange.display_uri, { title: '已接受记忆变更' });
    } catch (err) {
      toast.error(err.response?.data?.detail || err.message, { title: t('review.integration_failed') });
    }
  };

  const handleClearAll = async () => {
    const accepted = await confirm({
      title: '标记当前所有安全事件已处理？',
      description: '这会把当前列表里的图谱快照全部标记为已处理。请只在你已经确认隔离区质量时使用。',
      details: [`待处理数量：${changes.length}`],
      confirmLabel: '全部标记已处理',
      variant: 'default',
      requireText: changes.length >= 10 ? 'APPROVE' : '',
    });
    if (!accepted) return;
    try {
      await clearAll();
      setChanges([]);
      setSelectedChange(null);
      setDiffData(null);
      toast.success('图谱变更队列已清空。', { title: '全部接受完成' });
    } catch (err) {
      toast.error(err.response?.data?.detail || err.message, { title: t('review.mass_integration_failed') });
    }
  };

  const handleRejectProposal = async () => {
    if (!selectedProposal || proposalActionLoading) return;
    const accepted = await confirm({
      title: '拒绝这条候选记忆？',
      description: '候选会留在审计链路中标记为 rejected，不会写入 Memory Graph。',
      details: [
        `Proposal #${selectedProposal.proposal_id}`,
        selectedProposal.human_title || selectedProposal.reason || 'No readable summary provided.',
      ],
      confirmLabel: '拒绝候选',
      variant: 'danger',
    });
    if (!accepted) return;
    setProposalActionLoading(true);
    setProposalActionError(null);
    try {
      await rejectProposal(selectedProposal.proposal_id, 'Kept out from Memory Graph safety valve');
      const data = await loadProposals();
      const proposals = data?.inbox?.proposals || [];
      setSelectedProposal(proposals.length > 0 ? proposals[0] : null);
      toast.success(`#${selectedProposal.proposal_id}`, { title: '已拒绝候选记忆' });
    } catch (err) {
      const detail = err.response?.data?.detail;
      const message = typeof detail === 'string' ? detail : JSON.stringify(detail || err.message);
      setProposalActionError(message);
      toast.error(message, { title: '拒绝候选失败' });
    } finally {
      setProposalActionLoading(false);
    }
  };

  const handleApproveProposal = async () => {
    if (!selectedProposal || proposalActionLoading) return;
    if (selectedProposal.target_store !== 'memory_graph' || selectedProposal.review_stage !== 'ready_memory') {
      setProposalActionError(t('review.only_ready_memory_approvable'));
      toast.warning(t('review.only_ready_memory_approvable'), { title: '无法放行' });
      return;
    }
    const accepted = await confirm({
      title: '放行候选记忆写入 Memory Graph？',
      description: '放行后系统会执行候选变更、读回验证，并刷新安全事件队列。',
      details: [
        `Proposal #${selectedProposal.proposal_id}`,
        selectedProposal.human_title || selectedProposal.reason || 'No readable summary provided.',
      ],
      confirmLabel: '放行写入',
      variant: 'default',
    });
    if (!accepted) return;
    setProposalActionLoading(true);
    setProposalActionError(null);
    try {
      await approveProposal(selectedProposal.proposal_id, 'Released from Memory Graph safety valve');
      const data = await loadProposals();
      const proposals = data?.inbox?.proposals || [];
      setSelectedProposal(proposals.length > 0 ? proposals[0] : null);
      await loadChanges();
      setActiveQueue('graph');
      toast.success(`#${selectedProposal.proposal_id}`, { title: '候选记忆已放行' });
    } catch (err) {
      const detail = err.response?.data?.detail;
      const message = typeof detail === 'string' ? detail : JSON.stringify(detail || err.message);
      setProposalActionError(message);
      toast.error(message, { title: '放行候选失败' });
    } finally {
      setProposalActionLoading(false);
    }
  };

  const renderMetadataChanges = () => {
    if (!diffData?.before_meta || !diffData?.current_meta) return null;
    const metaKeys = ['priority', 'disclosure'];
    
    const hasPathChanges = diffData.path_changes && diffData.path_changes.length > 0;
    
    const diffs = metaKeys.filter(key => {
      const oldVal = diffData.before_meta[key];
      const newVal = diffData.current_meta[key];
      const isChanged = JSON.stringify(oldVal) !== JSON.stringify(newVal);
      
      if (isChanged) return true;
      if (hasPathChanges && (oldVal != null || newVal != null)) return true;
      
      return false;
    });

    if (diffs.length === 0) return null;

    const allPreserved = diffs.every(key => JSON.stringify(diffData.before_meta[key]) === JSON.stringify(diffData.current_meta[key]));
    const isCreation = diffData.action === 'created';
    const isDeletion = diffData.current_meta.priority == null && diffData.before_meta.priority != null;

    return (
      <div className="mb-8 p-4 bg-slate-900/40 border border-slate-800/60 rounded-lg backdrop-blur-sm">
        <h3 className="text-xs font-bold text-slate-500 uppercase mb-4 flex items-center gap-2 tracking-widest">
          <Activity size={12} /> Edge Metadata {isCreation ? "(Initial)" : isDeletion ? "(Removed)" : allPreserved ? "(Preserved)" : "Shifts"}
        </h3>
        <div className="space-y-3">
          {diffs.map(key => {
            const oldVal = diffData.before_meta[key];
            const newVal = diffData.current_meta[key];
            const isChanged = JSON.stringify(oldVal) !== JSON.stringify(newVal);
            
            return (
              <div key={key} className="grid grid-cols-[100px_1fr_20px_1fr] gap-4 text-sm items-start">
                <span className="text-slate-400 font-medium capitalize text-xs pt-0.5">{key}</span>
                <div className={clsx("text-xs font-mono text-right break-words", isChanged && !isCreation ? "text-rose-400/70 line-through" : "text-slate-500")}>
                  {oldVal != null ? String(oldVal) : '∅'}
                </div>
                <div className="text-center text-slate-700 pt-0.5">
                  {isChanged ? '→' : '≡'}
                </div>
                <div className={clsx("text-xs font-mono font-bold break-words", isChanged ? "text-emerald-400" : "text-slate-400")}>
                  {newVal != null ? String(newVal) : '∅'}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    );
  };

  const changeTypeIcon = (type) => {
    switch (type) {
      case 'nodes': return <Box size={18} />;
      case 'memories': return <FileText size={18} />;
      case 'edges': return <LinkIcon size={18} />;
      case 'paths': return <Database size={18} />;
      case 'glossary_keywords': return <BookOpen size={18} />;
      default: return <FileText size={18} />;
    }
  };

  const proposalEligibleForDirectApproval = selectedProposal?.target_store === 'memory_graph' && selectedProposal?.review_stage === 'ready_memory';
  const proposalReadbackState = proposalEligibleForDirectApproval
    ? t('review.readback_will_run')
    : t('review.direct_approval_unavailable');
  const proposalContentText = selectedProposal?.content_preview?.text || t('review.redacted');
  const proposalEvidenceText = selectedProposal?.evidence_preview?.text || t('review.redacted');
  const proposalStillRedacted = Boolean(selectedProposal?.content_preview?.redacted || selectedProposal?.evidence_preview?.redacted);
  const proposalListTitle = (proposal) => {
    const text = proposal?.content_preview?.text;
    if (text && text !== '[redacted]' && text !== '[已脱敏]') return text;
    return proposal?.subject || proposal?.candidate_kind || t('review.memory_candidate');
  };

  const changeTypeStyle = (action) => {
    switch (action) {
      case 'created':
        return "bg-emerald-950/10 border-emerald-500/20 text-emerald-400 shadow-[0_0_15px_rgba(16,185,129,0.1)]";
      case 'deleted':
        return "bg-rose-950/10 border-rose-500/20 text-rose-400 shadow-[0_0_15px_rgba(244,63,94,0.1)]";
      default:
        return "bg-amber-950/10 border-amber-500/20 text-amber-400 shadow-[0_0_15px_rgba(245,158,11,0.1)]";
    }
  };

  return (
    <div className="flex h-full bg-[#05050A] text-slate-300 overflow-hidden font-sans selection:bg-purple-500/30 selection:text-purple-200">

      {/* Sidebar */}
      <div className="w-72 flex-shrink-0 flex flex-col border-r border-slate-800/30 bg-[#08080E]">
        <div className="p-5 border-b border-slate-800/30">
          <div className="flex items-center gap-3 text-slate-100">
            <div className="w-8 h-8 rounded bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center shadow-lg shadow-purple-900/20">
              <ShieldCheck className="w-4 h-4 text-white" />
            </div>
            <div className="flex flex-col">
              <span className="font-bold tracking-tight text-sm">{t('review.global_review')}</span>
              <span className="text-[10px] text-indigo-400/70 uppercase tracking-widest font-medium">{t('review.all_namespaces')}</span>
            </div>
          </div>
          <div className="mt-4 grid grid-cols-2 gap-2">
            <button
              onClick={() => { if (canReviewGraph !== false) setActiveQueue('graph'); }}
              disabled={canReviewGraph === false}
              className={clsx(
                "rounded-md border px-2 py-2 text-[10px] font-bold uppercase tracking-wider transition-colors",
                canReviewGraph === false
                  ? "cursor-not-allowed border-slate-900 bg-slate-950/40 text-slate-700"
                  : activeQueue === 'graph'
                  ? "border-indigo-500/40 bg-indigo-500/10 text-indigo-200"
                  : "border-slate-800 bg-slate-900/30 text-slate-500 hover:text-slate-300"
              )}
            >
              {t('review.graph_changes_plain')} ({changes.length})
            </button>
            <button
              onClick={() => { setProposalStage('ready_memory'); setActiveQueue('proposals'); }}
              className={clsx(
                "rounded-md border px-2 py-2 text-[10px] font-bold uppercase tracking-wider transition-colors",
                activeQueue === 'proposals'
                  ? "border-purple-500/40 bg-purple-500/10 text-purple-200"
                  : "border-slate-800 bg-slate-900/30 text-slate-500 hover:text-slate-300"
              )}
            >
              {t('review.pending_memories')} ({proposalInbox?.inbox?.ready_memory_count ?? 0})
            </button>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto py-2">
          {activeQueue === 'graph' ? (
            loading ? (
              <div className="p-8 flex justify-center">
                <div className="w-6 h-6 border-2 border-indigo-500/30 border-t-indigo-500 rounded-full animate-spin"></div>
              </div>
            ) : (
              <SnapshotList
                snapshots={changes}
                selectedId={selectedChange?.node_uuid}
                onSelect={setSelectedChange}
              />
            )
          ) : proposalLoading ? (
            <div className="p-8 flex justify-center">
              <div className="w-6 h-6 border-2 border-purple-500/30 border-t-purple-500 rounded-full animate-spin"></div>
            </div>
          ) : proposalError ? (
            <div className="p-4 text-xs text-rose-400/80">{proposalError}</div>
          ) : (proposalInbox?.inbox?.proposals || []).length > 0 ? (
            <div className="space-y-2 px-2">
              <div className="grid grid-cols-2 gap-2 px-1 pb-2">
                <button
                  onClick={() => setProposalStage('ready_memory')}
                  className={clsx(
                    "rounded-md border px-2 py-1.5 text-[10px] font-bold transition-colors",
                    proposalStage === 'ready_memory'
                      ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-200"
                      : "border-slate-800 bg-slate-900/30 text-slate-500 hover:text-slate-300"
                  )}
                >
                  {t('review.ready_memory_bucket')} ({proposalInbox?.inbox?.ready_memory_count ?? 0})
                </button>
                <button
                  onClick={() => setProposalStage('raw_material')}
                  className={clsx(
                    "rounded-md border px-2 py-1.5 text-[10px] font-bold transition-colors",
                    proposalStage === 'raw_material'
                      ? "border-amber-500/40 bg-amber-500/10 text-amber-200"
                      : "border-slate-800 bg-slate-900/30 text-slate-500 hover:text-slate-300"
                  )}
                >
                  {t('review.raw_material_bucket')} ({proposalInbox?.inbox?.raw_material_count ?? 0})
                </button>
              </div>
              {(proposalInbox?.inbox?.proposals || []).map((proposal) => (
                <button
                  key={proposal.proposal_id}
                  onClick={() => setSelectedProposal(proposal)}
                  className={clsx(
                    "w-full text-left rounded-lg border px-3 py-3 transition-colors",
                    selectedProposal?.proposal_id === proposal.proposal_id
                      ? "border-purple-500/40 bg-purple-500/10 text-purple-100"
                      : "border-slate-800/60 bg-slate-900/20 text-slate-400 hover:bg-slate-900/50"
                  )}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate text-xs font-semibold">{proposalListTitle(proposal)}</span>
                    <span className={clsx(
                      "shrink-0 rounded px-1.5 py-0.5 text-[9px] uppercase border",
                      proposal.review_stage === 'ready_memory'
                        ? "bg-emerald-500/10 text-emerald-300 border-emerald-500/20"
                        : "bg-amber-500/10 text-amber-300 border-amber-500/20"
                    )}>{proposal.review_stage === 'ready_memory' ? t('review.ready_to_confirm') : t('review.needs_distillation')}</span>
                  </div>
                  <div className="mt-1 truncate text-[11px] text-slate-500">{proposal.namespace || t('review.private_source')}</div>
                  <div className="mt-2 flex items-center justify-end gap-2 text-[10px] text-slate-600">
                    <span className="shrink-0 rounded-full border border-slate-700 bg-slate-900/60 px-2 py-0.5 text-slate-400">
                      {proposal.target_store === 'memory_graph' ? t('review.can_write') : t('review.needs_conversion')}
                    </span>
                  </div>
                </button>
              ))}
            </div>
          ) : (
            <div className="space-y-3 p-4 text-center text-xs text-slate-500">
              <div className="grid grid-cols-2 gap-2">
                <button onClick={() => setProposalStage('ready_memory')} className="rounded-md border border-emerald-500/30 bg-emerald-500/10 px-2 py-2 text-emerald-200">
                  {t('review.ready_memory_bucket')} ({proposalInbox?.inbox?.ready_memory_count ?? 0})
                </button>
                <button onClick={() => setProposalStage('raw_material')} className="rounded-md border border-amber-500/30 bg-amber-500/10 px-2 py-2 text-amber-200">
                  {t('review.raw_material_bucket')} ({proposalInbox?.inbox?.raw_material_count ?? 0})
                </button>
              </div>
              <div className="rounded-xl border border-slate-800/60 bg-slate-900/30 p-4">
                <div className="text-sm font-semibold text-slate-400">{t('review.no_pending_candidates')}</div>
                <p className="mt-2 text-xs leading-5 text-slate-600">{t('review.no_pending_candidates_desc')}</p>
              </div>
            </div>
          )}
        </div>

        {activeQueue === 'graph' && changes.length > 0 && (
          <div className="p-4 border-t border-slate-800/30 bg-slate-900/20 backdrop-blur-sm">
            <button
              onClick={handleClearAll}
              className="w-full group flex items-center justify-center gap-2 bg-slate-800/50 hover:bg-emerald-900/20 text-slate-400 hover:text-emerald-400 border border-slate-700 hover:border-emerald-800/50 rounded-md py-2.5 text-xs font-medium transition-all duration-300"
            >
              <Check size={14} className="group-hover:scale-110 transition-transform" />
              <span>{t('review.integrate_all')}</span>
            </button>
          </div>
        )}
      </div>

      {/* Main Stage */}
      <div className="flex-1 flex flex-col min-w-0 bg-[#05050A] relative">
        <div className="absolute top-0 left-0 right-0 h-96 bg-gradient-to-b from-purple-900/5 to-transparent pointer-events-none" />

        {activeQueue === 'graph' && selectedChange ? (
          <>
            {/* Header */}
            <div className="h-20 border-b border-slate-800/30 flex items-center justify-between px-8 relative z-10 backdrop-blur-sm">
              <div className="flex items-center gap-4 min-w-0">
                <div className={clsx(
                  "w-10 h-10 rounded-full flex items-center justify-center border",
                  changeTypeStyle(selectedChange.action)
                )}>
                  {changeTypeIcon(selectedChange.top_level_table)}
                </div>
                <div className="min-w-0 flex flex-col">
                  <h2 className="text-lg font-medium text-slate-100 truncate tracking-tight flex items-center gap-3">
                    <span>{selectedChange.display_uri}</span>
                    {selectedChange.namespaces && selectedChange.namespaces.length > 0 && selectedChange.namespaces.some(ns => ns !== "" || selectedChange.namespaces.length > 1) && (
                      <span className="text-[10px] px-2 py-0.5 rounded bg-indigo-500/10 text-indigo-400 border border-indigo-500/20 tracking-widest font-mono uppercase">
                        {selectedChange.namespaces.map(ns => ns === "" ? "default" : ns).join(', ')}
                      </span>
                    )}
                  </h2>
                  <div className="flex items-center gap-2 text-xs text-slate-500">
                    <span className="bg-slate-800/50 px-1.5 py-0.5 rounded text-slate-400 capitalize">
                      {selectedChange.top_level_table} {selectedChange.action || 'modified'}
                    </span>
                    <span className="text-slate-600">
                      ({selectedChange.row_count} rows affected)
                    </span>
                  </div>
                </div>
              </div>

              <motion.div
                className="flex items-center gap-3"
                initial={{ opacity: 0, x: 20 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: 0.3 }}
              >
                <AnimatedButton
                  onClick={handleRollback}
                  variant="danger"
                  icon={RotateCcw}
                >
                  {t('review.reject_group')}
                </AnimatedButton>
                <AnimatedButton
                  onClick={handleApprove}
                  variant="primary"
                  icon={Check}
                >
                  {t('review.integrate_group')}
                </AnimatedButton>
              </motion.div>
            </div>

            {/* Diff Area */}
            <div className="flex-1 overflow-y-auto px-8 py-8 custom-scrollbar">
              <div className="max-w-4xl mx-auto space-y-6">
                <SafetyValveNote />
                {diffError ? (
                  <div className="mt-20 flex flex-col items-center justify-center text-rose-500 gap-6 animate-in fade-in zoom-in duration-300">
                    <div className="w-20 h-20 bg-rose-950/20 rounded-full flex items-center justify-center border border-rose-900/50 shadow-xl">
                      <Activity size={32} />
                    </div>
                    <div className="text-center">
                      <p className="text-lg font-medium text-rose-200">Memory Retrieval Failed</p>
                      <p className="text-rose-400/60 mt-2 max-w-md text-sm">{diffError}</p>
                    </div>
                    <button
                      onClick={() => loadDiff(selectedChange.node_uuid)}
                      className="px-6 py-2 bg-slate-800/50 hover:bg-slate-800 rounded-full text-slate-300 text-xs transition-colors border border-slate-700"
                    >
                      Retry Connection
                    </button>
                  </div>
                ) : diffData ? (
                  <div className="animate-in fade-in slide-in-from-bottom-4 duration-500">
                    <div className="mb-6 flex justify-end">
                      <div className={clsx(
                        "inline-flex items-center gap-2 px-3 py-1 rounded-full text-[10px] font-bold uppercase tracking-widest border",
                        diffData.action === 'deleted' 
                          ? "bg-rose-500/5 border-rose-500/20 text-rose-500" 
                          : diffData.action === 'created'
                            ? "bg-emerald-500/5 border-emerald-500/20 text-emerald-500"
                            : (diffData.has_changes || diffData.path_changes?.length > 0 || diffData.glossary_changes?.length > 0)
                              ? "bg-amber-500/5 border-amber-500/20 text-amber-500"
                              : "bg-slate-800/50 border-slate-700 text-slate-500"
                      )}>
                        {diffData.action === 'deleted' ? "Deletion Detected" 
                          : diffData.action === 'created' ? "Creation Detected" 
                          : (diffData.has_changes || diffData.path_changes?.length > 0 || diffData.glossary_changes?.length > 0) ? "Modification Detected" 
                          : "No Content Deviation"}
                      </div>
                    </div>

                    {diffData.path_changes && diffData.path_changes.length > 0 && (
                      <div className="mb-8 p-4 bg-slate-900/40 border border-slate-800/60 rounded-lg backdrop-blur-sm">
                        <h3 className="text-xs font-bold text-slate-500 uppercase mb-4 flex items-center gap-2 tracking-widest">
                          <Database size={12} /> Path Modifications
                        </h3>
                        <div className="space-y-2">
                          {diffData.path_changes.map((pc, i) => (
                            <div key={i} className="flex items-center gap-3 text-sm">
                              {pc.action === 'deleted' ? (
                                <span className="text-rose-500/80 bg-rose-500/10 px-2 py-0.5 rounded text-[10px] uppercase font-bold tracking-wider">Removed</span>
                              ) : (
                                <span className="text-emerald-500/80 bg-emerald-500/10 px-2 py-0.5 rounded text-[10px] uppercase font-bold tracking-wider">Added</span>
                              )}
                              <span className={clsx("font-mono text-xs break-all", pc.action === 'deleted' ? "text-rose-400/70 line-through" : "text-emerald-400")}>
                                {pc.uri}
                              </span>
                              {pc.namespace !== undefined && pc.namespace !== null && (pc.namespace !== "" || (selectedChange.namespaces && selectedChange.namespaces.some(n => n !== "" || selectedChange.namespaces.length > 1))) && (
                                <span className="ml-auto text-[10px] px-2 py-0.5 rounded bg-indigo-500/10 text-indigo-400 border border-indigo-500/20 tracking-wider font-mono">
                                  {pc.namespace === "" ? "default" : pc.namespace}
                                </span>
                              )}
                            </div>
                          ))}
                        </div>
                        {diffData.active_paths && diffData.active_paths.length > 0 && (
                          <div className="mt-4 pt-4 border-t border-slate-800/50">
                            <span className="text-xs text-slate-500 block mb-2">Node remains accessible at:</span>
                            <div className="flex flex-wrap gap-2">
                              {diffData.active_paths.map((uri, i) => (
                                <span key={i} className="flex items-center gap-2 text-xs font-mono text-indigo-300 bg-indigo-900/10 border border-indigo-500/20 px-2 py-1 rounded">
                                  <span>{uri}</span>
                                  {diffData.path_namespaces && diffData.path_namespaces[uri] && diffData.path_namespaces[uri]
                                    .filter(ns => ns !== "" || diffData.path_namespaces[uri].length > 1 || (selectedChange.namespaces && selectedChange.namespaces.some(n => n !== "" || selectedChange.namespaces.length > 1)))
                                    .map((ns, nsIdx) => (
                                    <span key={nsIdx} className="text-[10px] px-1.5 py-0.5 rounded bg-indigo-500/20 text-indigo-300 border border-indigo-500/30">
                                      {ns === "" ? "default" : ns}
                                    </span>
                                  ))}
                                </span>
                              ))}
                            </div>
                          </div>
                        )}
                      </div>
                    )}

                    {diffData.glossary_changes && diffData.glossary_changes.length > 0 && (
                      <div className="mb-8 p-4 bg-slate-900/40 border border-slate-800/60 rounded-lg backdrop-blur-sm">
                        <h3 className="text-xs font-bold text-slate-500 uppercase mb-4 flex items-center gap-2 tracking-widest">
                          <BookOpen size={12} /> Glossary Keywords
                        </h3>
                        <div className="space-y-2">
                          {diffData.glossary_changes.map((gc, i) => (
                            <div key={i} className="flex items-center gap-3 text-sm">
                              {gc.action === 'deleted' ? (
                                <span className="text-rose-500/80 bg-rose-500/10 px-2 py-0.5 rounded text-[10px] uppercase font-bold tracking-wider">Removed</span>
                              ) : (
                                <span className="text-emerald-500/80 bg-emerald-500/10 px-2 py-0.5 rounded text-[10px] uppercase font-bold tracking-wider">Added</span>
                              )}
                              <span className={clsx("font-mono text-xs break-all", gc.action === 'deleted' ? "text-rose-400/70 line-through" : "text-emerald-400")}>
                                {gc.keyword}
                              </span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {renderMetadataChanges()}

                    <div className="bg-[#0A0A12]/50 rounded-xl border border-slate-800/50 p-1 min-h-[200px] shadow-2xl relative overflow-hidden">
                      <div className="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-transparent via-indigo-500/20 to-transparent opacity-50"></div>
                      <div className="p-6 md:p-10">
                        <DiffViewer
                          oldText={diffData.before_content ?? ''}
                          newText={diffData.current_content ?? ''}
                        />
                      </div>
                    </div>
                  </div>
                ) : (
                  <div className="flex flex-col items-center justify-center h-64 text-slate-700">
                    <div className="w-2 h-2 bg-indigo-500 rounded-full animate-ping mb-4"></div>
                    <span className="text-xs tracking-widest uppercase opacity-50">Synchronizing...</span>
                  </div>
                )}
              </div>
            </div>
          </>
        ) : activeQueue === 'proposals' && selectedProposal ? (
          <>
            <div className="h-20 border-b border-slate-800/30 flex items-center justify-between px-8 relative z-10 backdrop-blur-sm">
              <div className="flex items-center gap-4 min-w-0">
                <div className="w-10 h-10 rounded-full flex items-center justify-center border border-purple-500/30 bg-purple-500/10 text-purple-300">
                  <FileText size={18} />
                </div>
                <div className="min-w-0 flex flex-col">
                  <h2 className="text-lg font-medium text-slate-100 truncate tracking-tight flex items-center gap-3">
                    <span>{selectedProposal.review_stage === 'ready_memory' ? t('review.review_this_memory') : t('review.review_raw_material')}</span>
                    <span className="text-[10px] px-2 py-0.5 rounded bg-purple-500/10 text-purple-300 border border-purple-500/20 tracking-widest font-mono uppercase">
                      {t('review.waiting_for_you')}
                    </span>
                  </h2>
                  <div className="flex items-center gap-2 text-xs text-slate-500">
                    <span className="bg-slate-800/50 px-1.5 py-0.5 rounded text-slate-400 capitalize">
                      {selectedProposal.candidate_kind || 'unknown'} / {selectedProposal.source_type || 'unknown'}
                    </span>
                    <span className="text-slate-600 font-mono truncate">
                      {selectedProposal.namespace || 'public'}
                    </span>
                  </div>
                </div>
              </div>
              <div className="flex items-center gap-3">
                <button
                  onClick={loadProposals}
                  disabled={proposalActionLoading}
                  className="px-4 py-2 bg-slate-900 hover:bg-slate-800 border border-slate-700 text-slate-400 hover:text-slate-200 rounded-md transition-all duration-200 text-xs font-medium uppercase tracking-wider disabled:opacity-50"
                >
                  {t('review.refresh')}
                </button>
                <button
                  onClick={handleRejectProposal}
                  disabled={proposalActionLoading}
                  className="flex items-center gap-2 px-4 py-2 bg-slate-900 hover:bg-rose-950/30 border border-slate-700 hover:border-rose-800 text-slate-400 hover:text-rose-400 rounded-md transition-all duration-200 text-xs font-medium uppercase tracking-wider disabled:opacity-50"
                >
                  <RotateCcw size={14} /> {t('review.reject_suggestion')}
                </button>
                <button
                  onClick={handleApproveProposal}
                  disabled={proposalActionLoading || !proposalEligibleForDirectApproval}
                  title={!proposalEligibleForDirectApproval ? t('review.direct_approval_unavailable') : t('review.approve_title')}
                  className="flex items-center gap-2 px-5 py-2 bg-purple-600/10 hover:bg-purple-500/20 border border-purple-500/30 hover:border-purple-500/50 text-purple-300 hover:text-purple-200 rounded-md transition-all duration-200 text-xs font-bold uppercase tracking-wider disabled:opacity-40 disabled:cursor-not-allowed disabled:border-slate-700 disabled:bg-slate-900/40 disabled:text-slate-500"
                >
                  <Check size={14} /> {t('review.approve_and_write')}
                </button>
              </div>
            </div>

            <div className="flex-1 overflow-y-auto px-8 py-8 custom-scrollbar">
              <div className="max-w-4xl mx-auto space-y-6">
                <SafetyValveNote />
                <div className="rounded-2xl border border-purple-500/20 bg-gradient-to-br from-purple-500/10 via-slate-900/60 to-indigo-500/5 p-6 shadow-[0_0_40px_rgba(124,58,237,0.10)]">
                  <div className="text-xs font-bold uppercase tracking-widest text-purple-300 mb-2">{t('review.what_to_do_title')}</div>
                  <p className="text-base text-slate-200 leading-7">
                    {proposalStillRedacted ? t('review.redacted_warning') : (selectedProposal.review_stage === 'ready_memory' ? t('review.what_to_do_desc') : t('review.raw_material_desc'))}
                  </p>
                  <div className="mt-5 grid gap-3 md:grid-cols-3">
                    {[
                      [t('review.step_check'), t('review.step_check_desc'), 'text-sky-300 border-sky-500/20 bg-sky-500/10'],
                      [t('review.step_approve'), proposalEligibleForDirectApproval ? t('review.step_approve_desc') : t('review.step_convert_desc'), proposalEligibleForDirectApproval ? 'text-emerald-300 border-emerald-500/25 bg-emerald-500/10' : 'text-amber-300 border-amber-500/25 bg-amber-500/10'],
                      [t('review.step_undo'), t('review.step_undo_desc'), 'text-indigo-300 border-indigo-500/20 bg-indigo-500/10'],
                    ].map(([label, value, tone]) => (
                      <div key={label} className={clsx("rounded-xl border p-3", tone)}>
                        <div className="text-[10px] font-bold uppercase tracking-[0.18em] opacity-70">{label}</div>
                        <div className="mt-2 text-xs leading-5">{value}</div>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div className="rounded-xl border border-emerald-500/20 bg-emerald-500/5 p-6">
                    <h3 className="text-xs font-bold text-emerald-300 uppercase mb-4 tracking-widest">{selectedProposal.review_stage === 'ready_memory' ? t('review.proposed_memory') : t('review.raw_material_title')}</h3>
                    <div className="text-base text-slate-100 leading-7 whitespace-pre-wrap">{proposalContentText}</div>
                    <div className="mt-3 text-[10px] uppercase tracking-widest text-slate-600">{t('review.length')}: {selectedProposal.content_preview?.length ?? 0}</div>
                  </div>
                  <div className="rounded-xl border border-sky-500/20 bg-sky-500/5 p-6">
                    <h3 className="text-xs font-bold text-sky-300 uppercase mb-4 tracking-widest">{t('review.evidence_for_memory')}</h3>
                    <div className="text-base text-slate-100 leading-7 whitespace-pre-wrap">{proposalEvidenceText}</div>
                    <div className="mt-3 text-[10px] uppercase tracking-widest text-slate-600">{t('review.length')}: {selectedProposal.evidence_preview?.length ?? 0}</div>
                  </div>
                </div>

                {selectedProposal.action_hint_label && (
                  <div className="rounded-xl border border-purple-500/20 bg-gradient-to-br from-purple-500/10 to-indigo-500/5 p-5 shadow-[0_0_30px_rgba(124,58,237,0.08)]">
                    <div className="text-[10px] font-bold uppercase tracking-[0.24em] text-purple-300/80 mb-2">{t('review.system_judgement')}</div>
                    <div className="text-base font-semibold text-slate-100">{selectedProposal.action_hint_label}</div>
                    <p className="mt-2 text-sm leading-6 text-slate-400">{selectedProposal.action_hint_reason}</p>
                    <div className="mt-3 inline-flex rounded-full border border-purple-500/20 bg-purple-500/10 px-3 py-1 text-[10px] font-mono uppercase tracking-wider text-purple-300">
                      {selectedProposal.action_hint_action}
                    </div>
                  </div>
                )}

                {proposalActionError && (
                  <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 p-4 text-sm text-rose-300 break-words">
                    {proposalActionError}
                  </div>
                )}

                <div className="grid grid-cols-2 gap-4">
                  {[
                    ['Predicate', selectedProposal.predicate],
                    ['Importance', selectedProposal.importance],
                    ['Confidence', selectedProposal.confidence],
                    ['Risk', selectedProposal.risk],
                    ['Target store', selectedProposal.target_store || 'n/a'],
                    ['Target path', selectedProposal.target_path_present ? selectedProposal.target_path : 'n/a'],
                    ['Readback queries', selectedProposal.readback_query_count],
                    ['Created', selectedProposal.created_at || 'n/a'],
                  ].map(([label, value]) => (
                    <div key={label} className="rounded-lg border border-slate-800/60 bg-slate-900/30 p-4">
                      <div className="text-[10px] uppercase tracking-widest text-slate-600 mb-1">{label}</div>
                      <div className="text-sm text-slate-300 break-words font-mono">{String(value ?? 'n/a')}</div>
                    </div>
                  ))}
                </div>

                <div className="rounded-xl border border-slate-800/60 bg-[#0A0A12]/50 p-6">
                  <h3 className="text-xs font-bold text-slate-500 uppercase mb-4 tracking-widest">{t('review.technical_details')}</h3>
                  <p className="text-sm text-slate-300 whitespace-pre-wrap leading-6">{selectedProposal.reason || selectedProposal.policy_reason || selectedProposal.failure_reason || t('review.no_reason')}</p>
                </div>
              </div>
            </div>
          </>
        ) : diffError ? (
          <div className="flex-1 flex flex-col items-center justify-center text-rose-500 gap-4">
            <Activity size={48} className="opacity-20" />
            <p className="text-sm font-medium opacity-50">Connection Lost</p>
          </div>
        ) : (
          <div className="flex-1 overflow-y-auto px-8 py-8 custom-scrollbar">
            <div className="mx-auto flex min-h-full max-w-4xl flex-col items-center justify-center gap-8 text-slate-700 select-none">
              <SafetyValveNote />
              <div className="relative">
                <div className="absolute inset-0 bg-indigo-500/20 blur-3xl rounded-full opacity-20 animate-pulse"></div>
                <Layout size={64} className="opacity-20 relative z-10" />
              </div>
              <div className="text-center">
                <p className="text-lg font-light text-slate-500">{t('review.awaiting_input')}</p>
                <p className="text-sm text-slate-500 mt-3 max-w-xl leading-6">{t('review.select_fragment')}</p>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function SafetyValveNote() {
  const { t } = useI18n();
  return (
    <div className="w-full rounded-2xl border border-indigo-500/20 bg-gradient-to-br from-indigo-500/10 via-slate-900/60 to-purple-500/5 p-6 shadow-[0_0_40px_rgba(79,70,229,0.08)]">
      <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
        <div className="max-w-2xl">
          <div className="text-xs font-bold uppercase tracking-[0.22em] text-indigo-300 mb-2">{t('review.safety_note_title')}</div>
          <p className="text-base leading-7 text-slate-200">{t('review.safety_note_desc')}</p>
        </div>
        <div className="rounded-xl border border-slate-700/60 bg-slate-950/40 p-4 md:w-72">
          <div className="text-[10px] font-bold uppercase tracking-[0.2em] text-slate-500 mb-2">{t('review.safety_note_when')}</div>
          <p className="text-sm leading-6 text-slate-400">{t('review.safety_note_when_desc')}</p>
        </div>
      </div>
    </div>
  );
}

export default ReviewPage;
