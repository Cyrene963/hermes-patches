import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { createPortal } from 'react-dom';
import { BookOpen, X } from 'lucide-react';
import clsx from 'clsx';

function findAllOccurrences(text, keywords) {
  if (!keywords || keywords.length === 0 || !text) return [];

  const matches = [];
  for (const entry of keywords) {
    if (!entry.keyword) continue;
    let idx = text.indexOf(entry.keyword);
    while (idx !== -1) {
      matches.push({
        start: idx,
        end: idx + entry.keyword.length,
        keyword: entry.keyword,
        nodes: entry.nodes,
      });
      idx = text.indexOf(entry.keyword, idx + entry.keyword.length);
    }
  }

  matches.sort((a, b) => a.start - b.start || (b.end - b.start) - (a.end - a.start));

  const result = [];
  let lastEnd = -1;
  for (const m of matches) {
    if (m.start >= lastEnd) {
      result.push(m);
      lastEnd = m.end;
    }
  }
  return result;
}

const GlossaryPopup = ({ keyword, nodes, position, onClose, onNavigate }) => {
  const popupRef = useRef(null);

  useEffect(() => {
    const handleClickOutside = (e) => {
      if (popupRef.current && !popupRef.current.contains(e.target)) {
        onClose();
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [onClose]);

  return createPortal(
    <div
      ref={popupRef}
      className="fixed z-[100] w-72 bg-[#0E0E18] border border-amber-800/40 rounded-xl shadow-2xl shadow-black/60 overflow-hidden flex flex-col"
      style={{ 
        left: position.x, 
        ...(position.isAbove 
          ? { bottom: window.innerHeight - position.spanTop + 4, maxHeight: position.spanTop - 16 } 
          : { top: position.y + 4, maxHeight: window.innerHeight - position.y - 16 })
      }}
    >
      <div className="px-3 py-2 border-b border-slate-800/60 flex items-center gap-2 flex-shrink-0">
        <BookOpen size={12} className="text-amber-400" />
        <span className="text-xs font-semibold text-amber-300">{keyword}</span>
        <button onClick={onClose} className="ml-auto text-slate-600 hover:text-slate-400 transition-colors">
          <X size={12} />
        </button>
      </div>
      <div className="p-2 overflow-y-auto custom-scrollbar flex-1">
        {nodes.map((node, i) => {
          const isUnlinked = node.uri?.startsWith('unlinked://');
          return (
          <button
            key={node.uri || i}
            onClick={() => {
              if (isUnlinked) return;
              const match = node.uri?.match(/^([^:]+):\/\/(.*)$/);
              if (match) onNavigate(match[2], match[1]);
              onClose();
            }}
            className={clsx(
              "w-full text-left px-2.5 py-2 rounded-lg transition-colors group relative",
              isUnlinked ? "cursor-default opacity-80 bg-slate-900/40" : "hover:bg-slate-800/60 cursor-pointer"
            )}
          >
            <div className="flex items-center justify-between gap-2">
              <code className={clsx(
                "text-[11px] font-mono block truncate flex-1",
                isUnlinked ? "text-slate-500" : "text-indigo-400/80 group-hover:text-indigo-300"
              )}>
                {node.uri}
              </code>
              {isUnlinked && (
                <span className="text-[9px] px-1.5 py-0.5 bg-rose-950/40 text-rose-400 border border-rose-900/50 rounded flex-shrink-0">
                  Orphaned
                </span>
              )}
            </div>
            {node.content_snippet && (
              <p className="text-[10px] text-slate-600 mt-0.5 line-clamp-2 leading-snug">
                {node.content_snippet}
              </p>
            )}
          </button>
        )})}
      </div>
    </div>,
    document.body
  );
};

const GlossaryHighlighter = ({ content, glossary, currentNodeUuid, onNavigate }) => {
  const [popup, setPopup] = useState(null);
  const containerRef = useRef(null);

  useEffect(() => {
    setPopup(null);
  }, [content]);

  const filteredGlossary = useMemo(() => {
    if (!glossary) return [];
    return glossary.map(entry => {
      const filteredNodes = entry.nodes?.filter(n => n.node_uuid !== currentNodeUuid) || [];
      return { ...entry, nodes: filteredNodes };
    }).filter(entry => entry.nodes.length > 0);
  }, [glossary, currentNodeUuid]);

  const matches = useMemo(
    () => findAllOccurrences(content, filteredGlossary),
    [content, filteredGlossary]
  );

  const handleKeywordClick = useCallback((e, match) => {
    const spanRect = e.target.getBoundingClientRect();
    
    const popupWidth = 288;
    let x = spanRect.left;
    if (x + popupWidth > window.innerWidth - 16) {
      x = window.innerWidth - popupWidth - 16;
      if (x < 16) x = 16;
    }

    const estimatedHeight = 250;
    let y = spanRect.bottom;
    let isAbove = false;
    
    if (y + estimatedHeight > window.innerHeight - 16 && spanRect.top > estimatedHeight + 16) {
      isAbove = true;
    }

    setPopup({
      keyword: match.keyword,
      nodes: match.nodes,
      position: { x, y, isAbove, spanTop: spanRect.top },
    });
  }, []);

  if (matches.length === 0) {
    return <pre className="whitespace-pre-wrap font-serif text-slate-300 leading-7">{content}</pre>;
  }

  const parts = [];
  let lastIdx = 0;
  for (const m of matches) {
    if (m.start > lastIdx) {
      parts.push({ text: content.slice(lastIdx, m.start), isMatch: false });
    }
    parts.push({ text: content.slice(m.start, m.end), isMatch: true, match: m });
    lastIdx = m.end;
  }
  if (lastIdx < content.length) {
    parts.push({ text: content.slice(lastIdx), isMatch: false });
  }

  return (
    <div ref={containerRef} className="relative">
      <pre className="whitespace-pre-wrap font-serif text-slate-300 leading-7">
        {parts.map((part, i) =>
          part.isMatch ? (
            <span
              key={i}
              className="text-amber-300 cursor-pointer underline decoration-dotted decoration-amber-600/50 hover:decoration-amber-400 hover:text-amber-200 transition-colors"
              onClick={(e) => handleKeywordClick(e, part.match)}
            >
              {part.text}
            </span>
          ) : (
            <React.Fragment key={i}>{part.text}</React.Fragment>
          )
        )}
      </pre>
      {popup && (
        <GlossaryPopup
          keyword={popup.keyword}
          nodes={popup.nodes}
          position={popup.position}
          onClose={() => setPopup(null)}
          onNavigate={onNavigate}
        />
      )}
    </div>
  );
};

export default GlossaryHighlighter;
