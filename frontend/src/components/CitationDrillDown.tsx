import React, { useState } from 'react';
import { ShieldAlert, Sparkles, HelpCircle, ChevronDown, ChevronUp, Loader2 } from 'lucide-react';
import type { CandidateSite, SiteCitations, CitationDetail } from '../types';

interface CitationDrillDownProps {
  site: CandidateSite;
  citations: SiteCitations | null;
  isLoading: boolean;
}

const AGENCY_COLORS: Record<string, { bg: string; text: string }> = {
  USGS:    { bg: '#dcfce7', text: '#15803d' },
  NOAA:    { bg: '#e0f2fe', text: '#0369a1' },
  WEATHER: { bg: '#e0f2fe', text: '#0369a1' },
  CENSUS:  { bg: '#ede9fe', text: '#5b21b6' },
  EIA:     { bg: '#fef3c7', text: '#92400e' },
  ENERGY:  { bg: '#fef3c7', text: '#92400e' },
  FHWA:    { bg: '#cffafe', text: '#0e7490' },
  DOT:     { bg: '#cffafe', text: '#0e7490' },
  BTS:     { bg: '#cffafe', text: '#0e7490' },
  FEMA:    { bg: '#fee2e2', text: '#b91c1c' },
  HAZARD:  { bg: '#fee2e2', text: '#b91c1c' },
};

function agencyColor(source: string | null) {
  if (!source) return { bg: '#f3f4f6', text: '#6b7280' };
  const upper = source.toUpperCase();
  for (const [key, val] of Object.entries(AGENCY_COLORS)) {
    if (upper.includes(key)) return val;
  }
  return { bg: '#f3f4f6', text: '#374151' };
}

const DIM_LABELS: Record<string, string> = {
  transport:    'Transport Access',
  power:        'Power & Utilities',
  buildability: 'Buildability & Zoning',
  context:      'Labor & Housing Context',
  hazard:       'Hazards & Insurability',
};

const FIELD_LABELS: Record<string, string> = {
  nearest_major_road_distance_m:       'Proximity to Major Road',
  roads_within_500m_count:             'Road Count within 500m',
  nearest_rail_line_distance_m:        'Proximity to Rail Line',
  nearest_transmission_line_distance_m:'Proximity to Transmission Line',
  nearest_transmission_line_voltage_kv:'Transmission Line Voltage',
  nearest_substation_distance_m:       'Proximity to Substation',
  parcel_zoning:                       'Parcel Zoning Class',
  parcel_area_m2:                      'Parcel Land Area',
  developable_acres_proxy:             'Developable Acres',
  grading_difficulty_class:            'Grading Difficulty',
  nearest_urban_area_distance_m:       'Proximity to Urban Area',
  housing_units_within_1km:            'Housing Units (1km)',
  housing_units_density_per_km2:       'Housing Unit Density',
  wildfire_annual_frequency:           'Wildfire Annual Frequency',
  within_floodplain_polygon:           'FEMA Floodplain',
  seismic_pga_2pct_50yr_g:             'Peak Ground Acceleration',
  design_wind_speed_mph:               'Design Wind Speed',
};

function formatVal(field: string, val: any, unit: string | null): string {
  if (val === null || val === undefined) return 'N/A';
  if (typeof val === 'boolean') return val ? 'Yes' : 'No';
  if (typeof val === 'number') {
    if (field === 'wildfire_annual_frequency') return `${(val * 100).toFixed(4)}%`;
    if (field === 'seismic_pga_2pct_50yr_g') return `${val.toFixed(3)}g`;
    if (field === 'parcel_area_m2') return `${val.toLocaleString()} m²`;
    return `${val.toLocaleString()}${unit ? ' ' + unit : ''}`;
  }
  return `${val}${unit ? ' ' + unit : ''}`;
}

