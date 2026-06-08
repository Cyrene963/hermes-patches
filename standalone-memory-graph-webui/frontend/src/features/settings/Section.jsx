import React, { useState } from 'react';
import { ChevronDown, ChevronUp } from 'lucide-react';

export default function Section({ icon: Icon, title, children, defaultOpen = true }) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div className="bg-slate-900/80 border border-slate-700/50 rounded-xl overflow-hidden mb-4 shadow-sm backdrop-blur-sm">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-3 px-5 py-4 hover:bg-slate-800/50 transition-colors"
      >
        <div className="text-slate-400 flex items-center justify-center">
          <Icon size={18} />
        </div>
        <span className="font-semibold text-slate-200">{title}</span>
        <div className="ml-auto">
          {open ? <ChevronUp size={16} className="text-slate-500" /> : <ChevronDown size={16} className="text-slate-500" />}
        </div>
      </button>
      {open && <div className="px-5 pb-5 pt-2 border-t border-slate-700/50">{children}</div>}
    </div>
  );
}
