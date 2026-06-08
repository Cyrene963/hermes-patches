import axios from 'axios';

export const AUTH_ERROR_EVENT = 'memory-graph:auth-error';

export const api = axios.create({
  baseURL: '/api',
  withCredentials: true,
});

// Request interceptor: attach X-Namespace (no Bearer token, cookies are automatic)
api.interceptors.request.use((config) => {
  config.headers = config.headers ?? {};
  const ns = localStorage.getItem('selected_namespace');
  if (ns && !config.url.startsWith('/review')) {
    config.headers['X-Namespace'] = ns;
  }
  return config;
});

// Response interceptor: 401 triggers re-auth
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response && error.response.status === 401) {
      window.dispatchEvent(new CustomEvent(AUTH_ERROR_EVENT));
    }
    return Promise.reject(error);
  }
);

const encodeId = (id) => encodeURIComponent(id);

// ============ Auth API ============

export const login = (username, password) =>
  api.post('/auth/login', { username, password }).then(res => res.data);

export const logout = () =>
  api.post('/auth/logout').then(res => res.data);

export const getMe = () =>
  api.get('/auth/me').then(res => res.data);

// ============ Review API ============

export const getGroups = () =>
  api.get('/review/groups').then(res => res.data);

export const getGroupDiff = (nodeUuid) =>
  api.get(`/review/groups/${encodeId(nodeUuid)}/diff`).then(res => res.data);

export const rollbackGroup = (nodeUuid) =>
  api.post(`/review/groups/${encodeId(nodeUuid)}/rollback`, {}).then(res => res.data);

export const approveGroup = (nodeUuid) =>
  api.delete(`/review/groups/${encodeId(nodeUuid)}`).then(res => res.data);

export const clearAll = () =>
  api.delete('/review').then(res => res.data);

export const getProposalInbox = ({ status = 'pending', limit = 50 } = {}) =>
  api.get('/proposal-review/inbox', { params: { status, limit } }).then(res => res.data);

export const rejectProposal = (proposalId, reason) =>
  api.post(`/proposal-review/proposals/${encodeId(proposalId)}/reject`, { reason }).then(res => res.data);

export const approveProposal = (proposalId, reason) =>
  api.post(`/proposal-review/proposals/${encodeId(proposalId)}/approve`, { reason }).then(res => res.data);

// ============ Browse API ============

export const getDomains = () =>
  api.get('/browse/domains').then(res => res.data);

export const getNamespaces = () =>
  api.get('/browse/namespaces').then(res => res.data);

export const deleteNode = (domain, path) =>
  api.delete('/browse/node', { params: { domain, path } }).then(res => res.data);

export const searchMemories = (q, { domain, limit } = {}) =>
  api.get('/browse/search', { params: { q, domain, limit } }).then(res => res.data);

// ============ Settings API ============

export const getSettings = () =>
  api.get('/settings').then(res => res.data);

export const updateSettings = (data) =>
  api.put('/settings', data).then(res => res.data);

export const getSettingsBootUris = () =>
  api.get('/settings/boot-uris').then(res => res.data);

export const setSettingsBootUris = (uris) =>
  api.put('/settings/boot-uris', { uris }).then(res => res.data);

export const toggleSettingsBootUri = (uri, enabled) =>
  api.patch('/settings/boot-uris', { uri, enabled }).then(res => res.data);

export const getAllBootUris = () =>
  api.get('/settings/boot-uris/all').then(res => res.data.boot_uris);

const _nsSlug = (ns) => encodeURIComponent(ns || '_ns_default_0x7f3a9e');

export const setBootUrisForNs = (namespace, uris) =>
  api.put(`/settings/boot-uris/ns/${_nsSlug(namespace)}`, { uris }).then(res => res.data);

export const deleteBootUrisForNs = (namespace) =>
  api.delete(`/settings/boot-uris/ns/${_nsSlug(namespace)}`).then(res => res.data);

export const getDatabaseStatus = () =>
  api.get('/settings/database/status').then(res => res.data);

export const testDatabase = (database_url) =>
  api.post('/settings/database/test', { database_url }).then(res => res.data);

export default api;
