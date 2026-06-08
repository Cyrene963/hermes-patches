import React from 'react';
import { Star } from 'lucide-react';
import clsx from 'clsx';

const PriorityBadge = ({ priority, size = 'sm' }) => {
  if (priority === null || priority === undefined) return null;
  
  const colors = priority === 0
    ? 'bg-rose-950/40 text-rose-400 border-rose-800/40'
    : priority <= 2
    ? 'bg-amber-950/30 text-amber-400 border-amber-800/30'
    : priority <= 5
    ? 'bg-sky-950/30 text-sky-400 border-sky-800/30'
    : 'bg-slate-800/30 text-slate-500 border-slate-700/30';
  
  const sizeClass = size === 'lg' 
    ? 'px-2.5 py-1 text-xs gap-1.5' 
    : 'px-1.5 py-0.5 text-[10px] gap-1';
  
  return (
    <span className={clsx("inline-flex items-center rounded border font-mono font-semibold", colors, sizeClass)}>
      <Star size={size === 'lg' ? 12 : 9} />
      {priority}
    </span>
  );
};

export default PriorityBadge;
