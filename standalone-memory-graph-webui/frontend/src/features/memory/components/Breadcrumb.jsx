import React from 'react';
import { ChevronRight, Home } from 'lucide-react';
import clsx from 'clsx';

const Breadcrumb = ({ items, onNavigate }) => (
  <div className="flex items-center gap-2 overflow-x-auto no-scrollbar mask-linear-fade">
    <button 
      onClick={() => onNavigate('')}
      className="p-1.5 rounded-md hover:bg-slate-800/50 text-slate-500 hover:text-indigo-400 transition-colors"
    >
      <Home size={14} />
    </button>
    
    {items.map((crumb, i) => (
      <React.Fragment key={crumb.path}>
        <ChevronRight size={12} className="text-slate-700 flex-shrink-0" />
        <button
          onClick={() => onNavigate(crumb.path)}
          className={clsx(
            "px-2 py-1 rounded-md text-xs font-medium transition-all whitespace-nowrap",
            i === items.length - 1
              ? "bg-indigo-500/10 text-indigo-300 border border-indigo-500/20"
              : "text-slate-400 hover:text-slate-200 hover:bg-white/5"
          )}
        >
          {crumb.label}
        </button>
      </React.Fragment>
    ))}
  </div>
);

export default Breadcrumb;
