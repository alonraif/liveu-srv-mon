import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react';
import Prism from 'prismjs';
import 'prismjs/components/prism-python';
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';

import { apiFetch } from './api';
import {
  AdvertisedIpStatus,
  AuditEntry,
  AuthState,
  Identity,
  NetworkInfo,
  SpeedtestResult,
  StatusCurrent,
  StatusHistory,
} from './types';

type TabKey = 'overview' | 'liveu' | 'logs' | 'admin' | 'audit';
type AdminActionPrompt = 'restart' | 'reboot' | 'speedtest' | 'advertised-ip' | null;
type LoginUserType = 'administrator' | 'monitor';
const TAB_SESSION_KEY = 'liveu_tab_session';
const TAB_ACTIVE_KEY = 'liveu_active_tab';
const TAB_KEYS: TabKey[] = ['overview', 'liveu', 'logs', 'admin', 'audit'];
const GRAPH_WINDOW_MS = 5 * 60 * 1000;
const POLL_STATUS_MS = 5000;
const POLL_HISTORY_MS = 15000;
const POLL_NETWORK_MS = 10000;
const POLL_LIVEU_MS = 5 * 60 * 1000;
const POLL_AUDIT_MS = 15000;
const SPEEDTEST_PHASES = ['Initializing', 'Selecting server', 'Testing download', 'Testing upload', 'Finalizing'];

function parseApiTimestampMs(value: string): number {
  // Backend often emits UTC timestamps without timezone suffix.
  // If timezone is missing, treat it as UTC explicitly.
  const hasTimezone = /(?:Z|[+-]\d{2}:\d{2})$/i.test(value);
  const normalized = hasTimezone ? value : `${value}Z`;
  return new Date(normalized).getTime();
}

function getInitialTab(): TabKey {
  if (typeof window === 'undefined') return 'overview';
  const stored = window.sessionStorage.getItem(TAB_ACTIVE_KEY);
  if (stored && TAB_KEYS.includes(stored as TabKey)) {
    return stored as TabKey;
  }
  return 'overview';
}