export const CitationDrillDown: React.FC<CitationDrillDownProps> = ({ site, citations, isLoading }) => {
  const [expanded, setExpanded] = useState<string | null>('transport');

  if (isLoading) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {[1, 2, 3].map((n) => (
          <div key={n} style={{ height: 44, background: 'var(--surface-3)', borderRadius: 'var(--radius-md)', opacity: 0.7 }} className="blink" />
        ))}
      </div>
    );
  }

  if (!citations) {
    return (
      <div className="empty-state">
        <HelpCircle size={26} className="empty-icon" />
        <span className="empty-title">No citations loaded</span>
        <span className="empty-body">Select a scored site to view its federal data provenance.</span>
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      {/* Synthetic banner */}
      {site.is_synthetic && (
        <div style={{
          display: 'flex', gap: 10, padding: '10px 12px',
          background: '#ede9fe', borderRadius: 'var(--radius-md)',
          marginBottom: 4, marginTop: 12
        }}>
          <Sparkles size={15} style={{ color: '#7c3aed', flexShrink: 0, marginTop: 1 }} />
          <div>
            <div style={{ fontSize: 12, fontWeight: 700, color: '#5b21b6', marginBottom: 2 }}>Illustrative Siting Run</div>
            <div style={{ fontSize: 11, color: '#6d28d9', lineHeight: 1.5 }}>
              This site was auto-generated near the demand centroid.{' '}
              Coordinates are synthetic (<code style={{ background: '#ddd6fe', padding: '0 3px', borderRadius: 3 }}>is_synthetic: true</code>).
            </div>
          </div>
        </div>
      )}

      {/* Accordion */}
      {Object.entries(citations.citations).map(([dim, fields]) => {
        const isOpen = expanded === dim;
        const hasMissing = (fields as CitationDetail[]).some((f) => !f.present);

        return (
          <div key={dim} style={{ border: '1.5px solid var(--border)', borderRadius: 'var(--radius-md)', overflow: 'hidden' }}>
            {/* Trigger */}
            <button
              onClick={() => setExpanded(isOpen ? null : dim)}
              style={{
                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                width: '100%', padding: '10px 13px',
                background: isOpen ? 'var(--surface-2)' : 'var(--surface)',
                border: 'none', cursor: 'pointer', fontFamily: 'inherit',
                fontSize: 13, fontWeight: 600, color: 'var(--text-primary)',
                borderBottom: isOpen ? '1px solid var(--border)' : 'none',
                textAlign: 'left', gap: 8,
              }}
            >
              <span>{DIM_LABELS[dim] || dim}</span>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0 }}>
                {hasMissing && (
                  <ShieldAlert size={13} style={{ color: 'var(--amber-text)' }} />
                )}
                <span className="print-hide">
                  {isOpen ? <ChevronUp size={15} style={{ color: 'var(--text-muted)' }} /> : <ChevronDown size={15} style={{ color: 'var(--text-muted)' }} />}
                </span>
              </div>
            </button>

            {/* Body */}
            <div
              className="citation-body-panel"
              style={{
                background: 'var(--surface-2)',
                display: isOpen ? 'block' : 'none'
              }}
            >
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
                  <thead>
                    <tr style={{ borderBottom: '1px solid var(--border)', background: 'var(--surface-3)' }}>
                      <th style={{ padding: '7px 12px', textAlign: 'left', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.4px', fontSize: 10, whiteSpace: 'nowrap' }}>Field</th>
                      <th style={{ padding: '7px 10px', textAlign: 'left', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.4px', fontSize: 10, whiteSpace: 'nowrap' }}>Value</th>
                      <th style={{ padding: '7px 10px', textAlign: 'left', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.4px', fontSize: 10, whiteSpace: 'nowrap' }}>Source</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(fields as CitationDetail[]).map((f) => {
                      const { bg, text } = agencyColor(f.source);
                      return (
                        <tr key={f.field_name} style={{ borderBottom: '1px solid var(--border)' }}>
                          <td style={{ padding: '8px 12px', verticalAlign: 'top' }}>
                            <div style={{ fontWeight: 600, color: 'var(--text-primary)', fontSize: 12 }}>
                              {FIELD_LABELS[f.field_name] || f.field_name}
                            </div>
                            <div style={{ fontFamily: 'monospace', fontSize: 9.5, color: 'var(--text-muted)', marginTop: 1 }}>
                              {f.field_name}
                            </div>
                          </td>
                          <td style={{ padding: '8px 10px', fontWeight: 700, color: 'var(--text-primary)', verticalAlign: 'top', whiteSpace: 'nowrap' }}>
                            {f.present ? (
                              formatVal(f.field_name, f.value, f.unit)
                            ) : (
                              <span style={{ display: 'flex', alignItems: 'center', gap: 4, color: 'var(--amber-text)', fontWeight: 600, fontSize: 11 }}>
                                <ShieldAlert size={12} /> Unknown
                              </span>
                            )}
                          </td>
                          <td style={{ padding: '8px 10px', verticalAlign: 'top' }}>
                            <span style={{ display: 'inline-block', padding: '2px 7px', borderRadius: 99, background: bg, color: text, fontSize: 10, fontWeight: 700, whiteSpace: 'nowrap' }}>
                              {f.source || '—'}
                            </span>
                          </td>

                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              {hasMissing && (
                <div style={{ padding: '8px 12px', background: 'var(--amber-bg)', borderTop: '1px solid var(--border)', fontSize: 11, color: 'var(--amber-text)', lineHeight: 1.5 }}>
                  ⚠ One or more fields failed to fetch. Missing values are categorized as <strong>unknown</strong> and excluded from weight scoring (not zero-filled).
                </div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
};
