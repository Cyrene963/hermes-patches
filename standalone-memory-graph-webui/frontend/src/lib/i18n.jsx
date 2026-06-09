/**
 * Simple i18n module for Memory Graph frontend.
 * 
 * Provides a React context with a t() translation function.
 * Supports Chinese (zh) and English (en).
 * Language preference stored in localStorage.
 */

import React, { createContext, useContext, useState, useCallback, useEffect } from 'react';

// ─── Translation Data ──────────────────────────────────────────

const translations = {
  en: {
    // Navigation
    'nav.review': 'Memory Safety',
    'nav.memory': 'Memory Explorer',
    'nav.maintenance': 'Brain Cleanup',
    'nav.settings': 'Settings',
    'nav.memory_graph': 'Memory Graph',

    // Common
    'common.search': 'Search',
    'common.save': 'Save',
    'common.cancel': 'Cancel',
    'common.delete': 'Delete',
    'common.loading': 'Loading...',
    'common.error': 'Error',
    'common.retry': 'Retry',
    'common.refresh': 'Refresh',
    'common.close': 'Close',
    'common.edit': 'Edit',
    'common.boot': 'Boot',
    'common.confirm': 'Confirm',
    'common.back': 'Back',
    'common.clear': 'Clear',
    'common.none': '(none)',
    'common.default': '(default)',

    // Login
    'login.title': 'Memory Graph',
    'login.subtitle': 'Sign in to continue',
    'login.username': 'Username',
    'login.password': 'Password',
    'login.sign_in': 'Sign In',
    'login.signing_in': 'Signing in...',
    'login.error_invalid': 'Invalid username or password',
    'login.error_connection': 'Connection failed. Please check the server.',

    // Connection status
    'status.connecting': 'Connecting to Memory Core...',
    'status.cannot_connect': 'Cannot connect to backend',
    'status.check_port': 'Please check that the backend server is running on port 8900.',

    // Review page
    'review.global_review': 'Memory Safety Valve',
    'review.all_namespaces': 'Only for exceptions',
    'review.empty_sequence': 'No memory changes need attention',
    'review.integrate_all': 'Mark all safe',
    'review.integrate_group': 'Mark safe',
    'review.reject_group': 'Undo change',
    'review.awaiting_input': 'Nothing needs your attention',
    'review.select_fragment': 'The agent handles normal memories automatically. Open this page only when something looks risky, wrong, or private.',
    'review.deletion_detected': 'Deletion Detected',
    'review.creation_detected': 'Creation Detected',
    'review.modification_detected': 'Modification Detected',
    'review.no_deviation': 'No Content Deviation',
    'review.path_modifications': 'Path Modifications',
    'review.glossary_keywords': 'Glossary Keywords',
    'review.edge_metadata': 'Edge Metadata',
    'review.initial': '(Initial)',
    'review.removed': '(Removed)',
    'review.preserved': '(Preserved)',
    'review.shifts': 'Shifts',
    'review.added': 'Added',
    'review.rows_affected': 'rows affected',
    'review.node_remains': 'Node remains accessible at:',
    'review.retrieval_failed': 'Memory Retrieval Failed',
    'review.retry_connection': 'Retry Connection',
    'review.connection_lost': 'Connection Lost',
    'review.synchronizing': 'Synchronizing...',
    'review.no_changes': 'No changes detected in content.',
    'review.confirm_reject': 'Reject changes for node group {uri}? This will revert the memory state.',
    'review.confirm_integrate_all': 'Integrate ALL pending memories?',
    'review.backend_offline': 'Disconnected from Neural Core (Backend offline).',
    'review.graph_changes_plain': 'Safety events',
    'review.pending_memories': 'Quarantine',
    'review.waiting_for_review': 'Quarantined',
    'review.review_this_memory': 'Inspect quarantined memory',
    'review.waiting_for_you': 'safety hold',
    'review.reject_suggestion': 'Keep out',
    'review.approve_and_write': 'Release and write',
    'review.what_to_do_title': 'Why is this here?',
    'review.what_to_do_desc': 'Normal low-risk memories are handled automatically. This item is paused because it needs privacy, namespace, confidence, or rollback inspection before release.',
    'review.redacted_warning': 'This item is still redacted. Keep it quarantined until enough content is visible.',
    'review.step_check': '1. Inspect risk',
    'review.step_check_desc': 'Check truth, namespace, privacy, and whether it belongs in long-term memory.',
    'review.step_approve': '2. Release only if safe',
    'review.step_approve_desc': 'Release writes it into Memory Graph after readback verification.',
    'review.step_convert_desc': 'This one needs manual conversion before writing.',
    'review.step_undo': '3. Undoable',
    'review.step_undo_desc': 'Released writes create a rollback record.',
    'review.system_judgement': 'System judgement',
    'review.proposed_memory': 'Quarantined memory',
    'review.evidence_for_memory': 'Why it was paused',
    'review.technical_details': 'Technical details',
    'review.ready_to_confirm': 'safe-release',
    'review.ready_memory_bucket': 'Release candidates',
    'review.raw_material_bucket': 'Source material',
    'review.needs_distillation': 'Needs distillation',
    'review.review_raw_material': 'Review source material',
    'review.raw_material_desc': 'This is chat/source material. It is kept only as evidence for distillation and cannot be written directly as memory.',
    'review.raw_material_title': 'Source material, not memory',
    'review.approve_title': 'Release into Memory Graph with readback verification',
    'review.can_write': 'safe-release',
    'review.needs_conversion': 'needs routing',
    'review.private_source': 'private source',
    'review.graph_changes': 'Graph changes',
    'review.candidates': 'Candidates',
    'review.safety_note_title': 'You normally do not need this page',
    'review.safety_note_desc': 'Hermes writes low-risk memories automatically. This page is the safety valve for privacy, cross-user boundaries, low-confidence suggestions, and rollback after accidents.',
    'review.safety_note_when': 'When should you use it?',
    'review.safety_note_when_desc': 'Use it only if the agent asks, a memory seems wrong, private data may have crossed namespaces, or you want to undo a recent write.',
    'review.no_pending_candidates': 'No quarantined memory needs attention',
    'review.no_pending_candidates_desc': 'Good: the automatic memory pipeline has no risky write paused here. You can leave this page.',
    'review.refresh': 'Refresh',
    'review.reject': 'Keep out',
    'review.approve': 'Release',
    'review.approvable': 'releasable',
    'review.convert': 'route',
    'review.candidate_queue_title': 'Memory OS quarantine queue',
    'review.candidate_queue_desc': 'This panel shows only supervised exceptions from the standalone Memory OS proposal queue. Keeping out only updates proposal status. Release is restricted to target_store=memory_graph candidates, then writes to Memory Graph with readback verification and records a rollbackable Graph changeset.',
    'review.approval_eligibility': 'Release eligibility',
    'review.direct_approval_enabled': 'Direct release enabled',
    'review.conversion_required': 'Conversion required',
    'review.readback': 'Readback',
    'review.readback_will_run': 'Release runs readback verification; success creates a rollbackable Graph changeset.',
    'review.direct_approval_unavailable': 'Direct release unavailable: route this candidate into the suggested private path/skill first.',
    'review.rollback': 'Rollback',
    'review.appears_after_approval': 'Appears under Safety events after release',
    'review.available_after_write': 'Available only after a verified Graph write',
    'review.suggested_route': 'Suggested supervised route',
    'review.policy_reason': 'Policy reason',
    'review.no_reason': 'No reason recorded.',
    'review.candidate_preview': 'Candidate content preview',
    'review.evidence_preview': 'Evidence preview',
    'review.predicate': 'Predicate',
    'review.importance': 'Importance',
    'review.confidence': 'Confidence',
    'review.risk': 'Risk',
    'review.target_store': 'Target store',
    'review.target_path': 'Target path',
    'review.readback_queries': 'Readback queries',
    'review.created': 'Created',
    'review.memory_candidate': 'Memory candidate',
    'review.pending_supervised': 'quarantined · supervised',
    'review.confirm_reject_proposal': 'Keep candidate {id} out? This only updates the proposal queue and does not write canonical memory.',
    'review.confirm_approve_proposal': 'Release candidate {id} into Memory Graph? It will be readback-verified and recorded in Safety events for rollback.',
    'review.only_mg_approvable': 'Only target_store=memory_graph candidates can be released directly. This candidate is target_store={store}.',
    'review.only_ready_memory_approvable': 'Only already-distilled memory candidates can be released. Source material must be summarized first.',
    'review.rejection_failed': 'Rejection failed: ',
    'review.integration_failed': 'Integration failed: ',
    'review.mass_integration_failed': 'Mass integration failed: ',
    'review.length': 'length',
    'review.redacted': '[redacted]',
    'review.unknown_subject': 'Unknown subject',
    'review.deletion_detected_badge': 'Deletion Detected',
    'review.creation_detected_badge': 'Creation Detected',
    'review.modification_detected_badge': 'Modification Detected',
    'review.no_deviation_badge': 'No Content Deviation',

    // Memory Browser
    'memory.core': 'Memory Core',
    'memory.neural_explorer': 'Neural Explorer v2.0',
    'memory.domains': 'Domains',
    'memory.current_path': 'Current Path',
    'memory.search_placeholder': 'Search memories...',
    'memory.retrieving': 'Retrieving Neural Data...',
    'memory.access_denied': 'Access Denied / Error',
    'memory.return_root': 'Return to Root',
    'memory.clusters': 'Memory Clusters',
    'memory.sub_nodes': 'Sub-Nodes',
    'memory.priority': 'Priority',
    'memory.priority_hint': '(lower = higher priority)',
    'memory.disclosure': 'Disclosure',
    'memory.disclosure_hint': '(when to recall)',
    'memory.disclosure_placeholder': 'e.g. When I need to remember...',
    'memory.save_changes': 'Save Changes',
    'memory.saving': 'Saving...',
    'memory.also_reachable': 'Also reachable via:',
    'memory.no_results': 'No results for',
    'memory.results_for': 'result(s) for',
    'memory.back_to_browser': 'Back to browser',
    'memory.delete_confirm': 'Delete this memory',
    'memory.memory': 'Memory',

    // Maintenance
    'maintenance.title': 'Brain Cleanup',
    'maintenance.description': 'Find and clean up orphan memories — deprecated versions from updates and unreachable memories from path deletions.',
    'maintenance.deprecated': 'Deprecated',
    'maintenance.deprecated_desc': 'old versions from updates',
    'maintenance.orphaned': 'Orphaned',
    'maintenance.orphaned_desc': 'unreachable (no paths)',
    'maintenance.access_logs': 'Access Logs',
    'maintenance.no_records': 'No records',
    'maintenance.oldest': 'Oldest',
    'maintenance.orphan_memories': 'Orphan Memories',
    'maintenance.delete_selected': 'Delete {count} selected',
    'maintenance.scanning': 'Scanning for orphans...',
    'maintenance.system_clean': 'System Clean',
    'maintenance.no_orphans': 'No orphan memories detected',
    'maintenance.deprecated_versions': 'Deprecated Versions',
    'maintenance.orphaned_memories': 'Orphaned Memories',
    'maintenance.full_content': 'Full Content',
    'maintenance.old_version': 'Old Version (This Memory)',
    'maintenance.loading_content': 'Loading full content...',
    'maintenance.batch_confirm': 'Permanently delete {count} memories? This cannot be undone.',
    'maintenance.clear_logs_prompt': 'Keep logs for how many days? (Enter 0 to clear all logs)',
    'maintenance.clearing': 'Clearing...',

    // Settings
    'settings.title': 'Settings',
    'settings.description': 'Manage your Memory Graph instance configuration.',
    'settings.general': 'General',
    'settings.database': 'Database',
    'settings.memory': 'Memory',
    'settings.loading': 'Loading settings...',
    'settings.server_config': 'Server Configuration',
    'settings.advanced': 'Developer Mode / Advanced',
    'settings.database_connection': 'Database Connection',
    'settings.boot_uris': 'Boot URIs',
    'settings.memory_domains': 'Memory Domains',

    // Sidebar
    'sidebar.memory': 'Memory',
    'sidebar.root': 'root',

    // Generic actions
    'action.deleting': 'Deleting...',
    'action.saving_changes': 'Saving changes...',
    'action.removing': 'Removing...',
  },

  zh: {
    // Navigation
    'nav.review': '记忆安全阀',
    'nav.memory': '记忆浏览器',
    'nav.maintenance': '记忆清理',
    'nav.settings': '设置',
    'nav.memory_graph': '记忆图谱',

    // Common
    'common.search': '搜索',
    'common.save': '保存',
    'common.cancel': '取消',
    'common.delete': '删除',
    'common.loading': '加载中...',
    'common.error': '错误',
    'common.retry': '重试',
    'common.refresh': '刷新',
    'common.close': '关闭',
    'common.edit': '编辑',
    'common.boot': '启动',
    'common.confirm': '确认',
    'common.back': '返回',
    'common.clear': '清除',
    'common.none': '（无）',
    'common.default': '（默认）',

    // Login
    'login.title': '记忆图谱',
    'login.subtitle': '登录以继续',
    'login.username': '用户名',
    'login.password': '密码',
    'login.sign_in': '登录',
    'login.signing_in': '登录中...',
    'login.error_invalid': '用户名或密码错误',
    'login.error_connection': '连接失败，请检查服务器状态。',

    // Connection status
    'status.connecting': '正在连接记忆核心...',
    'status.cannot_connect': '无法连接后端服务',
    'status.check_port': '请检查后端服务器是否在端口 8900 上运行。',

    // Review page
    'review.global_review': '记忆安全阀',
    'review.all_namespaces': '只处理异常',
    'review.empty_sequence': '没有需要你处理的记忆变更',
    'review.integrate_all': '全部标记安全',
    'review.integrate_group': '标记安全',
    'review.reject_group': '撤销变更',
    'review.awaiting_input': '现在没有需要你处理的事',
    'review.select_fragment': '普通记忆由 Hermes 自动处理。只有发现风险、写错、串用户、隐私问题，才需要打开这里。',
    'review.deletion_detected': '检测到删除',
    'review.creation_detected': '检测到新增',
    'review.modification_detected': '检测到修改',
    'review.no_deviation': '内容无变化',
    'review.path_modifications': '路径变更',
    'review.glossary_keywords': '术语关键词',
    'review.edge_metadata': '边元数据',
    'review.initial': '（初始）',
    'review.removed': '（已移除）',
    'review.preserved': '（已保留）',
    'review.shifts': '变更',
    'review.added': '已添加',
    'review.rows_affected': '行受影响',
    'review.node_remains': '节点仍可通过以下路径访问：',
    'review.retrieval_failed': '记忆检索失败',
    'review.retry_connection': '重试连接',
    'review.connection_lost': '连接断开',
    'review.synchronizing': '同步中...',
    'review.no_changes': '内容未检测到变更。',
    'review.confirm_reject': '确认回滚节点组 {uri} 的变更？这将恢复记忆状态。',
    'review.confirm_integrate_all': '确认把所有待处理异常标记为安全？',
    'review.backend_offline': '与核心断开连接（后端离线）。',
    'review.graph_changes_plain': '安全事件',
    'review.pending_memories': '隔离区',
    'review.waiting_for_review': '已隔离',
    'review.review_this_memory': '检查隔离记忆',
    'review.waiting_for_you': '安全暂停',
    'review.reject_suggestion': '继续隔离',
    'review.approve_and_write': '放行并写入',
    'review.what_to_do_title': '为什么它在这里？',
    'review.what_to_do_desc': '普通低风险记忆会自动处理。这条被暂停，是因为需要检查隐私、命名空间、置信度或回滚风险后才能放行。',
    'review.redacted_warning': '这条仍然被遮住。内容不够可见时，继续留在隔离区。',
    'review.step_check': '1. 检查风险',
    'review.step_check_desc': '检查真实性、命名空间、隐私边界，以及是否值得长期记住。',
    'review.step_approve': '2. 安全才放行',
    'review.step_approve_desc': '放行后写入 Memory Graph，并自动执行读回验证。',
    'review.step_convert_desc': '这条不能直接写，需要先转成技能/规则/私有记忆。',
    'review.step_undo': '3. 可回滚',
    'review.step_undo_desc': '放行写入成功后会产生变更记录，之后可撤销。',
    'review.system_judgement': '系统判断',
    'review.proposed_memory': '隔离中的记忆',
    'review.evidence_for_memory': '为什么被暂停',
    'review.technical_details': '技术细节',
    'review.ready_to_confirm': '可放行',
    'review.ready_memory_bucket': '可放行候选',
    'review.raw_material_bucket': '待蒸馏素材',
    'review.needs_distillation': '待蒸馏',
    'review.review_raw_material': '查看待蒸馏素材',
    'review.raw_material_desc': '这只是聊天/外部对话原文，用来做证据材料；还没有被归纳成稳定记忆，不能直接写入 Memory Graph。',
    'review.raw_material_title': '原始素材，不是记忆',
    'review.approve_title': '放行到 Memory Graph 并执行读回验证',
    'review.can_write': '可放行',
    'review.needs_conversion': '需路由',
    'review.private_source': '私有来源',
    'review.graph_changes': '图谱变更',
    'review.candidates': '候选队列',
    'review.safety_note_title': '你平时不用管这个页面',
    'review.safety_note_desc': '低风险记忆会自动写入、读回验证、未来自动调用。这里不是让你每天手动审核，而是隐私、跨用户、低置信候选、事故回滚的安全阀。',
    'review.safety_note_when': '什么时候才需要用？',
    'review.safety_note_when_desc': '只有当 agent 提醒你、你发现记忆不对、怀疑私密内容进错命名空间，或想撤销最近写入时才用。',
    'review.no_pending_candidates': '没有需要处理的隔离记忆',
    'review.no_pending_candidates_desc': '这是好事：自动记忆管道没有把高风险写入暂停在这里。可以直接离开这个页面。',
    'review.refresh': '刷新',
    'review.reject': '继续隔离',
    'review.approve': '放行',
    'review.approvable': '可放行',
    'review.convert': '需路由',
    'review.candidate_queue_title': 'Memory OS 隔离队列',
    'review.candidate_queue_desc': '此面板只显示独立 Memory OS 候选队列里的受监督异常。继续隔离只更新候选状态；放行仅限 target_store=memory_graph 的候选，将写入记忆图谱并经读回验证，同时记录可回滚的图谱变更集。',
    'review.approval_eligibility': '放行资格',
    'review.direct_approval_enabled': '可直接放行',
    'review.conversion_required': '需要转换',
    'review.readback': '读回验证',
    'review.readback_will_run': '放行时将执行读回验证；成功后创建可回滚的图谱变更集。',
    'review.direct_approval_unavailable': '无法直接放行：请先将此候选路由到建议的私有路径/技能。',
    'review.rollback': '回滚',
    'review.appears_after_approval': '放行后显示在安全事件中',
    'review.available_after_write': '仅在验证写入图谱后可用',
    'review.suggested_route': '建议的监督路由',
    'review.policy_reason': '策略原因',
    'review.no_reason': '未记录原因。',
    'review.candidate_preview': '候选内容预览',
    'review.evidence_preview': '证据预览',
    'review.predicate': '谓词',
    'review.importance': '重要性',
    'review.confidence': '置信度',
    'review.risk': '风险',
    'review.target_store': '目标存储',
    'review.target_path': '目标路径',
    'review.readback_queries': '读回查询数',
    'review.created': '创建时间',
    'review.memory_candidate': '记忆候选',
    'review.pending_supervised': '已隔离 · 受监督',
    'review.confirm_reject_proposal': '确认继续隔离候选 {id}？此操作仅更新候选队列状态，不写入正式记忆。',
    'review.confirm_approve_proposal': '确认放行候选 {id} 进入记忆图谱？将执行读回验证并记录在安全事件中以便回滚。',
    'review.only_mg_approvable': '仅 target_store=memory_graph 的候选可直接放行。此候选为 target_store={store}。',
    'review.only_ready_memory_approvable': '只有已经蒸馏好的记忆候选才能放行；原始素材必须先归纳成稳定记忆。',
    'review.rejection_failed': '拒绝失败：',
    'review.integration_failed': '采纳失败：',
    'review.mass_integration_failed': '批量采纳失败：',
    'review.length': '长度',
    'review.redacted': '[已脱敏]',
    'review.unknown_subject': '未知主题',
    'review.deletion_detected_badge': '检测到删除',
    'review.creation_detected_badge': '检测到新增',
    'review.modification_detected_badge': '检测到修改',
    'review.no_deviation_badge': '内容无变化',

    // Memory Browser
    'memory.core': '记忆核心',
    'memory.neural_explorer': '神经探索器 v2.0',
    'memory.domains': '域',
    'memory.current_path': '当前路径',
    'memory.search_placeholder': '搜索记忆...',
    'memory.retrieving': '正在检索神经数据...',
    'memory.access_denied': '访问被拒绝 / 错误',
    'memory.return_root': '返回根节点',
    'memory.clusters': '记忆集群',
    'memory.sub_nodes': '子节点',
    'memory.priority': '优先级',
    'memory.priority_hint': '（越小优先级越高）',
    'memory.disclosure': '触发条件',
    'memory.disclosure_hint': '（何时回忆）',
    'memory.disclosure_placeholder': '例如：当我需要记住...',
    'memory.save_changes': '保存更改',
    'memory.saving': '保存中...',
    'memory.also_reachable': '也可通过以下路径访问：',
    'memory.no_results': '无搜索结果：',
    'memory.results_for': '搜索结果：',
    'memory.back_to_browser': '返回浏览器',
    'memory.delete_confirm': '删除此记忆',
    'memory.memory': '记忆',

    // Maintenance
    'maintenance.title': '记忆清理',
    'maintenance.description': '查找并清理孤立记忆——更新产生的旧版本和路径删除后无法访问的记忆。',
    'maintenance.deprecated': '已弃用',
    'maintenance.deprecated_desc': '更新产生的旧版本',
    'maintenance.orphaned': '孤立',
    'maintenance.orphaned_desc': '无法访问（无路径）',
    'maintenance.access_logs': '访问日志',
    'maintenance.no_records': '无记录',
    'maintenance.oldest': '最早',
    'maintenance.orphan_memories': '孤立记忆',
    'maintenance.delete_selected': '删除选中的 {count} 项',
    'maintenance.scanning': '正在扫描孤立记忆...',
    'maintenance.system_clean': '系统清洁',
    'maintenance.no_orphans': '未检测到孤立记忆',
    'maintenance.deprecated_versions': '已弃用版本',
    'maintenance.orphaned_memories': '孤立记忆',
    'maintenance.full_content': '完整内容',
    'maintenance.old_version': '旧版本（此记忆）',
    'maintenance.loading_content': '正在加载完整内容...',
    'maintenance.batch_confirm': '确认永久删除 {count} 条记忆？此操作不可撤销。',
    'maintenance.clear_logs_prompt': '保留最近多少天的日志？（输入 0 清除所有日志）',
    'maintenance.clearing': '清除中...',

    // Settings
    'settings.title': '设置',
    'settings.description': '管理记忆图谱实例配置。',
    'settings.general': '通用',
    'settings.database': '数据库',
    'settings.memory': '记忆',
    'settings.loading': '加载设置中...',
    'settings.server_config': '服务器配置',
    'settings.advanced': '开发者模式 / 高级',
    'settings.database_connection': '数据库连接',
    'settings.boot_uris': '启动 URI',
    'settings.memory_domains': '记忆域',

    // Sidebar
    'sidebar.memory': '记忆',
    'sidebar.root': '根',

    // Generic actions
    'action.deleting': '删除中...',
    'action.saving_changes': '保存更改中...',
    'action.removing': '移除中...',
  },
};

