import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react';
import Prism from 'prismjs';
import 'prismjs/components/prism-python';
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';

import { apiFetch } from './api';
import { AuditEntry, AuthState, Identity, NetworkInfo, SpeedtestResult, StatusCurrent, StatusHistory } from './types';

type TabKey = 'overview' | 'liveu' | 'logs' | 'admin' | 'audit';
type GraphWindowKey = '5m' | '10m' | '30m' | '1h' | '24h' | '7d';
const TAB_SESSION_KEY = 'liveu_tab_session';
const TAB_ACTIVE_KEY = 'liveu_active_tab';
const TAB_KEYS: TabKey[] = ['overview', 'liveu', 'logs', 'admin', 'audit'];
const GRAPH_WINDOW_MS: Record<GraphWindowKey, number> = {
  '5m': 5 * 60 * 1000,
  '10m': 10 * 60 * 1000,
  '30m': 30 * 60 * 1000,
  '1h': 60 * 60 * 1000,
  '24h': 24 * 60 * 60 * 1000,
  '7d': 7 * 24 * 60 * 60 * 1000,
};
const GRAPH_WINDOW_OPTIONS: Array<{ value: GraphWindowKey; label: string }> = [
  { value: '5m', label: '5 minutes' },
  { value: '10m', label: '10 minutes' },
  { value: '30m', label: '30 minutes' },
  { value: '1h', label: '1 hour' },
  { value: '24h', label: '24 hours' },
  { value: '7d', label: '7 days' },
];
const POLL_STATUS_MS = 5000;
const POLL_HISTORY_MS = 1000;
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

  const [loginUsername, setLoginUsername] = useState('admin');
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
  const [restartPassword, setRestartPassword] = useState('');
  const [rebootPassword, setRebootPassword] = useState('');
  const [rebootConfirm, setRebootConfirm] = useState('');
  const [graphWindow, setGraphWindow] = useState<GraphWindowKey>('5m');

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
      const hist = await apiFetch<StatusHistory>('/api/status/history?range=7d');
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

  useEffect(() => {
    ensureSession();
  }, [ensureSession]);

  useEffect(() => {
    window.sessionStorage.setItem(TAB_ACTIVE_KEY, tab);
  }, [tab]);

  useEffect(() => {
    if (!auth || auth.must_change_password) return;
    loadStatusCurrent();
    const timer = window.setInterval(() => {
      loadStatusCurrent();
    }, POLL_STATUS_MS);
    return () => window.clearInterval(timer);
  }, [auth, loadStatusCurrent]);

  useEffect(() => {
    if (!auth || auth.must_change_password) return;
    loadStatusHistory();
    const timer = window.setInterval(() => {
      loadStatusHistory();
    }, POLL_HISTORY_MS);
    return () => window.clearInterval(timer);
  }, [auth, loadStatusHistory]);

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
    const cutoff = latestTs - GRAPH_WINDOW_MS[graphWindow];
    return chartData.filter((point) => point.ts >= cutoff);
  }, [chartData, graphWindow]);

  const liveuServiceStatus = status?.liveu_service_status || 'unknown';
  const graphNicName = status?.network_interface || windowedChartData[windowedChartData.length - 1]?.nic || 'N/A';
  const liveuServiceBadgeClass =
    liveuServiceStatus === 'active' ? 'badge-green' : liveuServiceStatus === 'unknown' ? 'badge-blue' : 'badge-red';
  const formatGraphTick = (ts: number) => {
    const date = new Date(ts);
    if (graphWindow === '24h') return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    if (graphWindow === '7d') return date.toLocaleDateString([], { month: 'short', day: 'numeric' });
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
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

  async function onRestartLiveu(e: FormEvent) {
    e.preventDefault();
    if (restartBusy) return;
    setRestartBusy(true);
    setRestartLiveuStatus(null);
    setRestartMessage(null);
    setRestartError(null);

    const pollLiveuStatus = async () => {
      try {
        const current = await apiFetch<StatusCurrent>('/api/status/current');
        setRestartLiveuStatus(current.liveu_service_status || 'unknown');
      } catch {
        // Keep polling loop alive even if one request fails.
      }
    };

    await pollLiveuStatus();
    const pollTimer = window.setInterval(() => {
      void pollLiveuStatus();
    }, 1000);

    try {
      const res = await apiFetch<{ detail: string }>('/api/admin/restart-liveu', {
        method: 'POST',
        body: JSON.stringify({ password: restartPassword }),
      });
      setRestartPassword('');
      setRestartMessage(res.detail);
      await pollLiveuStatus();
      await Promise.allSettled([loadStatusCurrent(), loadStatusHistory(), loadNetworkInfo()]);
    } catch (err: any) {
      setRestartError(err.message || 'Failed to restart service');
      await pollLiveuStatus();
    } finally {
      window.clearInterval(pollTimer);
      setRestartBusy(false);
    }
  }

  async function onReboot(e: FormEvent) {
    e.preventDefault();
    if (rebootBusy || rebootWaiting) return;
    setRebootBusy(true);
    setRebootWaiting(false);
    setRebootMessage(null);
    setRebootError(null);

    try {
      const res = await apiFetch<{ detail: string }>('/api/admin/reboot', {
        method: 'POST',
        body: JSON.stringify({ password: rebootPassword, confirmation: rebootConfirm }),
      });
      setRebootPassword('');
      setRebootConfirm('');

      // Start polling for server to come back
      setRebootBusy(false);
      setRebootWaiting(true);

      const pollInterval = 5000; // 5 seconds
      const maxPolls = 60; // 5 minutes max
      let pollCount = 0;

      const pollTimer = window.setInterval(async () => {
        pollCount++;
        if (pollCount > maxPolls) {
          window.clearInterval(pollTimer);
          setRebootWaiting(false);
          setRebootError('Server did not come back online in time. Please check manually.');
          return;
        }

        try {
          await apiFetch('/api/status/current');
          window.clearInterval(pollTimer);
          setRebootWaiting(false);
          setRebootMessage('Server rebooted successfully and is back online.');
          // Refresh all data
          await Promise.allSettled([loadStatusCurrent(), loadStatusHistory(), loadNetworkInfo()]);
        } catch {
          // Keep polling - server is still down
        }
      }, pollInterval);
    } catch (err: any) {
      setRebootBusy(false);
      setRebootError(err.message || 'Failed to reboot server');
    }
  }

  async function onRunSpeedtest(e: FormEvent) {
    e.preventDefault();
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
        body: JSON.stringify({}),
      });
      setSpeedtestResult(res);
    } catch (err: any) {
      setSpeedtestError(err.message || 'Failed to run speed test');
    } finally {
      window.clearInterval(phaseTimer);
      setSpeedtestBusy(false);
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
          <p>Administrator login (local only)</p>
          <label>
            Username
            <input value={loginUsername} onChange={(e) => setLoginUsername(e.target.value)} autoComplete="username" />
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
            <span className="badge">Administrator</span>
            {identity?.server_type && <span className="badge badge-blue">{identity.server_type}</span>}
          </div>
        </div>
        <div className="top-actions">
          <span className="muted">{auth.username}</span>
          <button onClick={onLogout}>Logout</button>
        </div>
      </header>

      <nav className="tabs">
        {[
          ['overview', 'Overview'],
          ['liveu', 'LiveU Configuration'],
          ['logs', 'Logs'],
          ['admin', 'Admin Actions'],
          ['audit', 'Audit Log'],
        ].map(([key, label]) => (
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
                <span className={`badge status-badge ${network?.ssh_port_22 === 'open' ? 'badge-green' : 'badge-red'}`}>
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
              <h3>Graphs</h3>
              <label className="graph-window-control">
                <select value={graphWindow} onChange={(e) => setGraphWindow(e.target.value as GraphWindowKey)}>
                  {GRAPH_WINDOW_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>
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
                        domain={['dataMin', 'dataMax']}
                        tickFormatter={formatGraphTick}
                        tick={{ fill: '#627d98', fontSize: 12 }}
                        minTickGap={24}
                      />
                      <YAxis domain={[0, 100]} tick={{ fill: '#627d98', fontSize: 12 }} width={38} />
                      <Tooltip labelFormatter={(value) => new Date(value).toLocaleString()} />
                      <Line type="monotone" dataKey="cpu" stroke="#0ea5e9" dot={false} strokeWidth={2} name="CPU %" />
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
                        domain={['dataMin', 'dataMax']}
                        tickFormatter={formatGraphTick}
                        tick={{ fill: '#627d98', fontSize: 12 }}
                        minTickGap={24}
                      />
                      <YAxis domain={[0, 100]} tick={{ fill: '#627d98', fontSize: 12 }} width={38} />
                      <Tooltip labelFormatter={(value) => new Date(value).toLocaleString()} />
                      <Line type="monotone" dataKey="memory" stroke="#10b981" dot={false} strokeWidth={2} name="Memory %" />
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
                        domain={['dataMin', 'dataMax']}
                        tickFormatter={formatGraphTick}
                        tick={{ fill: '#627d98', fontSize: 12 }}
                        minTickGap={24}
                      />
                      <YAxis tick={{ fill: '#627d98', fontSize: 12 }} width={38} />
                      <Tooltip labelFormatter={(value) => new Date(value).toLocaleString()} />
                      <Line type="monotone" dataKey="temp" stroke="#f97316" dot={false} strokeWidth={2} name="Temp C" />
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
                        domain={['dataMin', 'dataMax']}
                        tickFormatter={formatGraphTick}
                        tick={{ fill: '#627d98', fontSize: 12 }}
                        minTickGap={24}
                      />
                      <YAxis tick={{ fill: '#627d98', fontSize: 12 }} width={44} />
                      <Tooltip
                        labelFormatter={(value) => new Date(value).toLocaleString()}
                        formatter={(value) => `${Number(value ?? 0).toFixed(3)} Mbps`}
                      />
                      <Line type="monotone" dataKey="rxMbps" stroke="#2563eb" dot={false} strokeWidth={2} name="RX Mbps" />
                      <Line type="monotone" dataKey="txMbps" stroke="#d97706" dot={false} strokeWidth={2} name="TX Mbps" />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              </div>
            </div>
          </div>
        </section>
      )}

      {tab === 'liveu' && (
        <section className="grid">
          <div className="panel">
            <h3>Identity</h3>
            <p><strong>Base Unique ID:</strong> {identity?.base_unique_id || 'Unavailable'}</p>
            <p><strong>Server License:</strong> {identity?.server_license || 'Unavailable'}</p>
            <p><strong>Server Type:</strong> {identity?.server_type || 'Unknown'}</p>
          </div>

          {liveuConfig?.server_type === 'MMH/Transceiver' && (
            <div className="panel">
              <h3>MMH / Transceiver Configuration</h3>
              <p><strong>MMH Instances:</strong> {liveuConfig?.mmh?.mmh_instances ?? '-'}</p>
              <p><strong>External Preview TCP Port:</strong> {liveuConfig?.mmh?.external_preview_tcp_port ?? 'N/A'}</p>
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

          {liveuConfig?.server_type === 'Ingest' && (
            <div className="panel">
              <h3>Ingest Configuration (Read-Only)</h3>
              {(liveuConfig?.ingest?.port_candidates || []).length > 0 && (
                <>
                  <h4>Detected Port Constants</h4>
                  <ul>
                    {liveuConfig.ingest.port_candidates.map((p: any, idx: number) => (
                      <li key={`${p.file}-${p.name}-${idx}`}>{p.name} = {p.value} ({p.file})</li>
                    ))}
                  </ul>
                </>
              )}

              {(liveuConfig?.ingest?.files || []).map((f: any) => (
                <div key={f.path} className="code-wrap">
                  <h4>{f.path}</h4>
                  {!f.exists ? (
                    <div className="muted">File not found</div>
                  ) : (
                    <pre>
                      <code className="language-python">{f.content}</code>
                    </pre>
                  )}
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
        <section className="grid">
          <form className="panel form" onSubmit={onRestartLiveu}>
            <h3>Restart LiveU Service</h3>
            <p>Confirmation required: re-enter your password.</p>
            <label>
              Password
              <input type="password" value={restartPassword} onChange={(e) => setRestartPassword(e.target.value)} />
            </label>
            <button className="inline-spinner-btn" disabled={restartBusy}>
              {restartBusy && <span className="button-spinner" aria-hidden="true" />}
              {restartBusy
                ? `Restarting (${restartLiveuStatus || 'checking'})...`
                : 'Restart LiveU Service'}
            </button>
            {restartMessage && <div className="info">{restartMessage}</div>}
            {restartError && <div className="error">{restartError}</div>}
          </form>

          <form className="panel form" onSubmit={onReboot}>
            <h3>Reboot Server</h3>
            <p>Confirmation required: re-enter your password and type <strong>REBOOT</strong>.</p>
            <label>
              Password
              <input type="password" value={rebootPassword} onChange={(e) => setRebootPassword(e.target.value)} />
            </label>
            <label>
              Type REBOOT
              <input value={rebootConfirm} onChange={(e) => setRebootConfirm(e.target.value)} />
            </label>
            <button 
              className={`danger${(rebootBusy || rebootWaiting) ? ' inline-spinner-btn' : ''}`} 
              disabled={rebootBusy || rebootWaiting}
            >
              {(rebootBusy || rebootWaiting) && <span className="button-spinner" aria-hidden="true" />}
              {rebootBusy
                ? 'Rebooting...'
                : rebootWaiting
                  ? 'Waiting for server to reboot...'
                  : 'Reboot Server'}
            </button>
            {rebootMessage && <div className="info">{rebootMessage}</div>}
            {rebootError && <div className="error">{rebootError}</div>}
          </form>

          <form className="panel form" onSubmit={onRunSpeedtest}>
            <h3>Network Speed Test</h3>
            <button className="inline-spinner-btn" disabled={speedtestBusy}>
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
          </form>
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
