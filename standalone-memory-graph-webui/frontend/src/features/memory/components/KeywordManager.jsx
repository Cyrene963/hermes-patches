import React, { useState, useEffect, useRef } from 'react';
import { Tag, X, Save, Plus } from 'lucide-react';
import { api } from '../../../lib/api';

const KeywordManager = ({ keywords, nodeUuid, onUpdate }) => {
  const [adding, setAdding] = useState(false);
  const [newKeyword, setNewKeyword] = useState('');
  const inputRef = useRef(null);

  useEffect(() => {
    if (adding && inputRef.current) inputRef.current.focus();
  }, [adding]);

  const handleAdd = async () => {
    const kw = newKeyword.trim();
    if (!kw || !nodeUuid) return;
    try {
      await api.post('/browse/glossary', { keyword: kw, node_uuid: nodeUuid });
      setNewKeyword('');
      setAdding(false);
      onUpdate();
    } catch (err) {
      alert('Failed to add keyword: ' + (err.response?.data?.detail || err.message));
    }
  };

  const handleRemove = async (kw) => {
    if (!nodeUuid) return;
    try {
      await api.delete('/browse/glossary', { data: { keyword: kw, node_uuid: nodeUuid } });
      onUpdate();
    } catch (err) {
      alert('Failed to remove keyword: ' + (err.response?.data?.detail || err.message));
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter') handleAdd();
    if (e.key === 'Escape') { setAdding(false); setNewKeyword(''); }
  };

  return (
    <div className="flex items-start gap-2 text-xs text-slate-500">
      <Tag size={13} className="flex-shrink-0 mt-0.5 text-amber-700" />
      <div className="flex flex-wrap gap-1.5 items-center">
        <span className="text-amber-700 font-medium">Glossary:</span>
        {keywords.map(kw => (
          <span
            key={kw}
            className="inline-flex items-center gap-1 px-1.5 py-0.5 bg-amber-950/30 border border-amber-800/30 rounded text-amber-400/80 font-mono text-[11px]"
          >
            {kw}
            <button
              onClick={() => handleRemove(kw)}
              className="text-amber-700 hover:text-amber-400 transition-colors"
            >
              <X size={9} />
            </button>
          </span>
        ))}
        {adding ? (
          <span className="inline-flex items-center gap-1">
            <input
              ref={inputRef}
              type="text"
              value={newKeyword}
              onChange={e => setNewKeyword(e.target.value)}
              onKeyDown={handleKeyDown}
              onBlur={() => { if (!newKeyword.trim()) setAdding(false); }}
              placeholder="keyword..."
              className="w-28 px-1.5 py-0.5 bg-slate-900 border border-amber-800/40 rounded text-amber-300 text-[11px] font-mono focus:outline-none focus:border-amber-500/50"
            />
            <button onClick={handleAdd} className="text-amber-600 hover:text-amber-400 transition-colors">
              <Save size={11} />
            </button>
          </span>
        ) : (
          <button
            onClick={() => setAdding(true)}
            className="inline-flex items-center gap-0.5 px-1.5 py-0.5 border border-dashed border-amber-800/30 rounded text-amber-700 hover:text-amber-400 hover:border-amber-600/40 transition-colors text-[11px]"
          >
            <Plus size={9} /> add
          </button>
        )}
      </div>
    </div>
  );
};

export default KeywordManager;
