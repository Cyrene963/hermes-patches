import React from 'react';
import { motion } from 'framer-motion';
import { diffLines } from 'diff';

const DiffViewer = ({ oldText, newText }) => {
  const safeOld = oldText || '';
  const safeNew = newText || '';
  const diff = diffLines(safeOld, safeNew);
  const hasChanges = safeOld !== safeNew;

  return (
    <div className="w-full font-sans text-sm leading-7">
      {!hasChanges && (
        <div className="text-slate-500 italic p-4 text-center border border-dashed border-slate-800 rounded-lg">
          No changes detected in content.
        </div>
      )}

      <div className="space-y-1">
        {diff.map((part, index) => {
          if (part.removed) {
            return (
              <motion.div
                key={`removed-${index}`}
                className="group relative bg-red-950/20 hover:bg-red-950/30 transition-colors border-l-2 border-red-900/50 pl-4 pr-2 py-1 select-text"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ duration: 0.1, delay: index * 0.01 }}
              >
                <div className="absolute left-0 top-0 bottom-0 w-[2px] bg-red-800 opacity-50 group-hover:opacity-100 transition-opacity" />
                <span className="text-red-300/50 line-through decoration-red-800/50 font-mono text-xs block mb-1 opacity-50 select-none">REMOVED</span>
                <span className="text-red-200/60 font-serif whitespace-pre-wrap">{part.value}</span>
              </motion.div>
            );
          }

          if (part.added) {
            return (
              <motion.div
                key={`added-${index}`}
                className="group relative bg-emerald-950/20 hover:bg-emerald-950/30 transition-colors border-l-2 border-emerald-500/50 pl-4 pr-2 py-2 my-1 rounded-r select-text"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ duration: 0.1, delay: index * 0.01 }}
              >
                <div className="absolute left-0 top-0 bottom-0 w-[2px] bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.3)]" />
                <span className="text-emerald-500/50 font-mono text-xs block mb-1 opacity-70 select-none">ADDED</span>
                <span className="text-emerald-100 font-medium font-serif whitespace-pre-wrap">{part.value}</span>
              </motion.div>
            );
          }

          // Unchanged lines
          return (
            <div
              key={`unchanged-${index}`}
              className="pl-4 pr-2 py-1 text-slate-400 whitespace-pre-wrap hover:text-slate-300 transition-colors border-l-2 border-transparent hover:border-slate-800/50"
            >
              {part.value}
            </div>
          );
        })}
      </div>
    </div>
  );
};

export default DiffViewer;
