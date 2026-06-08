import React from 'react';
import clsx from 'clsx';

export default function VisibilityBadge({ namespace, visibilityLabel, securityLevel, compact = false }) {
  const ns = namespace ?? '';
  const isShared = ns === '' || visibilityLabel === 'Shared';
  const level = securityLevel || (isShared ? 'public' : 'private');

  const label = isShared
    ? '公开'
    : level === 'sensitive'
      ? '私有 · 敏感'
      : level === 'admin_only'
        ? '仅管理员'
        : '私有';

  const title = isShared
    ? '所有人可见 · 公开'
    : `${ns || 'private namespace'} · ${level === 'sensitive' ? '敏感' : level === 'admin_only' ? '仅管理员' : '私有'}`;

  return (
    <span
      title={title}
      className={clsx(
        'inline-flex items-center rounded border font-medium tracking-wide',
        compact ? 'px-1 py-0.5 text-[9px]' : 'px-1.5 py-0.5 text-[10px]',
        isShared
          ? 'bg-emerald-500/10 text-emerald-300 border-emerald-500/25'
          : level === 'sensitive'
            ? 'bg-rose-500/10 text-rose-300 border-rose-500/25'
            : 'bg-sky-500/10 text-sky-300 border-sky-500/25'
      )}
    >
      {label}
    </span>
  );
}
