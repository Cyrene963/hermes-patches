import React, { useState } from 'react';
import { motion } from 'framer-motion';
import { ChevronRight, Folder, FileText, AlertTriangle, Link2, Zap } from 'lucide-react';
import clsx from 'clsx';
import PriorityBadge from './PriorityBadge';
import VisibilityBadge from './VisibilityBadge';

const NodeGridCard = ({ node, currentDomain, isInBoot, onBootToggle, onClick }) => {
  const [isHovered, setIsHovered] = useState(false);
  const isCrossDomain = node.domain && node.domain !== currentDomain;

  const handleBootClick = (e) => {
    e.stopPropagation();
    onBootToggle?.();
  };

  return (
    <motion.button
      onClick={onClick}
      onHoverStart={() => setIsHovered(true)}
      onHoverEnd={() => setIsHovered(false)}
      className={clsx(
        "group relative flex flex-col items-start p-4 sm:p-5 bg-[#0A0A12] border rounded-xl text-left w-full h-full overflow-hidden transition-all duration-200",
        isInBoot
          ? "border-amber-800/40 hover:border-amber-600/50"
          : isCrossDomain
            ? "border-violet-800/40 hover:border-violet-500/40"
            : "border-slate-800/50 hover:border-indigo-500/30"
      )}
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      whileHover={{ y: -2 }}
      whileTap={{ scale: 0.98 }}
      transition={{ duration: 0.2 }}
    >
      {/* Gradient overlay on hover */}
      <div
        className={clsx(
          "absolute inset-0 bg-gradient-to-br from-indigo-500/5 via-transparent to-transparent transition-opacity duration-200",
          isHovered ? "opacity-100" : "opacity-0"
        )}
      />

      <div className="flex items-center gap-2 sm:gap-3 mb-2 sm:mb-3 w-full relative z-10">
        <div className="p-1.5 sm:p-2 rounded-lg bg-slate-900 group-hover:bg-indigo-900/20 text-slate-500 group-hover:text-indigo-400 transition-colors flex-shrink-0">
          {node.approx_children_count > 0 ? <Folder size={16} className="sm:w-[18px] sm:h-[18px]" /> : <FileText size={16} className="sm:w-[18px] sm:h-[18px]" />}
        </div>
        <div className="min-w-0 flex-1">
          <h3 className="text-xs sm:text-sm font-semibold text-slate-300 group-hover:text-indigo-200 transition-colors break-words line-clamp-2">
            {node.name || node.path.split('/').pop()}
          </h3>
          {isCrossDomain && (
            <span className="inline-flex items-center gap-1 mt-1 px-1.5 py-0.5 text-[9px] sm:text-[10px] font-mono text-violet-400/80 bg-violet-950/40 border border-violet-800/30 rounded">
              <Link2 size={8} className="sm:w-[9px] sm:h-[9px]" />
              {node.domain}://
            </span>
          )}
        </div>

        <div className="flex items-center gap-1 sm:gap-1.5 flex-shrink-0">
          <PriorityBadge priority={node.priority} />
          <VisibilityBadge namespace={node.namespace} visibilityLabel={node.visibility_label} securityLevel={node.security_level} compact />
          <motion.div
            onClick={handleBootClick}
            title={isInBoot ? "Remove from Boot" : "Add to Boot"}
            className={clsx(
              "p-1 rounded-md transition-all cursor-pointer",
              isInBoot
                ? "text-amber-400 bg-amber-950/50 border border-amber-700/40"
                : "text-slate-700 border border-transparent opacity-0 group-hover:opacity-100"
            )}
            whileHover={{ scale: 1.1 }}
            whileTap={{ scale: 0.9 }}
          >
            <Zap size={12} className={clsx("sm:w-[13px] sm:h-[13px]", isInBoot && "fill-amber-400")} />
          </motion.div>
        </div>
      </div>

      {node.disclosure && (
        <div className="w-full mb-2">
          <p className="text-[10px] sm:text-[11px] text-amber-500/70 leading-snug line-clamp-2 flex items-start gap-1">
            <AlertTriangle size={10} className="sm:w-[11px] sm:h-[11px] flex-shrink-0 mt-0.5" />
            <span className="italic">{node.disclosure}</span>
          </p>
        </div>
      )}

      <div className="w-full flex-1 relative z-10">
        {node.content_snippet ? (
          <p className="text-xs text-slate-500 leading-relaxed line-clamp-3">
            {node.content_snippet}
          </p>
        ) : (
          <p className="text-xs text-slate-700 italic">No preview available</p>
        )}
      </div>

      {/* Arrow indicator */}
      <ChevronRight
        size={14}
        className={clsx(
          "absolute bottom-3 sm:bottom-4 right-3 sm:right-4 text-indigo-500/50 transition-opacity duration-200",
          isHovered ? "opacity-100" : "opacity-0"
        )}
      />
    </motion.button>
  );
};

export default NodeGridCard;