// ─── Language Context ──────────────────────────────────────────

const LANG_KEY = 'mg_language';

const defaultLang = (() => {
  try {
    const stored = localStorage.getItem(LANG_KEY);
    if (stored && translations[stored]) return stored;
  } catch {}
  // Auto-detect from browser
  const browserLang = navigator.language || navigator.userLanguage || 'en';
  return browserLang.startsWith('zh') ? 'zh' : 'en';
})();

const I18nContext = createContext({
  lang: defaultLang,
  setLang: () => {},
  t: (key, params) => key,
});

export function I18nProvider({ children }) {
  const [lang, setLangState] = useState(defaultLang);

  const setLang = useCallback((newLang) => {
    setLangState(newLang);
    try {
      localStorage.setItem(LANG_KEY, newLang);
    } catch {}
  }, []);

  const t = useCallback((key, params = {}) => {
    const dict = translations[lang] || translations.en;
    let text = dict[key] || translations.en[key] || key;
    // Simple parameter substitution: {name} -> params.name
    for (const [k, v] of Object.entries(params)) {
      text = text.replace(`{${k}}`, String(v));
    }
    return text;
  }, [lang]);

  return (
    <I18nContext.Provider value={{ lang, setLang, t }}>
      {children}
    </I18nContext.Provider>
  );
}

export function useI18n() {
  return useContext(I18nContext);
}

// ─── Language Toggle Button Component ──────────────────────────

export function LanguageToggle() {
  const { lang, setLang } = useI18n();
  return (
    <button
      onClick={() => setLang(lang === 'zh' ? 'en' : 'zh')}
      className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium transition-colors text-slate-400 hover:text-slate-200 hover:bg-slate-800/50"
      title={lang === 'zh' ? 'Switch to English' : '切换到中文'}
    >
      <span className="text-xs font-mono">
        {lang === 'zh' ? 'EN' : '中'}
      </span>
    </button>
  );
}

export default I18nContext;
