import { useState, useEffect, useCallback } from 'react';
import {
  Upload,
  MapPin,
  FileText,
  ChevronRight,
  Loader2,
  ShieldAlert,
  MoreHorizontal,
  CheckCircle2,
  FileSpreadsheet,
  TriangleAlert,
  Menu,
  X,
  List,
  Map as MapIcon,
} from 'lucide-react';

import type { Run, CandidateRegion, CandidateSite, SiteCitations } from './types';
import { Map } from './components/Map';
import { ScoreBreakdown } from './components/ScoreBreakdown';
import { CitationDrillDown } from './components/CitationDrillDown';
import { ProgressTracker } from './components/ProgressTracker';

const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000/api';

function StatusPill({ status }: { status: string }) {
  if (status === 'completed')
    return <span className="pill pill-green">Complete</span>;
  if (status === 'demand_completed')
    return <span className="pill pill-blue">Stage 1 Done</span>;
  if (status.startsWith('processing'))
    return <span className="pill pill-amber blink">Evaluating</span>;
  if (status === 'failed')
    return <span className="pill pill-red">Failed</span>;
  return <span className="pill pill-gray">{status}</span>;
}

export default function App() {
  const [runs, setRuns] = useState<Run[]>([]);
  const [activeRun, setActiveRun] = useState<Run | null>(null);
  const [activeRegion, setActiveRegion] = useState<CandidateRegion | null>(null);
  const [sites, setSites] = useState<CandidateSite[]>([]);
  const [selectedSite, setSelectedSite] = useState<CandidateSite | null>(null);
  const [citations, setCitations] = useState<SiteCitations | null>(null);

  const [runsLoading, setRunsLoading] = useState(true);
  const [sitesLoading, setSitesLoading] = useState(false);
  const [citationsLoading, setCitationsLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [scoringTriggered, setScoringTriggered] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const [activeTab, setActiveTab] = useState<'new' | 'history'>('new');
  const [runName, setRunName] = useState('Siting Run ' + new Date().toLocaleDateString());
  const [hubCount, setHubCount] = useState(2);
  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [dragActive, setDragActive] = useState(false);

  const [leftPanelOpen, setLeftPanelOpen] = useState(false);
  const [mobileView, setMobileView] = useState<'map' | 'list'>('map');

  const [weights, setWeights] = useState({
    transport: 0.2,
    power: 0.2,
    buildability: 0.2,
    context: 0.2,
    hazard: 0.2,
  });

  const handleSelectRun = useCallback((run: Run) => {
    setActiveRun(run);
    setSelectedSite(null);
    setScoringTriggered(false);
    if (run.regions && run.regions.length > 0) setActiveRegion(run.regions[0]);
    else setActiveRegion(null);
  }, []);

  const fetchRuns = useCallback(async () => {
    setRunsLoading(true);
    try {
      const res = await fetch(`${API_BASE}/runs`);
      if (res.ok) {
        const data = await res.json();
        setRuns(data);
        if (data.length > 0) {
          setActiveRun((currentActive) => {
            if (!currentActive) {
              handleSelectRun(data[0]);
            } else {
              const freshActive = data.find((r: Run) => r.id === currentActive.id);
              if (freshActive) setActiveRun(freshActive);
            }
            return currentActive;
          });
        }
      }
    } catch (e) {
      console.error('Failed to fetch runs:', e);
    } finally {
      setRunsLoading(false);
    }
  }, [handleSelectRun]);

  useEffect(() => { fetchRuns(); }, [fetchRuns]);

  useEffect(() => {
    if (activeRun && activeRegion) {
      fetchRegionSites(activeRun.id, activeRegion.id);
    } else {
      setSites([]);
      setSelectedSite(null);
    }
  }, [activeRun, activeRegion]);

  useEffect(() => {
    if (selectedSite) fetchSiteCitations(selectedSite.id);
    else setCitations(null);
  }, [selectedSite]);

  const fetchRegionSites = async (runId: string, regionId: string) => {
    setSitesLoading(true);
    try {
      const res = await fetch(`${API_BASE}/runs/${runId}/sites?region_id=${regionId}`);
      if (res.ok) {
        const data = await res.json();
        const sorted = data.sort((a: CandidateSite, b: CandidateSite) => {
          const sa = a.score?.composite_score ?? -1;
          const sb = b.score?.composite_score ?? -1;
          return sb - sa;
        });
        setSites(sorted);
        if (sorted.length > 0) setSelectedSite(sorted[0]);
      }
    } catch (e) {
      console.error('Failed to fetch sites:', e);
    } finally {
      setSitesLoading(false);
    }
  };

  const fetchSiteCitations = async (siteId: string) => {
    setCitationsLoading(true);
    try {
      const res = await fetch(`${API_BASE}/sites/${siteId}/citations`);
      if (res.ok) setCitations(await res.json());
    } catch (e) {
      console.error('Failed to fetch citations:', e);
    } finally {
      setCitationsLoading(false);
    }
  };

  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault(); e.stopPropagation();
    setDragActive(e.type === 'dragenter' || e.type === 'dragover');
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault(); e.stopPropagation();
    setDragActive(false);
    if (e.dataTransfer.files?.[0]) setCsvFile(e.dataTransfer.files[0]);
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files?.[0]) setCsvFile(e.target.files[0]);
  };

  const handleSubmitRun = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!csvFile) return;
    setUploading(true);
    setErrorMessage(null);
    const fd = new FormData();
    fd.append('file', csvFile);
    fd.append('name', runName);
    fd.append('hub_count', hubCount.toString());
    fd.append('transport_weight', weights.transport.toString());
    fd.append('power_weight', weights.power.toString());
    fd.append('buildability_weight', weights.buildability.toString());
    fd.append('context_weight', weights.context.toString());
    fd.append('hazard_weight', weights.hazard.toString());
    try {
      const res = await fetch(`${API_BASE}/runs`, { method: 'POST', body: fd });
      if (res.ok) {
        const data = await res.json();
        setRuns((p) => [data, ...p]);
        handleSelectRun(data);
        setCsvFile(null);
        setActiveTab('history');
      } else {
        const err = await res.json();
        setErrorMessage(`Siting run failed: ${err.detail}`);
      }
    } catch {
      setErrorMessage('Network error submitting siting run.');
    } finally {
      setUploading(false);
    }
  };

  const handleTriggerScoring = async () => {
    if (!activeRun || !activeRegion) return;
    setScoringTriggered(true);
    setErrorMessage(null);
    try {
      const res = await fetch(`${API_BASE}/runs/${activeRun.id}/score?region_id=${activeRegion.id}`, { method: 'POST' });
      if (!res.ok) {
        setErrorMessage(`Failed to queue scoring: ${(await res.json()).detail}`);
        setScoringTriggered(false);
      }
    } catch {
      setScoringTriggered(false);
    }
  };

  const handleScoringComplete = () => {
    setScoringTriggered(false);
    if (activeRun && activeRegion) {
      fetchRegionSites(activeRun.id, activeRegion.id);
      fetchRuns();
    }
  };

  const generateSampleData = () => {
    const csv =
      'zip_code,order_count,revenue\n10001,45,2250.0\n90210,32,1920.0\n60601,60,3000.0\n77001,25,1250.0\n33101,18,900.0\n94102,40,2400.0\n02108,15,750.0\n98101,28,1400.0\n30301,35,1750.0\n80201,22,1100.0\n75201,29,1450.0\n19102,21,1050.0\n';
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }));
    Object.assign(document.createElement('a'), { href: url, download: 'anchorpoint_sample_orders.csv' }).click();
    URL.revokeObjectURL(url);
  };

  const isScoring = scoringTriggered || activeRun?.status === 'processing_scoring';

  return (
    <>
      {leftPanelOpen && (
        <div className="drawer-backdrop print-hide" onClick={() => setLeftPanelOpen(false)} />
      )}
      <div className="app-shell">
        {/* ── Error Banner ──────────────────────────────── */}
      {errorMessage && (
        <div style={{
          position: 'fixed', top: 0, left: 0, right: 0, zIndex: 9999,
          background: 'var(--red-bg)', color: 'var(--red-text)',
          padding: '10px 20px', fontSize: 13, fontWeight: 600,
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          borderBottom: '1px solid var(--red)',
        }}>
          <span>⚠ {errorMessage}</span>
          <button
            onClick={() => setErrorMessage(null)}
            style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 18, color: 'var(--red-text)', lineHeight: 1 }}
          >×</button>
        </div>
      )}
      {/* ── Nav Rail ──────────────────────────────── */}
      <nav className="nav-rail print-hide">
        <div className="nav-logo">
          <MapPin size={16} />
        </div>
        <div className="nav-items">
          <button
            className="nav-item"
            title="Export PDF"
            onClick={() => window.print()}
            style={{ cursor: 'pointer' }}
          >
            <FileText size={18} />
          </button>
        </div>
      </nav>

      {/* ── Left Panel ────────────────────────────── */}
      <aside className={`left-panel print-hide ${leftPanelOpen ? 'open' : ''}`}>
        {/* Header */}
        <div className="panel-header">
          <span className="panel-title">Anchorpoint</span>
          <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
            <button className="mobile-close-btn print-hide" onClick={() => setLeftPanelOpen(false)}>
              <X size={18} />
            </button>
            <button style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-muted)', padding: '4px' }}>
              <MoreHorizontal size={18} />
            </button>
          </div>
        </div>

        {/* Tab Bar */}
        <div className="tab-bar">
          <button className={`tab-btn ${activeTab === 'history' ? 'active' : ''}`} onClick={() => setActiveTab('history')}>
            History
          </button>
          <button className={`tab-btn ${activeTab === 'new' ? 'active' : ''}`} onClick={() => setActiveTab('new')}>
            New Analysis
          </button>
        </div>

        {/* ── History Tab ── */}
        {activeTab === 'history' && (
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
            <div className="section-label">Siting Runs</div>
            <div className="sites-list" style={{ padding: '0 12px 12px' }}>
              {runsLoading ? (
                <div className="empty-state">
                  <Loader2 size={22} className="spin" style={{ color: 'var(--text-muted)' }} />
                </div>
              ) : runs.length === 0 ? (
                <div className="empty-state">
                  <TriangleAlert size={28} className="empty-icon" />
                  <span className="empty-title">No runs yet</span>
                  <span className="empty-body">Create a new analysis to get started.</span>
                </div>
              ) : (
                runs.map((r) => (
                  <div
                    key={r.id}
                    className={`item-card ${activeRun?.id === r.id ? 'active' : ''}`}
                    onClick={() => handleSelectRun(r)}
                  >
                    <div className="item-body">
                      <div className="item-name">{r.name}</div>
                      <div className="item-sub">
                        {r.hub_count} hub{r.hub_count !== 1 ? 's' : ''} · {new Date(r.created_at).toLocaleDateString()}
                      </div>
                    </div>
                    <StatusPill status={r.status} />
                  </div>
                ))
              )}
            </div>
          </div>
        )}

        {/* ── New Analysis Tab ── */}
        {activeTab === 'new' && (
          <form onSubmit={handleSubmitRun} style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
            <div className="form-section" style={{ flex: 1, overflowY: 'auto', paddingTop: 14 }}>
              {/* Analysis Name */}
              <div className="field-row">
                <label className="field-label">Analysis Name</label>
                <input
                  type="text"
                  className="field-input"
                  value={runName}
                  onChange={(e) => setRunName(e.target.value)}
                  required
                />
              </div>

              {/* Hub Count */}
              <div className="field-row">
                <label className="field-label">
                  Network Hubs (k)
                  <span style={{ float: 'right', fontWeight: 700, color: 'var(--text-primary)', textTransform: 'none', letterSpacing: 0 }}>
                    {hubCount}
                  </span>
                </label>
                <input
                  type="range" min={1} max={5} step={1}
                  value={hubCount}
                  onChange={(e) => setHubCount(parseInt(e.target.value))}
                  className="weight-slider"
                  style={{ width: '100%', marginTop: 6 }}
                />
              </div>

              {/* CSV Upload */}
              <div className="field-row">
                <label className="field-label">Demand Geography (CSV)</label>
                <label
                  htmlFor="csv-file-input"
                  className={`dropzone ${dragActive ? 'drag-active' : ''} ${csvFile ? 'has-file' : ''}`}
                  onDragEnter={handleDrag}
                  onDragOver={handleDrag}
                  onDragLeave={handleDrag}
                  onDrop={handleDrop}
                >
                  <input id="csv-file-input" type="file" accept=".csv" onChange={handleFileChange} style={{ display: 'none' }} />
                  <Upload size={18} style={{ margin: '0 auto 6px', display: 'block', color: csvFile ? 'var(--green-text)' : 'var(--text-muted)' }} />
                  {csvFile ? (
                    <p style={{ fontSize: 12, fontWeight: 600, color: 'var(--green-text)' }}>{csvFile.name}</p>
                  ) : (
                    <>
                      <p style={{ fontSize: 12, color: 'var(--text-secondary)' }}>Drag & drop or click to browse</p>
                      <p style={{ fontSize: 10.5, color: 'var(--text-muted)', marginTop: 2 }}>Requires zip_code or lat/lng columns</p>
                    </>
                  )}
                </label>
              </div>

              {/* Scoring Weights */}
              <div className="field-row">
                <label className="field-label" style={{ marginBottom: 10 }}>Scoring Weights</label>
                {([
                  { key: 'transport', label: 'Transport' },
                  { key: 'power', label: 'Utilities' },
                  { key: 'buildability', label: 'Buildability' },
                  { key: 'context', label: 'Labor Proxy' },
                  { key: 'hazard', label: 'Hazards' },
                ] as const).map((w) => (
                  <div key={w.key} className="weight-row">
                    <span className="weight-label">{w.label}</span>
                    <input
                      type="range" min={0} max={1} step={0.05}
                      value={weights[w.key]}
                      onChange={(e) => setWeights((p) => ({ ...p, [w.key]: parseFloat(e.target.value) }))}
                      className="weight-slider"
                    />
                    <span className="weight-value">{(weights[w.key] * 100).toFixed(0)}%</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Sticky bottom actions */}
            <div style={{ padding: '14px 20px 16px', borderTop: '1px solid var(--border)', flexShrink: 0 }}>
              <button type="submit" className="btn-primary" disabled={uploading || !csvFile}>
                {uploading ? <><Loader2 size={14} className="spin" /> Generating Centroids…</> : 'Run Stage 1 Clustering'}
              </button>
              <button type="button" className="btn-ghost" onClick={generateSampleData}>
                <FileSpreadsheet size={13} /> Download Sample CSV
              </button>
            </div>
          </form>
        )}
      </aside>

      {/* ── Main Area ─────────────────────────────── */}
      <main className="main-area">
        {/* Top Bar */}
        <div className="top-bar">
          <div className="breadcrumb">
            <button className="menu-btn print-hide" onClick={() => setLeftPanelOpen(true)}>
              <Menu size={18} />
            </button>
            <span>Analysis</span>
            {activeRun && (
              <>
                <span className="breadcrumb-sep">›</span>
                <span className="breadcrumb-name">{activeRun.name}</span>
                {activeRun.regions.length > 0 && (
                  <>
                    <span className="breadcrumb-sep">›</span>
                    <select
                      className="region-select"
                      value={activeRegion?.id || ''}
                      onChange={(e) => {
                        const reg = activeRun.regions.find((r) => r.id === e.target.value);
                        if (reg) setActiveRegion(reg);
                      }}
                    >
                      {activeRun.regions.map((reg) => (
                        <option key={reg.id} value={reg.id}>{reg.name}</option>
                      ))}
                    </select>
                  </>
                )}
              </>
            )}
            {!activeRun && <span style={{ color: 'var(--text-muted)', fontStyle: 'italic' }}>No active analysis</span>}
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            {activeRun && (
              <StatusPill status={activeRun.status} />
            )}
            {activeRegion && (
              <button
                className="btn-cta"
                onClick={handleTriggerScoring}
                disabled={!!isScoring}
              >
                {isScoring
                  ? <><Loader2 size={13} className="spin" /> Evaluating…</>
                  : <><CheckCircle2 size={13} /> Trigger Stage 2 Scoring</>}
              </button>
            )}
          </div>
        </div>

        {/* Content Grid */}
        <div className={`content-grid mobile-view-${mobileView}`}>
          {/* Map */}
          <div className="map-wrapper print-hide">
            {/* Progress tracker floats above map */}
            {isScoring && activeRun && (
              <div style={{
                position: 'absolute', top: 16, left: 16, right: 16, zIndex: 900,
                background: 'rgba(255,255,255,0.96)', backdropFilter: 'blur(10px)',
                borderRadius: 'var(--radius-lg)',
                border: '1.5px solid var(--border)',
                boxShadow: '0 4px 24px rgba(0,0,0,.1)',
                padding: '14px 18px'
              }}>
                <ProgressTracker runId={activeRun.id} onScoringComplete={handleScoringComplete} />
              </div>
            )}

            <Map
              regions={activeRun?.regions || []}
              sites={sites}
              selectedSite={selectedSite}
              onSelectSite={setSelectedSite}
            />

            {/* Site info bar overlaid at bottom of map */}
            {selectedSite && (
              <div className="map-overlay-bar">
                <div className="site-info-bar fadein">
                  <span className="sib-id">{selectedSite.name}</span>
                  {selectedSite.is_synthetic && (
                    <span className="pill pill-indigo" style={{ marginRight: 8 }}>Illustrative</span>
                  )}
                  <div className="sib-divider" />
                  <div className="sib-stat">
                    <div className="sib-stat-label">Lat</div>
                    <div className="sib-stat-value">{selectedSite.lat.toFixed(4)}</div>
                  </div>
                  <div className="sib-stat">
                    <div className="sib-stat-label">Lng</div>
                    <div className="sib-stat-value">{selectedSite.lng.toFixed(4)}</div>
                  </div>
                  {selectedSite.score?.composite_score != null && (
                    <>
                      <div className="sib-divider" />
                      <div className="sib-stat">
                        <div className="sib-stat-label">Composite Score</div>
                        <div className="sib-stat-value">{selectedSite.score.composite_score.toFixed(3)}</div>
                      </div>
                      <div className="sib-stat">
                        <div className="sib-stat-label">Data Completeness</div>
                        <div className="sib-stat-value">{selectedSite.score.data_completeness_pct.toFixed(0)}%</div>
                      </div>
                    </>
                  )}
                  {selectedSite.score?.composite_score === null && selectedSite.score != null && (
                    <>
                      <div className="sib-divider" />
                      <div style={{ display: 'flex', alignItems: 'center', gap: 6, color: 'var(--red-text)' }}>
                        <ShieldAlert size={15} />
                        <span style={{ fontSize: 12, fontWeight: 700 }}>Insufficient data to rank</span>
                      </div>
                    </>
                  )}
                </div>
              </div>
            )}
          </div>

          {/* Right Panel */}
          <aside className="right-panel">
            {/* Sites ranked list header */}
            <div className="rp-header">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span className="rp-title">Candidate Sites</span>
                <span style={{ fontSize: 11, color: 'var(--text-muted)', fontWeight: 600 }}>
                  {sites.length} found
                </span>
              </div>
              <div className="rp-sub">Ranked by composite score</div>
            </div>

            {/* Single scrollable body for everything below header */}
            <div className="right-panel-scrollable" style={{ flex: 1, overflowY: 'auto', overflowX: 'hidden' }}>
              {/* Sites list */}
              <div style={{ padding: '10px 12px 4px' }}>
                {sitesLoading ? (
                  <div className="empty-state" style={{ padding: '24px 0' }}>
                    <Loader2 size={20} className="spin" style={{ color: 'var(--text-muted)' }} />
                  </div>
                ) : sites.length === 0 ? (
                  <div className="empty-state" style={{ padding: '24px 0' }}>
                    <TriangleAlert size={24} className="empty-icon" />
                    <span className="empty-title">No candidates yet</span>
                    <span className="empty-body">Trigger Stage 2 Scoring to evaluate sites.</span>
                  </div>
                ) : (
                  sites.map((s, idx) => {
                    const hasScore = s.score?.composite_score != null;
                    const isInsufficient = s.score != null && s.score.composite_score === null;
                    return (
                      <div
                        key={s.id}
                        className={`item-card ${selectedSite?.id === s.id ? 'active' : ''}`}
                        onClick={() => setSelectedSite(s)}
                      >
                        <span className="item-rank">#{idx + 1}</span>
                        <div className="item-body">
                          <div className="item-name">{s.name}</div>
                          <div style={{ display: 'flex', alignItems: 'center', gap: 5, marginTop: 3 }}>
                            {s.is_synthetic && <span className="pill pill-indigo" style={{ fontSize: 9, padding: '1px 6px' }}>Illustrative</span>}
                            <span className="item-sub" style={{ marginTop: 0 }}>
                              {s.lat.toFixed(4)}, {s.lng.toFixed(4)}
                            </span>
                          </div>
                        </div>
                        <div className="item-score">
                          {hasScore ? (
                            <>
                              <span className="score-num">{s.score!.composite_score!.toFixed(2)}</span>
                              <span className="score-label">{s.score!.data_completeness_pct.toFixed(0)}% data</span>
                            </>
                          ) : isInsufficient ? (
                            <div style={{ display: 'flex', alignItems: 'center', gap: 4, color: 'var(--red-text)' }}>
                              <ShieldAlert size={13} />
                              <span style={{ fontSize: 10, fontWeight: 700 }}>N/A</span>
                            </div>
                          ) : (
                            <span style={{ fontSize: 10, color: 'var(--text-muted)', fontStyle: 'italic' }}>—</span>
                          )}
                        </div>
                      </div>
                    );
                  })
                )}
              </div>

              {/* Score Breakdown */}
              {selectedSite && selectedSite.score?.composite_score != null && (
                <div style={{ padding: '0 14px', borderTop: '1px solid var(--border)' }}>
                  <ScoreBreakdown site={selectedSite} weights={weights} />
                </div>
              )}

              {/* Citations provenance */}
              <div style={{ borderTop: '1px solid var(--border)' }}>
                <div className="rp-header">
                  <span className="rp-title">Federal Provenance</span>
                  <div className="rp-sub">Source citations per field</div>
                </div>
                <div style={{ padding: '0 14px 20px' }}>
                  {selectedSite ? (
                    <CitationDrillDown
                      site={selectedSite}
                      citations={citations}
                      isLoading={citationsLoading}
                    />
                  ) : (
                    <div className="empty-state">
                      <ChevronRight size={24} className="empty-icon" />
                      <span className="empty-title">Select a site</span>
                      <span className="empty-body">Click any candidate to view its federal data provenance log.</span>
                    </div>
                  )}
                </div>
              </div>
            </div>
          </aside>
        </div>

        {/* ── Mobile View Toggle ── */}
        <div className="mobile-view-toggle print-hide">
          <button className={`mvt-btn ${mobileView === 'map' ? 'active' : ''}`} onClick={() => setMobileView('map')}>
            <MapIcon size={16} /> Map
          </button>
          <button className={`mvt-btn ${mobileView === 'list' ? 'active' : ''}`} onClick={() => setMobileView('list')}>
            <List size={16} /> Candidates
          </button>
        </div>
      </main>
    </div>
    </>
  );
}
