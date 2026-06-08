import React from 'react';
import { motion } from 'framer-motion';
import clsx from 'clsx';

// 带动画的按钮组件
export const AnimatedButton = ({
  children,
  onClick,
  variant = 'primary',
  disabled = false,
  loading = false,
  icon: Icon,
  className,
  ...props
}) => {
  const variants = {
    primary: "bg-indigo-600/10 hover:bg-indigo-500/20 border border-indigo-500/30 hover:border-indigo-500/50 text-indigo-300 hover:text-indigo-200 shadow-[0_0_15px_rgba(99,102,241,0.1)] hover:shadow-[0_0_25px_rgba(99,102,241,0.2)]",
    danger: "bg-slate-900 hover:bg-rose-950/30 border border-slate-700 hover:border-rose-800 text-slate-400 hover:text-rose-400",
    success: "bg-slate-800/50 hover:bg-emerald-900/20 text-slate-400 hover:text-emerald-400 border border-slate-700 hover:border-emerald-800/50",
  };

  return (
    <motion.button
      onClick={onClick}
      disabled={disabled || loading}
      className={clsx(
        "flex items-center gap-2 px-5 py-2 rounded-md text-xs font-bold uppercase tracking-wider transition-all duration-300 disabled:opacity-50 disabled:cursor-not-allowed",
        variants[variant],
        className
      )}
      whileHover={{
        scale: disabled || loading ? 1 : 1.02,
        y: disabled || loading ? 0 : -2,
      }}
      whileTap={{
        scale: disabled || loading ? 1 : 0.95,
      }}
      transition={{
        type: "spring",
        stiffness: 400,
        damping: 17,
      }}
      {...props}
    >
      {loading ? (
        <motion.div
          className="h-4 w-4 border-2 border-current border-t-transparent rounded-full"
          animate={{ rotate: 360 }}
          transition={{ duration: 1, repeat: Infinity, ease: "linear" }}
        />
      ) : Icon ? (
        <motion.div
          whileHover={{ rotate: variant === 'danger' ? [0, -10, 10, -10, 10, 0] : 0 }}
          transition={{ duration: 0.5 }}
        >
          <Icon size={14} />
        </motion.div>
      ) : null}
      {children}
    </motion.button>
  );
};

// 带动画的标签
export const AnimatedBadge = ({ children, variant = 'default', className }) => {
  const variants = {
    default: "bg-slate-800/50 text-slate-400",
    created: "bg-emerald-950/10 border-emerald-500/20 text-emerald-400 shadow-[0_0_15px_rgba(16,185,129,0.1)]",
    deleted: "bg-rose-950/10 border-rose-500/20 text-rose-400 shadow-[0_0_15px_rgba(244,63,94,0.1)]",
    modified: "bg-amber-950/10 border-amber-500/20 text-amber-400 shadow-[0_0_15px_rgba(245,158,11,0.1)]",
  };

  return (
    <motion.div
      className={clsx(
        "inline-flex items-center gap-2 px-3 py-1 rounded-full text-[10px] font-bold uppercase tracking-widest border",
        variants[variant],
        className
      )}
      initial={{ scale: 0, opacity: 0 }}
      animate={{ scale: 1, opacity: 1 }}
      transition={{
        type: "spring",
        stiffness: 500,
        damping: 30,
      }}
      whileHover={{
        scale: 1.05,
        transition: { duration: 0.2 }
      }}
    >
      {children}
    </motion.div>
  );
};

// 加载骨架屏
export const LoadingSkeleton = ({ className }) => (
  <motion.div
    className={clsx(
      "bg-slate-800/50 rounded",
      className
    )}
    animate={{
      opacity: [0.5, 1, 0.5],
    }}
    transition={{
      duration: 1.5,
      repeat: Infinity,
      ease: "easeInOut",
    }}
  />
);

// 空状态显示
export const EmptyState = ({ icon: Icon, title, description }) => (
  <motion.div
    className="flex flex-col items-center justify-center py-20 text-slate-600 gap-6 select-none"
    initial={{ opacity: 0, y: 20 }}
    animate={{ opacity: 1, y: 0 }}
    transition={{ duration: 0.6 }}
  >
    <motion.div
      className="relative"
      animate={{
        y: [0, -10, 0],
      }}
      transition={{
        duration: 3,
        repeat: Infinity,
        ease: "easeInOut",
      }}
    >
      <div className="absolute inset-0 bg-indigo-500/20 blur-3xl rounded-full opacity-20 animate-pulse" />
      <Icon size={64} className="opacity-20 relative z-10" />
    </motion.div>
    <div className="text-center">
      <p className="text-lg font-light text-slate-500">{title}</p>
      {description && <p className="text-xs text-slate-600 mt-2 tracking-wide uppercase">{description}</p>}
    </div>
  </motion.div>
);

// 成功/错误通知
export const Toast = ({ type = 'success', message, onClose }) => {
  const config = {
    success: {
      bg: 'bg-emerald-500/10',
      border: 'border-emerald-500/30',
      text: 'text-emerald-300',
    },
    error: {
      bg: 'bg-rose-500/10',
      border: 'border-rose-500/30',
      text: 'text-rose-300',
    },
  };

  return (
    <motion.div
      className={clsx(
        "fixed top-4 right-4 px-4 py-3 rounded-xl border backdrop-blur-xl shadow-2xl z-50",
        config[type].bg,
        config[type].border,
        config[type].text
      )}
      initial={{ opacity: 0, y: -50, x: 100 }}
      animate={{ opacity: 1, y: 0, x: 0 }}
      exit={{ opacity: 0, x: 100 }}
      transition={{
        type: "spring",
        stiffness: 500,
        damping: 30,
      }}
    >
      <div className="flex items-center gap-3">
        <motion.div
          animate={{
            scale: [1, 1.2, 1],
          }}
          transition={{
            duration: 0.5,
          }}
        >
          {type === 'success' ? '✓' : '✕'}
        </motion.div>
        <span className="text-sm font-medium">{message}</span>
        {onClose && (
          <motion.button
            onClick={onClose}
            className="ml-2 hover:opacity-70"
            whileHover={{ scale: 1.1 }}
            whileTap={{ scale: 0.9 }}
          >
            ×
          </motion.button>
        )}
      </div>
    </motion.div>
  );
};

export default {
  AnimatedButton,
  AnimatedBadge,
  LoadingSkeleton,
  EmptyState,
  Toast,
};