export function App() {
  const [auth, setAuth] = useState<AuthState | null>(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [authError, setAuthError] = useState<string | null>(null);

  const [tab, setTab] = useState<TabKey>(getInitialTab);
  const [status, setStatus] = useState<StatusCurrent | null>(null);
  const [history, setHistory] = useState<StatusHistory | null>(null);
  const [network, setNetwork] = useState<NetworkInfo | null>(null);
  const [identity, setIdentity] = useState<Identity | null>(null);
  const [liveuConfig, setLiveuConfig] = useState<any>(null);
  const [audit, setAudit] = useState<AuditEntry[]>([]);
  const [error, setError] = useState<string | null>(null);

  const [loginUserType, setLoginUserType] = useState<LoginUserType>('administrator');
  const [loginPassword, setLoginPassword] = useState('');
  const [loginBusy, setLoginBusy] = useState(false);

  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [changeBusy, setChangeBusy] = useState(false);

  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [gatherLogsBusy, setGatherLogsBusy] = useState(false);
  const [restartBusy, setRestartBusy] = useState(false);
  const [restartLiveuStatus, setRestartLiveuStatus] = useState<string | null>(null);
  const [restartMessage, setRestartMessage] = useState<string | null>(null);
  const [restartError, setRestartError] = useState<string | null>(null);
  const [rebootBusy, setRebootBusy] = useState(false);
  const [rebootWaiting, setRebootWaiting] = useState(false);
  const [rebootMessage, setRebootMessage] = useState<string | null>(null);
  const [rebootError, setRebootError] = useState<string | null>(null);
  const [speedtestBusy, setSpeedtestBusy] = useState(false);
  const [speedtestPhaseIdx, setSpeedtestPhaseIdx] = useState(0);
  const [speedtestResult, setSpeedtestResult] = useState<SpeedtestResult | null>(null);
  const [speedtestError, setSpeedtestError] = useState<string | null>(null);
  const [advertisedIpStatus, setAdvertisedIpStatus] = useState<AdvertisedIpStatus | null>(null);
  const [advertisedIpMode, setAdvertisedIpMode] = useState<'public' | 'local' | 'custom'>('public');
  const [advertisedIpSelected, setAdvertisedIpSelected] = useState<string>('');
  const [advertisedIpCustom, setAdvertisedIpCustom] = useState<string>('');
  const [advertisedIpBusy, setAdvertisedIpBusy] = useState(false);
  const [advertisedIpLiveuStatus, setAdvertisedIpLiveuStatus] = useState<string | null>(null);
  const [advertisedIpMessage, setAdvertisedIpMessage] = useState<string | null>(null);
  const [advertisedIpError, setAdvertisedIpError] = useState<string | null>(null);
  const [actionPrompt, setActionPrompt] = useState<AdminActionPrompt>(null);
  const [promptPassword, setPromptPassword] = useState('');
  const [promptRebootConfirm, setPromptRebootConfirm] = useState('');
  const [promptError, setPromptError] = useState<string | null>(null);
  const [promptBusy, setPromptBusy] = useState(false);
  const loginUsername = loginUserType === 'administrator' ? 'admin' : 'monitor';
  const isMonitor = auth?.role === 'monitor';

  const ensureSession = useCallback(async () => {
    setAuthLoading(true);
    try {
      const hasTabSession = window.sessionStorage.getItem(TAB_SESSION_KEY) === '1';
      if (!hasTabSession) {
        await apiFetch('/api/auth/logout', { method: 'POST', body: JSON.stringify({}) }).catch(() => null);
        setAuth(null);
        setAuthError(null);
        return;
      }
      const me = await apiFetch<AuthState>('/api/auth/me');
      setAuth(me);
      setAuthError(null);
    } catch {
      setAuth(null);
    } finally {
      setAuthLoading(false);
    }
  }, []);

  const handleDataError = useCallback((e: any, fallbackMessage: string) => {
    setError(e?.message || fallbackMessage);
    if (
      String(e?.message).includes('Authentication') ||
      String(e?.message).includes('Invalid session') ||
      String(e?.message).includes('Session expired')
    ) {
      window.sessionStorage.removeItem(TAB_SESSION_KEY);
      setAuth(null);
    }
    if (String(e?.message).includes('Password change required')) {
      setAuth((prev) => (prev ? { ...prev, must_change_password: true } : prev));
    }
  }, []);

  const loadStatusCurrent = useCallback(async () => {
    try {
      const current = await apiFetch<StatusCurrent>('/api/status/current');
      setStatus(current);
      setError(null);
    } catch (e: any) {
      handleDataError(e, 'Failed to load status');
    }
  }, [handleDataError]);

  const loadStatusHistory = useCallback(async () => {
    try {
      const hist = await apiFetch<StatusHistory>('/api/status/history?range=5m&max_points=300');
      setHistory(hist);
      setError(null);
    } catch (e: any) {
      handleDataError(e, 'Failed to load history');
    }
  }, [handleDataError]);

  const loadNetworkInfo = useCallback(async () => {
    try {
      const net = await apiFetch<NetworkInfo>('/api/network');
      setNetwork(net);
      setError(null);
    } catch (e: any) {
      handleDataError(e, 'Failed to load network');
    }
  }, [handleDataError]);

  const loadLiveuIdentity = useCallback(async () => {
    try {
      const ident = await apiFetch<Identity>('/api/liveu/identity');
      setIdentity(ident);
      setError(null);
    } catch (e: any) {
      handleDataError(e, 'Failed to load LiveU identity');
    }
  }, [handleDataError]);

  const loadLiveuData = useCallback(async () => {
    try {
      const config = await apiFetch<any>('/api/liveu/config');
      setLiveuConfig(config);
      setError(null);
    } catch (e: any) {
      handleDataError(e, 'Failed to load LiveU data');
    }
  }, [handleDataError]);

  const loadAuditData = useCallback(async () => {
    try {
      const auditRows = await apiFetch<{ entries: AuditEntry[] }>('/api/audit?limit=200');
      setAudit(auditRows.entries);
      setError(null);
    } catch (e: any) {
      handleDataError(e, 'Failed to load audit log');
    }
  }, [handleDataError]);

  const loadAdvertisedIpStatus = useCallback(async () => {
    try {
      const statusValue = await apiFetch<AdvertisedIpStatus>('/api/admin/advertised-ip');
      setAdvertisedIpStatus(statusValue);
      setAdvertisedIpMode(
        statusValue.selected_mode === 'local' ? 'local' : statusValue.selected_mode === 'custom' ? 'custom' : 'public'
      );
      setAdvertisedIpSelected(statusValue.selected_ip || statusValue.local_ip_options[0]?.ip || '');
      setAdvertisedIpCustom(statusValue.selected_mode === 'custom' ? statusValue.selected_ip || '' : '');
      setError(null);
    } catch (e: any) {
      handleDataError(e, 'Failed to load advertised IP status');
    }
  }, [handleDataError]);

  useEffect(() => {
    ensureSession();
  }, [ensureSession]);

  useEffect(() => {
    window.sessionStorage.setItem(TAB_ACTIVE_KEY, tab);
  }, [tab]);

  useEffect(() => {
    if (isMonitor && (tab === 'admin' || tab === 'audit')) {
      setTab('overview');
    }
  }, [isMonitor, tab]);

  useEffect(() => {
    if (!auth || auth.must_change_password) return;
    loadStatusCurrent();
    const timer = window.setInterval(() => {
      loadStatusCurrent();
    }, POLL_STATUS_MS);
    return () => window.clearInterval(timer);
  }, [auth, loadStatusCurrent]);

  useEffect(() => {
    if (!auth || auth.must_change_password || tab !== 'overview') return;
    loadStatusHistory();
    const timer = window.setInterval(() => {
      loadStatusHistory();
    }, POLL_HISTORY_MS);
    return () => window.clearInterval(timer);
  }, [auth, tab, loadStatusHistory]);

  useEffect(() => {
    if (!auth || auth.must_change_password) return;
    loadNetworkInfo();
    const timer = window.setInterval(() => {
      loadNetworkInfo();
    }, POLL_NETWORK_MS);
    return () => window.clearInterval(timer);
  }, [auth, loadNetworkInfo]);

  useEffect(() => {
    if (!auth || auth.must_change_password || tab !== 'liveu') return;
    loadLiveuData();
    const timer = window.setInterval(() => {
      loadLiveuData();
    }, POLL_LIVEU_MS);
    return () => window.clearInterval(timer);
  }, [auth, tab, loadLiveuData]);

  useEffect(() => {
    if (!auth || auth.must_change_password) return;
    loadLiveuIdentity();
    const timer = window.setInterval(() => {
      loadLiveuIdentity();
    }, POLL_LIVEU_MS);
    return () => window.clearInterval(timer);
  }, [auth, loadLiveuIdentity]);

  useEffect(() => {
    if (!auth || auth.must_change_password || tab !== 'audit') return;
    loadAuditData();
    const timer = window.setInterval(() => {
      loadAuditData();
    }, POLL_AUDIT_MS);
    return () => window.clearInterval(timer);
  }, [auth, tab, loadAuditData]);

  useEffect(() => {
    if (!auth || auth.must_change_password || tab !== 'admin') return;
    loadAdvertisedIpStatus();
  }, [auth, tab, loadAdvertisedIpStatus]);

  useEffect(() => {
    Prism.highlightAll();
  }, [liveuConfig]);

  const chartData = useMemo(() => {
    if (!history || !history.samples) return [];
    return history.samples
      .map((s) => {
        const ts = parseApiTimestampMs(s.timestamp);
        return {
          ts,
          t: new Date(ts).toLocaleString(),
          cpu: s.cpu_percent,
          memory: s.memory_percent,
          temp: s.temperature_c,
          rxMbps: s.rx_mbps,
          txMbps: s.tx_mbps,
          nic: s.network_interface,
        };
      })
      .filter((point) => Number.isFinite(point.ts));
  }, [history]);

  const windowedChartData = useMemo(() => {
    if (!chartData.length) return [];
    const latestTs = chartData[chartData.length - 1].ts;
    const cutoff = latestTs - GRAPH_WINDOW_MS;
    return chartData.filter((point) => point.ts >= cutoff);
  }, [chartData]);

  const xAxisDomain = useMemo(() => {
    const now = chartData.length ? chartData[chartData.length - 1].ts : Date.now();
    return [now - GRAPH_WINDOW_MS, now];
  }, [chartData]);

  const liveuServiceStatus = status?.liveu_service_status || 'unknown';
  const graphNicName = status?.network_interface || windowedChartData[windowedChartData.length - 1]?.nic || 'N/A';
  const liveuServiceBadgeClass =
    liveuServiceStatus === 'active' ? 'badge-green' : liveuServiceStatus === 'unknown' ? 'badge-blue' : 'badge-red';
  const formatGraphTick = (ts: number) => {
    const date = new Date(ts);
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  };

  const liveuNetworkRows = useMemo(() => {
    const net = liveuConfig?.network || {};
    return Object.entries(net) as Array<[string, Record<string, any>]>;
  }, [liveuConfig]);

  const formatValue = (value: any): string => {
    if (value === null || value === undefined || value === '') return 'N/A';
    if (Array.isArray(value) || typeof value === 'object') {
      try {
        return JSON.stringify(value);
      } catch {
        return String(value);
      }
    }
    return String(value);
  };

  const parseHubs = (value: any): string[] => {
    if (Array.isArray(value)) {
      return value.map((v) => String(v)).filter(Boolean);
    }
    if (typeof value === 'string') {
      const trimmed = value.trim();
      if (!trimmed) return [];
      try {
        const normalized = trimmed.replace(/'/g, '"');
        const parsed = JSON.parse(normalized);
        if (Array.isArray(parsed)) {
          return parsed.map((v) => String(v)).filter(Boolean);
        }
      } catch {
        // Fall through to plain string rendering.
      }
      return [trimmed];
    }
    return [];
  };

  async function onLogin(e: FormEvent) {
    e.preventDefault();
    setLoginBusy(true);
    setAuthError(null);
    try {
      const res = await apiFetch<AuthState>('/api/auth/login', {
        method: 'POST',
        body: JSON.stringify({ username: loginUsername, password: loginPassword }),
      });
      window.sessionStorage.setItem(TAB_SESSION_KEY, '1');
      setAuth(res);
      setLoginPassword('');
    } catch (err: any) {
      setAuthError(err.message || 'Login failed');
    } finally {
      setLoginBusy(false);
    }
  }

  async function onChangePassword(e: FormEvent) {
    e.preventDefault();
    setChangeBusy(true);
    setAuthError(null);
    try {
      const resp = await apiFetch<{ detail: string }>('/api/auth/change-password', {
        method: 'POST',
        body: JSON.stringify({
          current_password: currentPassword,
          new_password: newPassword,
        }),
      });
      await apiFetch('/api/auth/logout', { method: 'POST', body: JSON.stringify({}) }).catch(() => null);
      window.sessionStorage.removeItem(TAB_SESSION_KEY);
      setAuth(null);
      setAuthError(resp.detail + ' Log in with your new password.');
      setCurrentPassword('');
      setNewPassword('');
    } catch (err: any) {
      setAuthError(err.message || 'Password update failed');
    } finally {
      setChangeBusy(false);
    }
  }

  async function onLogout() {
    try {
      await apiFetch('/api/auth/logout', { method: 'POST', body: JSON.stringify({}) });
    } finally {
      window.sessionStorage.removeItem(TAB_SESSION_KEY);
      setAuth(null);
    }
  }

  async function onGatherLogs() {
    if (gatherLogsBusy) return;
    setGatherLogsBusy(true);
    setActionMessage(null);
    setActionError(null);
    try {
      const res = await apiFetch<{ bundle_id: string; filename: string }>('/api/logs/gather', {
        method: 'POST',
        body: JSON.stringify({}),
      });
      window.location.href = `/api/logs/download/${res.bundle_id}`;
      setActionMessage(`Log bundle ready: ${res.filename}`);
    } catch (err: any) {
      setActionError(err.message || 'Failed to gather logs');
    } finally {
      setGatherLogsBusy(false);
    }
  }

  async function doRestartLiveu(password: string) {
    if (restartBusy) return;
    setRestartBusy(true);
    setRestartLiveuStatus(null);
    setRestartMessage(null);
    setRestartError(null);

    const pollLiveuStatus = async (): Promise<string> => {
      try {
        const current = await apiFetch<{ status: string }>('/api/admin/liveu-status');
        const statusValue = current.status || 'unknown';
        setRestartLiveuStatus(statusValue);
        return statusValue;
      } catch {
        // Keep polling loop alive even if one request fails.
        return 'unknown';
      }
    };

    void pollLiveuStatus();

    try {
      const res = await apiFetch<{ detail: string }>('/api/admin/restart-liveu', {
        method: 'POST',
        body: JSON.stringify({ password }),
      });

      const maxPolls = 120;
      for (let i = 0; i < maxPolls; i++) {
        const current = await pollLiveuStatus();
        if (current === 'active') {
          setRestartMessage('LiveU service restarted successfully');
          setRestartError(null);
          break;
        }
        if (current === 'failed') {
          setRestartError('LiveU service entered failed state after restart.');
          break;
        }
        await new Promise((resolve) => window.setTimeout(resolve, 1000));
        if (i === maxPolls - 1) {
          setRestartError(`Restart status check timed out. Current host state: ${current}`);
        }
      }
      void Promise.allSettled([loadStatusCurrent(), loadStatusHistory(), loadNetworkInfo()]);
    } catch (err: any) {
      const msg = err?.message || 'Failed to restart service';
      setRestartError(msg);
      if (String(msg).toLowerCase().includes('password confirmation failed')) {
        throw err;
      }
    } finally {
      setRestartBusy(false);
    }
  }

  async function doReboot(password: string, confirmation: string) {
    if (rebootBusy || rebootWaiting) return;
    setRebootBusy(true);
    setRebootWaiting(false);
    setRebootMessage(null);
    setRebootError(null);

    try {
      await apiFetch<{ detail: string }>('/api/admin/reboot', {
        method: 'POST',
        body: JSON.stringify({ password, confirmation }),
      });

      // Start polling for reboot cycle: server goes down, then comes back.
      setRebootBusy(false);
      setRebootWaiting(true);

      const pollInterval = 5000; // 5 seconds
      const maxPolls = 60; // 5 minutes max
      let pollCount = 0;
      let seenServerDown = false;

      const pollTimer = window.setInterval(async () => {
        pollCount++;
        if (pollCount > maxPolls) {
          window.clearInterval(pollTimer);
          setRebootWaiting(false);
          setRebootError(
            seenServerDown
              ? 'Server did not come back online in time. Please check manually.'
              : 'Reboot not yet detected. Server never appeared offline during the check window.'
          );
          return;
        }

        try {
          await apiFetch('/api/status/current');
          if (!seenServerDown) {
            // Server is still reachable; reboot may still be pending.
            return;
          }
          window.clearInterval(pollTimer);
          setRebootWaiting(false);
          setRebootMessage('Server rebooted successfully and is back online.');
          // Refresh all data
          await Promise.allSettled([loadStatusCurrent(), loadStatusHistory(), loadNetworkInfo()]);
        } catch {
          // Connection failure indicates the reboot has likely started.
          seenServerDown = true;
        }
      }, pollInterval);
    } catch (err: any) {
      const msg = err?.message || 'Failed to reboot server';
      setRebootBusy(false);
      setRebootError(msg);
      if (String(msg).toLowerCase().includes('password confirmation failed')) {
        throw err;
      }
    }
  }

  async function doRunSpeedtest(password: string) {
    if (speedtestBusy) return;
    setSpeedtestBusy(true);
    setSpeedtestPhaseIdx(0);
    setSpeedtestError(null);
    setSpeedtestResult(null);

    const phaseTimer = window.setInterval(() => {
      setSpeedtestPhaseIdx((prev) => Math.min(prev + 1, SPEEDTEST_PHASES.length - 1));
    }, 3500);

    try {
      const res = await apiFetch<SpeedtestResult>('/api/admin/speedtest', {
        method: 'POST',
        body: JSON.stringify({ password: password || null }),
      });
      setSpeedtestResult(res);
    } catch (err: any) {
      const msg = err?.message || 'Failed to run speed test';
      setSpeedtestError(msg);
      if (String(msg).toLowerCase().includes('password confirmation failed')) {
        throw err;
      }
    } finally {
      window.clearInterval(phaseTimer);
      setSpeedtestBusy(false);
    }
  }

  async function doSetAdvertisedIp(password: string) {
    if (advertisedIpBusy) return;
    const isValidIpv4 = (value: string): boolean => {
      const parts = value.trim().split('.');
      if (parts.length !== 4) return false;
      return parts.every((p) => /^\d+$/.test(p) && Number(p) >= 0 && Number(p) <= 255);
    };
    if (advertisedIpMode === 'local' && !advertisedIpSelected) {
      setAdvertisedIpError('Select a local IP address');
      return;
    }
    if (advertisedIpMode === 'custom' && !isValidIpv4(advertisedIpCustom)) {
      setAdvertisedIpError('Enter a valid IPv4 address for Custom mode');
      return;
    }
    setAdvertisedIpBusy(true);
    setAdvertisedIpLiveuStatus(null);
    setAdvertisedIpMessage(null);
    setAdvertisedIpError(null);

    const pollLiveuStatus = async (): Promise<string> => {
      try {
        const current = await apiFetch<{ status: string }>('/api/admin/liveu-status');
        const statusValue = current.status || 'unknown';
        setAdvertisedIpLiveuStatus(statusValue);
        return statusValue;
      } catch {
        return 'unknown';
      }
    };

    void pollLiveuStatus();
    try {
      const res = await apiFetch<{ detail: string }>('/api/admin/advertised-ip', {
        method: 'POST',
        body: JSON.stringify({
          password,
          mode: advertisedIpMode,
          ip: advertisedIpMode === 'local' ? advertisedIpSelected : advertisedIpMode === 'custom' ? advertisedIpCustom.trim() : null,
        }),
      });

      const maxPolls = 120;
      for (let i = 0; i < maxPolls; i++) {
        const current = await pollLiveuStatus();
        if (current === 'active') {
          break;
        }
        if (current === 'failed') {
          setAdvertisedIpError('LiveU service entered failed state after restart.');
          break;
        }
        await new Promise((resolve) => window.setTimeout(resolve, 1000));
        if (i === maxPolls - 1) {
          setAdvertisedIpError(`Restart status check timed out. Current host state: ${current}`);
        }
      }

      setAdvertisedIpMessage(res.detail || 'Advertised IP updated');
      await Promise.allSettled([loadAdvertisedIpStatus(), loadStatusCurrent(), loadNetworkInfo()]);
    } catch (err: any) {
      const msg = err?.message || 'Failed to update advertised IP';
      setAdvertisedIpError(msg);
      if (String(msg).toLowerCase().includes('password confirmation failed')) {
        throw err;
      }
    } finally {
      setAdvertisedIpBusy(false);
    }
  }

  function openActionPrompt(action: Exclude<AdminActionPrompt, null>) {
    setPromptError(null);
    setPromptPassword('');
    setPromptRebootConfirm('');
    setActionPrompt(action);
  }

  function closeActionPrompt() {
    if (promptBusy) return;
    setActionPrompt(null);
    setPromptError(null);
    setPromptPassword('');
    setPromptRebootConfirm('');
  }

  async function onConfirmActionPrompt(e: FormEvent) {
    e.preventDefault();
    if (!actionPrompt) return;
    setPromptError(null);
    if (!promptPassword) {
      setPromptError('Password is required');
      return;
    }
    if (actionPrompt === 'reboot' && promptRebootConfirm !== 'REBOOT') {
      setPromptError("Confirmation text must be exactly 'REBOOT'");
      return;
    }

    setPromptBusy(true);
    const chosenAction = actionPrompt;
    const password = promptPassword;
    const rebootConfirm = promptRebootConfirm;
    setActionPrompt(null);
    setPromptPassword('');
    setPromptRebootConfirm('');
    setPromptError(null);
    try {
      if (chosenAction === 'restart') {
        await doRestartLiveu(password);
      } else if (chosenAction === 'reboot') {
        await doReboot(password, rebootConfirm);
      } else if (chosenAction === 'speedtest') {
        await doRunSpeedtest(password);
      } else if (chosenAction === 'advertised-ip') {
        await doSetAdvertisedIp(password);
      }
    } catch {
      // Errors are surfaced on the action cards.
    } finally {
      setPromptBusy(false);
    }
  }

  if (authLoading) {
    return <div className="screen-center">Loading session...</div>;
  }

  if (!auth) {
    return (
      <div className="screen-center">
        <form className="panel form" onSubmit={onLogin}>
          <h1>LiveU Server Monitor</h1>
          <p>Select user and sign in (local only)</p>
          <label>
            User
            <select value={loginUserType} onChange={(e) => setLoginUserType(e.target.value as LoginUserType)}>
              <option value="administrator">Administrator</option>
              <option value="monitor">Monitor</option>
            </select>
          </label>
          <label>
            Password
            <input
              type="password"
              value={loginPassword}
              onChange={(e) => setLoginPassword(e.target.value)}
              autoComplete="current-password"
            />
          </label>
          {authError && <div className="error">{authError}</div>}
          <button disabled={loginBusy}>{loginBusy ? 'Signing in...' : 'Sign In'}</button>
        </form>
      </div>
    );
  }

  if (auth.must_change_password) {
    return (
      <div className="screen-center">
        <form className="panel form" onSubmit={onChangePassword}>
          <h1>Change Temporary Password</h1>
          <p>First login requires a password change before dashboard access.</p>
          <label>
            Current password
            <input
              type="password"
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              autoComplete="current-password"
            />
          </label>
          <label>
            New password (min 12 chars)
            <input
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              autoComplete="new-password"
            />
          </label>
          {authError && <div className="error">{authError}</div>}
          <button disabled={changeBusy}>{changeBusy ? 'Updating...' : 'Change Password'}</button>
        </form>
      </div>
    );
  }

  return (
    <div className="app">
      <header className="topbar">
        <div>
          <h1>LiveU Server Monitor</h1>
          <div className="subline">
            <span className="badge">{auth.role === 'monitor' ? 'Monitor' : 'Administrator'}</span>
            {identity?.server_type && <span className="badge badge-blue">{identity.server_type}</span>}
          </div>
        </div>
        <div className="top-actions">
          <span className="muted">{auth.username}</span>
          <button onClick={onLogout}>Logout</button>
        </div>
      </header>

      <nav className="tabs">
        {(isMonitor
          ? [
              ['overview', 'Overview'],
              ['liveu', 'LiveU Configuration'],
              ['logs', 'Logs'],
            ]
          : [
              ['overview', 'Overview'],
              ['liveu', 'LiveU Configuration'],
              ['logs', 'Logs'],
              ['admin', 'Admin Actions'],
              ['audit', 'Audit Log'],
            ]).map(([key, label]) => (
          <button key={key} className={tab === key ? 'tab active' : 'tab'} onClick={() => setTab(key as TabKey)}>
            {label}
          </button>
        ))}
      </nav>

      {error && <div className="error">{error}</div>}

      {tab === 'overview' && (
        <section className="grid overview-grid">
          <div className="panel card stacked-card overview-system">
            <div className="muted">System Health</div>
            <div className="stacked-card-value">
              <div>
                <strong>LiveU Service:</strong>{' '}
                <span className={`badge status-badge ${liveuServiceBadgeClass}`}>{liveuServiceStatus}</span>
              </div>
              <div><strong>CPU:</strong> {status ? `${status.cpu_percent}%` : '-'}</div>
              <div><strong>Memory:</strong> {status ? `${status.memory_percent}%` : '-'}</div>
              <div><strong>Temperature:</strong> {status?.temperature_c != null ? `${status.temperature_c} °C` : 'Unavailable'}</div>
            </div>
          </div>
          <div className="panel card stacked-card overview-versions">
            <div className="muted">Versions</div>
            <div className="stacked-card-value">
              <div><strong>Server:</strong> {status?.server_version || '-'}</div>
              <div><strong>OS:</strong> {status?.os_version || '-'}</div>
              <div><strong>Kernel:</strong> {status?.kernel_version || '-'}</div>
            </div>
          </div>
          <div className="panel card stacked-card overview-network">
            <div className="muted">Network</div>
            <div className="stacked-card-value">
              <div><strong>Internal IP:</strong> {network?.internal_ip || 'Unavailable'}</div>
              <div><strong>Public IP:</strong> {network?.public_ip || 'Unavailable'}</div>
              <div>
                <strong>Link Status:</strong>{' '}
                <span className={`badge status-badge ${network?.link_status === 'up' ? 'badge-green' : 'badge-red'}`}>
                  {network?.link_status || '-'}
                </span>
              </div>
              <div>
                <strong>SSH Port 22:</strong>{' '}
                <span className={`badge status-badge ${network?.ssh_port_22 === 'open' ? 'badge-red' : 'badge-green'}`}>
                  {network?.ssh_port_22 || '-'}
                </span>
              </div>
            </div>
          </div>
          <div className="panel overview-disk">
            <h3>Disk Usage</h3>
            <table>
              <thead>
                <tr>
                  <th>Filesystem</th>
                  <th>Size</th>
                  <th>Used</th>
                  <th>Avail</th>
                  <th>Use%</th>
                  <th>Mounted on</th>
                </tr>
              </thead>
              <tbody>
                {status?.disks.map((d) => (
                  <tr key={`${d.filesystem}-${d.mounted_on}`}>
                    <td>{d.filesystem}</td>
                    <td>{d.size}</td>
                    <td>{d.used}</td>
                    <td>{d.avail}</td>
                    <td>{d.use_percent}</td>
                    <td>{d.mounted_on}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="panel chart-panel overview-graphs">
            <div className="graphs-header">
              <h3>Graphs (Last 5 Minutes)</h3>
            </div>
            <div className="graphs-grid">
              <div className="panel graph-card">
                <h4>CPU</h4>
                <div style={{ width: '100%', height: 220 }}>
                  <ResponsiveContainer>
                    <LineChart data={windowedChartData} margin={{ top: 8, right: 12, left: -8, bottom: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                      <XAxis
                        dataKey="ts"
                        type="number"
                        domain={xAxisDomain}
                        tickFormatter={formatGraphTick}
                        tick={{ fill: '#627d98', fontSize: 12 }}
                        minTickGap={24}
                      />
                      <YAxis
                        domain={[0, 100]}
                        tick={{ fill: '#627d98', fontSize: 12 }}
                        width={52}
                        label={{ value: 'Usage %', angle: -90, position: 'insideLeft', offset: 0 }}
                      />
                      <Tooltip
                        labelFormatter={(value) => new Date(value).toLocaleString()}
                        formatter={(value) => [`${Number(value ?? 0).toFixed(2)} %`, 'CPU usage']}
                      />
                      <Line type="linear" dataKey="cpu" stroke="#0ea5e9" dot={false} strokeWidth={2} name="CPU %" isAnimationActive={false} />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              </div>
              <div className="panel graph-card">
                <h4>Memory</h4>
                <div style={{ width: '100%', height: 220 }}>
                  <ResponsiveContainer>
                    <LineChart data={windowedChartData} margin={{ top: 8, right: 12, left: -8, bottom: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                      <XAxis
                        dataKey="ts"
                        type="number"
                        domain={xAxisDomain}
                        tickFormatter={formatGraphTick}
                        tick={{ fill: '#627d98', fontSize: 12 }}
                        minTickGap={24}
                      />
                      <YAxis
                        domain={[0, 100]}
                        tick={{ fill: '#627d98', fontSize: 12 }}
                        width={52}
                        label={{ value: 'Usage %', angle: -90, position: 'insideLeft', offset: 0 }}
                      />
                      <Tooltip
                        labelFormatter={(value) => new Date(value).toLocaleString()}
                        formatter={(value) => [`${Number(value ?? 0).toFixed(2)} %`, 'Memory usage']}
                      />
                      <Line type="linear" dataKey="memory" stroke="#10b981" dot={false} strokeWidth={2} name="Memory %" isAnimationActive={false} />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              </div>
              <div className="panel graph-card">
                <h4>Temperature</h4>
                <div style={{ width: '100%', height: 220 }}>
                  <ResponsiveContainer>
                    <LineChart data={windowedChartData} margin={{ top: 8, right: 12, left: -8, bottom: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                      <XAxis
                        dataKey="ts"
                        type="number"
                        domain={xAxisDomain}
                        tickFormatter={formatGraphTick}
                        tick={{ fill: '#627d98', fontSize: 12 }}
                        minTickGap={24}
                      />
                      <YAxis
                        tick={{ fill: '#627d98', fontSize: 12 }}
                        width={52}
                        label={{ value: 'Temp (C)', angle: -90, position: 'insideLeft', offset: 0 }}
                      />
                      <Tooltip
                        labelFormatter={(value) => new Date(value).toLocaleString()}
                        formatter={(value) => [`${Number(value ?? 0).toFixed(2)} C`, 'Temperature']}
                      />
                      <Line type="linear" dataKey="temp" stroke="#f97316" dot={false} strokeWidth={2} name="Temp C" isAnimationActive={false} />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              </div>
              <div className="panel graph-card">
                <h4>Network TX/RX ({graphNicName})</h4>
                <div style={{ width: '100%', height: 220 }}>
                  <ResponsiveContainer>
                    <LineChart data={windowedChartData} margin={{ top: 8, right: 12, left: -8, bottom: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                      <XAxis
                        dataKey="ts"
                        type="number"
                        domain={xAxisDomain}
                        tickFormatter={formatGraphTick}
                        tick={{ fill: '#627d98', fontSize: 12 }}
                        minTickGap={24}
                      />
                      <YAxis
                        tick={{ fill: '#627d98', fontSize: 12 }}
                        width={58}
                        label={{ value: 'Mbps', angle: -90, position: 'insideLeft', offset: 0 }}
                      />
                      <Tooltip
                        labelFormatter={(value) => new Date(value).toLocaleString()}
                        formatter={(value) => `${Number(value ?? 0).toFixed(3)} Mbps`}
                      />
                      <Line type="linear" dataKey="rxMbps" stroke="#2563eb" dot={false} strokeWidth={2} name="RX Mbps" isAnimationActive={false} />
                      <Line type="linear" dataKey="txMbps" stroke="#d97706" dot={false} strokeWidth={2} name="TX Mbps" isAnimationActive={false} />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              </div>
            </div>
          </div>
        </section>
      )}

      {tab === 'liveu' && (
        <section className="grid liveu-grid">
          <div className="panel liveu-identity">
            <h3>Identity</h3>
            <p><strong>Base Unique ID:</strong> {identity?.base_unique_id || 'Unavailable'}</p>
            <p><strong>Server License:</strong> {identity?.server_license || 'Unavailable'}</p>
            <p><strong>Server Type:</strong> {identity?.server_type || 'Unknown'}</p>
          </div>

          {liveuConfig?.server_type === 'MMH/Transceiver' && (
            <div className="panel liveu-mmh">
              <h3>MMH / Transceiver Configuration</h3>
              <p><strong>MMH Instances:</strong> {liveuConfig?.mmh?.mmh_instances ?? '-'}</p>
              <p><strong>External Video Preview TCP Port:</strong> {liveuConfig?.role_config?.['external video preview tcp port']
                ?? liveuConfig?.role_config?.['EXTERNAL_PREVIEW_TCP_PORT']
                ?? liveuConfig?.mmh?.external_preview_tcp_port
                ?? 'N/A'}</p>
              <p><strong>Local Hub Port:</strong> {liveuConfig?.mmh?.local_hub_port ?? 'N/A'}</p>
              <h4>Collector Ports</h4>
              <table>
                <thead>
                  <tr>
                    <th>Instance</th>
                    <th>UDP Port</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {(liveuConfig?.mmh?.collectors || []).map((item: any) => (
                    <tr key={item.instance}>
                      <td>{item.instance}</td>
                      <td>{item.port ?? 'N/A'}</td>
                      <td>{item.status || 'closed'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {liveuConfig?.server_type === 'Video Return' && (
            <div className="panel liveu-mmh">
              <h3>Video Return Configuration</h3>
              <p><strong>External Video Preview TCP Port:</strong> {liveuConfig?.role_config?.['external video preview tcp port']
                ?? liveuConfig?.role_config?.['EXTERNAL_VIDEO_PREVIEW_TCP_PORT']
                ?? liveuConfig?.role_config?.['external preview tcp port']
                ?? liveuConfig?.role_config?.['EXTERNAL_PREVIEW_TCP_PORT']
                ?? 'N/A'}</p>
              <p><strong>RTP Base Port:</strong> {liveuConfig?.role_config?.['rtp base port']
                ?? liveuConfig?.role_config?.['RTP_BASE_PORT']
                ?? liveuConfig?.role_config?.['RTP base port']
                ?? 'N/A'}</p>
            </div>
          )}

          <div className="panel liveu-core">
            <h3>Core Configuration</h3>
            <p><strong>LUC:</strong> {formatValue(liveuConfig?.core?.luc)}</p>
            <p><strong>Hubs:</strong></p>
            {parseHubs(liveuConfig?.core?.hubs).length > 0 ? (
              <ul>
                {parseHubs(liveuConfig?.core?.hubs).map((hub, idx) => (
                  <li key={`${hub}-${idx}`}>{hub}</li>
                ))}
              </ul>
            ) : (
              <p className="muted">N/A</p>
            )}
          </div>

          <div className="panel liveu-network">
            <h3>Network Configuration</h3>
            <p><strong>Server Public IP:</strong> {network?.public_ip || 'Unavailable'}</p>
            {liveuNetworkRows.length === 0 ? (
              <p className="muted">No network data available.</p>
            ) : (
              liveuNetworkRows.map(([iface, fields]) => (
                <div key={iface} className="code-wrap network-block">
                  <h4>{iface}</h4>
                  <table className="network-table">
                    <thead>
                      <tr>
                        <th>Field</th>
                        <th>Value</th>
                      </tr>
                    </thead>
                    <tbody>
                      {Object.entries(fields).map(([key, val]) => (
                        <tr key={`${iface}-${key}`}>
                          <td>{key}</td>
                          <td>{formatValue(val)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ))
            )}
          </div>

          {liveuConfig?.server_type === 'Ingest' && (
            <div className="panel liveu-mmh">
              <h3>Ingest Configuration</h3>
              <p className="ingest-port-line"><strong>External file server tcp port:</strong> {liveuConfig?.ingest?.external_file_server_tcp_port ?? 'N/A'}</p>

              {(liveuConfig?.ingest?.files || []).map((f: any) => (
                <div key={f.path} className="ingest-file-block">
                  <h4 className="ingest-file-title">{f.path}</h4>
                  <pre className="ingest-pre">
                    <code className="language-python">{f.content}</code>
                  </pre>
                </div>
              ))}
            </div>
          )}
        </section>
      )}

      {tab === 'logs' && (
        <section className="grid">
          <div className="panel">
            <h3>Log Bundles</h3>
            <p>Create and download a compressed `.tar.gz` bundle.</p>
            <button className="logs-gather-btn" onClick={onGatherLogs} disabled={gatherLogsBusy}>
              {gatherLogsBusy && <span className="button-spinner" aria-hidden="true" />}
              {gatherLogsBusy ? 'Gathering Logs...' : 'Gather Logs'}
            </button>
            {actionMessage && <div className="info">{actionMessage}</div>}
            {actionError && <div className="error">{actionError}</div>}
          </div>
        </section>
      )}

      {tab === 'admin' && (
        <section className="grid admin-grid">
          {liveuConfig?.server_type !== 'Ingest' && (
            <div className="panel form admin-action-card">
              <h3>Advertised stream destination</h3>
              <p><strong>Configured IP:</strong> {advertisedIpStatus?.configured_ip || 'Public IP (no override)'}</p>
              <p><strong>Current Public IP:</strong> {network?.public_ip || 'Unavailable'}</p>
              <label>
                Advertise
                <select
                  value={advertisedIpMode}
                  onChange={(e) =>
                    setAdvertisedIpMode(
                      e.target.value === 'local' ? 'local' : e.target.value === 'custom' ? 'custom' : 'public'
                    )
                  }
                  disabled={advertisedIpBusy}
                >
                  <option value="public">Public IP</option>
                  <option value="local" disabled={!advertisedIpStatus || advertisedIpStatus.local_ip_options.length === 0}>
                    Local IP
                  </option>
                  <option value="custom">Custom</option>
                </select>
              </label>
              {advertisedIpMode === 'local' && (
                <label>
                  Local IP
                  <select
                    value={advertisedIpSelected}
                    onChange={(e) => setAdvertisedIpSelected(e.target.value)}
                    disabled={advertisedIpBusy || !advertisedIpStatus || advertisedIpStatus.local_ip_options.length === 0}
                  >
                    {(advertisedIpStatus?.local_ip_options || []).map((entry) => (
                      <option key={`${entry.interface}-${entry.ip}`} value={entry.ip}>
                        {entry.label}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              {advertisedIpMode === 'local' && (advertisedIpStatus?.local_ip_options || []).length === 0 && (
                <div className="error">No local IPv4 options were detected on this host.</div>
              )}
              {advertisedIpMode === 'custom' && (
                <label>
                  Custom IPv4
                  <input
                    value={advertisedIpCustom}
                    onChange={(e) => setAdvertisedIpCustom(e.target.value)}
                    placeholder="e.g. 172.16.32.7"
                    disabled={advertisedIpBusy}
                  />
                </label>
              )}
              <button
                className="inline-spinner-btn admin-action-btn"
                disabled={
                  advertisedIpBusy ||
                  !advertisedIpStatus ||
                  (advertisedIpMode === 'local' && (!advertisedIpSelected || advertisedIpStatus.local_ip_options.length === 0)) ||
                  (advertisedIpMode === 'custom' && !advertisedIpCustom.trim())
                }
                onClick={() => openActionPrompt('advertised-ip')}
              >
                {advertisedIpBusy && <span className="button-spinner" aria-hidden="true" />}
                {advertisedIpBusy
                  ? `Applying and restarting (${advertisedIpLiveuStatus || 'checking'})...`
                  : 'Apply Advertised IP'}
              </button>
              {advertisedIpMessage && <div className="info">{advertisedIpMessage}</div>}
              {advertisedIpError && <div className="error">{advertisedIpError}</div>}
            </div>
          )}

          <div className="panel form admin-action-card">
            <h3>Restart LiveU Service</h3>
            <p className="admin-action-desc">Requires password confirmation.</p>
            <button className="inline-spinner-btn admin-action-btn" disabled={restartBusy} onClick={() => openActionPrompt('restart')}>
              {restartBusy && <span className="button-spinner" aria-hidden="true" />}
              {restartBusy
                ? `Restarting (${restartLiveuStatus || 'checking'})...`
                : 'Restart LiveU Service'}
            </button>
            {restartMessage && <div className="info">{restartMessage}</div>}
            {restartError && <div className="error">{restartError}</div>}
          </div>

          <div className="panel form admin-action-card">
            <h3>Reboot Server</h3>
            <p className="admin-action-desc">Requires password confirmation and REBOOT confirmation text.</p>
            <button 
              className={`danger admin-action-btn${(rebootBusy || rebootWaiting) ? ' inline-spinner-btn' : ''}`} 
              disabled={rebootBusy || rebootWaiting}
              onClick={() => openActionPrompt('reboot')}
            >
              {(rebootBusy || rebootWaiting) && <span className="button-spinner" aria-hidden="true" />}
              {rebootBusy
                ? 'Rebooting...'
                : rebootWaiting
                  ? 'Rebooting...'
                  : 'Reboot Server'}
            </button>
            {rebootMessage && <div className="info">{rebootMessage}</div>}
            {rebootError && <div className="error">{rebootError}</div>}
          </div>

          <div className="panel form admin-action-card">
            <h3>Network Speed Test</h3>
            <p className="admin-action-desc">Requires password confirmation.</p>
            <button className="inline-spinner-btn admin-action-btn" disabled={speedtestBusy} onClick={() => openActionPrompt('speedtest')}>
              {speedtestBusy && <span className="button-spinner" aria-hidden="true" />}
              {speedtestBusy ? `${SPEEDTEST_PHASES[speedtestPhaseIdx]}...` : 'Start Speed Test'}
            </button>
            {speedtestError && <div className="error">{speedtestError}</div>}
            {speedtestResult && (
              <div className="speedtest-result">
                <div><strong>Download:</strong> {speedtestResult.download_mbps.toFixed(2)} Mbps</div>
                <div><strong>Upload:</strong> {speedtestResult.upload_mbps.toFixed(2)} Mbps</div>
                <div><strong>Ping:</strong> {speedtestResult.ping_ms.toFixed(2)} ms</div>
                <div><strong>Server:</strong> {speedtestResult.server_name} ({speedtestResult.server_sponsor})</div>
                <div><strong>Location:</strong> {speedtestResult.server_country}</div>
                <div><strong>Host:</strong> {speedtestResult.server_host}</div>
                <div><strong>Public IP:</strong> {speedtestResult.public_ip}</div>
                <div>
                  <strong>Timestamp:</strong>{' '}
                  {speedtestResult.timestamp ? new Date(speedtestResult.timestamp).toLocaleString() : '-'}
                </div>
              </div>
            )}
          </div>
        </section>
      )}

      {tab === 'audit' && (
        <section className="grid">
          <div className="panel">
            <h3>Audit Log</h3>
            <table>
              <thead>
                <tr>
                  <th>Timestamp</th>
                  <th>User</th>
                  <th>Action</th>
                  <th>Details</th>
                  <th>IP</th>
                </tr>
              </thead>
              <tbody>
                {audit.map((entry, idx) => (
                  <tr key={`${entry.timestamp}-${idx}`}>
                    <td>{new Date(entry.timestamp).toLocaleString()}</td>
                    <td>{entry.username}</td>
                    <td>{entry.action}</td>
                    <td>{entry.details}</td>
                    <td>{entry.remote_ip || '-'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {actionPrompt && (
        <div className="modal-backdrop" role="presentation" onClick={closeActionPrompt}>
          <div className="modal-card" role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()}>
            <h3>
              {actionPrompt === 'restart' && 'Confirm Restart LiveU Service'}
              {actionPrompt === 'reboot' && 'Confirm Reboot Server'}
              {actionPrompt === 'speedtest' && 'Confirm Network Speed Test'}
              {actionPrompt === 'advertised-ip' && 'Confirm Advertised IP Change'}
            </h3>
            {actionPrompt === 'advertised-ip' && (
              <p>
                Selection: {advertisedIpMode === 'public'
                  ? 'Public IP'
                  : advertisedIpMode === 'local'
                    ? `Local IP (${advertisedIpSelected})`
                    : `Custom IP (${advertisedIpCustom.trim() || '-'})`}. This action restarts LiveU service.
              </p>
            )}
            <form className="form" onSubmit={onConfirmActionPrompt}>
              <label>
                Password
                <input
                  type="password"
                  value={promptPassword}
                  onChange={(e) => setPromptPassword(e.target.value)}
                  autoComplete="current-password"
                  disabled={promptBusy}
                />
              </label>
              {actionPrompt === 'reboot' && (
                <label>
                  Type REBOOT
                  <input
                    value={promptRebootConfirm}
                    onChange={(e) => setPromptRebootConfirm(e.target.value)}
                    disabled={promptBusy}
                  />
                </label>
              )}
              {promptError && <div className="error">{promptError}</div>}
              <div className="modal-actions">
                <button type="button" onClick={closeActionPrompt} disabled={promptBusy}>
                  Cancel
                </button>
                <button className="inline-spinner-btn" disabled={promptBusy}>
                  {promptBusy && <span className="button-spinner" aria-hidden="true" />}
                  Confirm
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

function Card({
  title,
  value,
  badgeClass,
}: {
  title: string;
  value: string;
  badgeClass?: string;
}) {
  return (
    <div className="panel card">
      <div className="muted">{title}</div>
      <div className="card-value">{value}</div>
      {badgeClass && <span className={`badge ${badgeClass}`}>{value}</span>}
    </div>
  );
}
