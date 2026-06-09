import React, { useState, useEffect } from 'react';
import { Tag, Plus, Trash2, Save, AlertTriangle } from 'lucide-react';
import { useToast } from '../../components/ui';

export default function DomainsSection({ settings, onSave }) {
  const toast = useToast();
  const [domains, setDomains] = useState([]);
  const [newDomain, setNewDomain] = useState('');
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (settings?.valid_domains) {
      setDomains([...settings.valid_domains]);
    }
  }, [settings?.valid_domains?.join?.(',')]);

  const handleAdd = () => {
    const trimmed = newDomain.trim().toLowerCase();
    if (!trimmed || domains.includes(trimmed)) return;
    if (!/^[a-z][a-z0-9_]*$/.test(trimmed)) {
      toast.warning('Domain 必须以字母开头，只能包含小写字母、数字和下划线。', { title: 'Domain 名称无效' });
      return;
    }
    setDomains([...domains, trimmed]);
    setNewDomain('');
    setDirty(true);
  };

  const handleRemove = (d) => {
    if (d === 'core') {
      toast.warning('core 是系统默认 domain，不能移除。', { title: '不能移除 core' });
      return;
    }
    setDomains(domains.filter(x => x !== d));
    setDirty(true);
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      await onSave({ valid_domains: domains });
      setDirty(false);
      toast.success(`${domains.length} 个 domain 已保存。`, { title: 'Domain 设置已更新' });
    } catch (e) {
      toast.error(e.response?.data?.detail || e.message, { title: '保存 Domain 设置失败' });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-3 pt-4">
      <div className="flex flex-wrap gap-2">
        {domains.map(d => (
          <span key={d} className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-slate-900 border border-slate-700 shadow-sm rounded-lg text-sm text-slate-200">
            <Tag size={12} className="text-slate-500" />
            {d}
            {d !== 'core' && (
              <button onClick={() => handleRemove(d)} className="ml-1 text-slate-500 hover:text-red-400 transition-colors">
                <Trash2 size={12} />
              </button>
            )}
          </span>
        ))}
      </div>

      <div className="flex gap-2">
        <input
          type="text"
          value={newDomain}
          onChange={e => setNewDomain(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && handleAdd()}
          placeholder="new_domain"
          className="bg-slate-950 border border-slate-700 text-slate-200 rounded-lg px-3 py-2 text-sm placeholder:text-slate-600 w-48 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 shadow-inner"
        />
        <button
          onClick={handleAdd}
          disabled={!newDomain.trim()}
          className="px-3 py-2 bg-slate-700 hover:bg-slate-600 disabled:opacity-40 text-slate-200 rounded-lg text-sm flex items-center gap-1.5 transition-colors"
        >
          <Plus size={14} /> Add
        </button>
      </div>

      {dirty && (
        <div className="flex items-center justify-between pt-1">
          <p className="text-xs text-amber-400 flex items-center gap-1">
            <AlertTriangle size={12} /> Requires server restart
          </p>
          <button
            onClick={handleSave}
            disabled={saving}
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
