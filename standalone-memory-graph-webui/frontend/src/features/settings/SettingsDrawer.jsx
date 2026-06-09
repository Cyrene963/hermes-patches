import React, { useState, useEffect, useCallback } from 'react';
import {
  Database, Server, List, Tag, Settings, X, RefreshCw
} from 'lucide-react';
import { getSettings, updateSettings, getDatabaseStatus } from '../../lib/api';
import { useI18n } from '../../lib/i18n';

import Section from './Section';
import DatabaseSection from './DatabaseSection';
import BootUrisSection from './BootUrisSection';
import DomainsSection from './DomainsSection';
import ServerSection from './ServerSection';
import AdvancedSection from './AdvancedSection';

export default function SettingsDrawer() {
  const { t } = useI18n();
  const [isOpen, setIsOpen] = useState(false);
  const [settings, setSettings] = useState(null);
  const [dbStatus, setDbStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [configPath, setConfigPath] = useState('');
  const [lockedFields, setLockedFields] = useState([]);
  const [activeTab, setActiveTab] = useState('general');

  useEffect(() => {
    const handleOpen = () => setIsOpen(true);
    window.addEventListener('open-settings', handleOpen);
    return () => window.removeEventListener('open-settings', handleOpen);
  }, []);

  const loadAll = useCallback(async () => {
    setLoading(true);
    try {
      const [settingsData, statusData] = await Promise.all([
        getSettings(),
        getDatabaseStatus(),
      ]);
      setSettings(settingsData.settings);
      setConfigPath(settingsData.config_path);
      setLockedFields(settingsData.locked_fields || []);
      setDbStatus(statusData);
    } catch (e) {
      console.error('Failed to load settings:', e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (isOpen) {
      loadAll();
    }
  }, [loadAll, isOpen]);

  const handleSave = async (updates) => {
    const result = await updateSettings(updates);
    await loadAll();
    return result;
  };

  const refreshDbStatus = async () => {
    try {
      setDbStatus(await getDatabaseStatus());
    } catch (e) {
      console.error('Failed to refresh DB status:', e);
    }
  };

  useEffect(() => {
    if (!isOpen) return undefined;
    const handleKeyDown = (event) => {
      if (event.key === 'Escape') setIsOpen(false);
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen]);

  if (!isOpen) return null;

  const tabs = [
    { id: 'general', label: t('settings.general'), icon: Settings },
    { id: 'database', label: t('settings.database'), icon: Database },
    { id: 'memory', label: t('settings.memory'), icon: List },
  ];

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/55 backdrop-blur-sm motion-safe:animate-in motion-safe:fade-in motion-safe:duration-200"
        onClick={() => setIsOpen(false)}
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="settings-title"
        className="fixed inset-y-0 right-0 z-50 flex w-full max-w-[640px] flex-col border-l border-slate-800 bg-slate-950 shadow-2xl motion-safe:animate-in motion-safe:slide-in-from-right motion-safe:duration-300 sm:w-[min(92vw,640px)]"
      >
        <div className="border-b border-slate-800/80 bg-slate-900/40 px-6 pt-6 backdrop-blur-md flex-shrink-0">
          <div className="flex items-start justify-between mb-6">
            <div>
              <h1 id="settings-title" className="text-2xl font-bold text-slate-100">{t('settings.title')}</h1>
              <p className="text-sm text-slate-400 mt-1">
                {t('settings.description')}
              </p>
            </div>
            <button
              type="button"
              aria-label="关闭设置"
              onClick={() => setIsOpen(false)}
              className="p-2 text-slate-400 hover:text-slate-200 hover:bg-slate-800 rounded-lg transition-colors"
            >
              <X size={20} />
            </button>
          </div>

          <div className="flex gap-6 overflow-x-auto" role="tablist" aria-label="设置分类">
            {tabs.map(tab => {
              const Icon = tab.icon;
              const isActive = activeTab === tab.id;
              return (
                <button
                  key={tab.id}
                  type="button"
                  role="tab"
                  aria-selected={isActive}
                  aria-controls={`settings-panel-${tab.id}`}
                  id={`settings-tab-${tab.id}`}
                  onClick={() => setActiveTab(tab.id)}
                  className={`flex items-center gap-2 pb-3 text-sm font-medium border-b-2 transition-all ${
                    isActive
                      ? "border-indigo-500 text-indigo-300 drop-shadow-sm"
                      : "border-transparent text-slate-400 hover:text-slate-200 hover:border-slate-700"
                  }`}
                >
                  <Icon size={16} />
                  {tab.label}
                </button>
              );
            })}
          </div>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-8">
          {loading ? (
            <div className="flex items-center justify-center h-full text-slate-500">
              <RefreshCw size={20} className="animate-spin mr-2" /> {t('settings.loading')}
            </div>
          ) : (
            <>
              {activeTab === 'general' && (
                <div
                  id="settings-panel-general"
                  role="tabpanel"
                  aria-labelledby="settings-tab-general"
                  className="space-y-6 motion-safe:animate-in motion-safe:fade-in motion-safe:slide-in-from-bottom-2 motion-safe:duration-200"
                >
                  <Section icon={Server} title={t('settings.server_config')}>
                    <ServerSection
                      settings={settings}
                      configPath={configPath}
                      lockedFields={lockedFields}
                      onSave={handleSave}
                    />
                  </Section>

                  <Section icon={Settings} title={t('settings.advanced')} defaultOpen={false}>
                    <AdvancedSection settings={settings} lockedFields={lockedFields} onSave={handleSave} />
                  </Section>
                </div>
              )}

              {activeTab === 'database' && (
                <div
                  id="settings-panel-database"
                  role="tabpanel"
                  aria-labelledby="settings-tab-database"
                  className="space-y-6 motion-safe:animate-in motion-safe:fade-in motion-safe:slide-in-from-bottom-2 motion-safe:duration-200"
                >
                  <Section icon={Database} title={t('settings.database_connection')}>
                    <DatabaseSection
                      settings={settings}
                      dbStatus={dbStatus}
                      onRefreshStatus={refreshDbStatus}
                      onSave={handleSave}
                    />
                  </Section>
                </div>
              )}

              {activeTab === 'memory' && (
                <div
                  id="settings-panel-memory"
                  role="tabpanel"
                  aria-labelledby="settings-tab-memory"
                  className="space-y-6 motion-safe:animate-in motion-safe:fade-in motion-safe:slide-in-from-bottom-2 motion-safe:duration-200"
                >
                  <Section icon={List} title={t('settings.boot_uris')}>
                    <BootUrisSection />
                  </Section>

                  <Section icon={Tag} title={t('settings.memory_domains')}>
                    <DomainsSection settings={settings} onSave={handleSave} />
                  </Section>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </>
  );
}
