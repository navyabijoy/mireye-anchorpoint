import React from 'react';
import {
  Radar, RadarChart, PolarGrid, PolarAngleAxis, PolarRadiusAxis, ResponsiveContainer
} from 'recharts';
import type { CandidateSite } from '../types';

interface ScoreBreakdownProps {
  site: CandidateSite;
  weights: { transport: number; power: number; buildability: number; context: number; hazard: number; };
}

export const ScoreBreakdown: React.FC<ScoreBreakdownProps> = ({ site, weights }) => {
  const score = site.score;
  if (!score) return null;

  const dims = score.dimension_scores_json;

  const data = [
    { name: 'Transport', score: dims.transport ?? 0, weight: weights.transport },
    { name: 'Utilities', score: dims.power ?? 0, weight: weights.power },
    { name: 'Buildability', score: dims.buildability ?? 0, weight: weights.buildability },
    { name: 'Labor', score: dims.context ?? 0, weight: weights.context },
    { name: 'Hazards', score: dims.hazard ?? 0, weight: weights.hazard },
  ];

  const barColor = (v: number) => v >= 0.75 ? '#16a34a' : v >= 0.5 ? '#d97706' : '#dc2626';

  return (
    <div style={{ paddingTop: 14, paddingBottom: 8 }}>
      <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: 10 }}>
        Score Breakdown
      </div>

      {/* Compact radar */}
      <div style={{ height: 160, marginBottom: 10 }}>
        <ResponsiveContainer width="100%" height="100%">
          <RadarChart cx="50%" cy="50%" outerRadius="65%" data={data}>
            <PolarGrid stroke="var(--border)" />
            <PolarAngleAxis dataKey="name" tick={{ fill: 'var(--text-muted)', fontSize: 10, fontFamily: 'Inter' }} />
            <PolarRadiusAxis angle={30} domain={[0, 1]} tick={false} axisLine={false} />
            <Radar name={site.name} dataKey="score" stroke="#111827" fill="#111827" fillOpacity={0.12} strokeWidth={1.5} />
          </RadarChart>
        </ResponsiveContainer>
      </div>

      {/* Bar list */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 7 }}>
        {data.map((d, i) => (
          <div key={i}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, marginBottom: 3 }}>
              <span style={{ color: 'var(--text-secondary)', fontWeight: 500 }}>{d.name}</span>
              <div style={{ display: 'flex', gap: 8 }}>
                <span style={{ color: 'var(--text-muted)' }}>{(d.weight * 100).toFixed(0)}%</span>
                <span style={{ fontWeight: 700, color: barColor(d.score) }}>{(d.score * 100).toFixed(0)}%</span>
              </div>
            </div>
            <div style={{ height: 3, background: 'var(--surface-3)', borderRadius: 99, overflow: 'hidden' }}>
              <div style={{ height: '100%', width: `${d.score * 100}%`, background: barColor(d.score), borderRadius: 99, transition: 'width .5s ease' }} />
            </div>
          </div>
        ))}
      </div>

      {score.composite_score === null && (
        <div style={{
          marginTop: 10, padding: '8px 10px', background: 'var(--red-bg)', borderRadius: 'var(--radius-sm)',
          fontSize: 11, color: 'var(--red-text)', lineHeight: 1.5
        }}>
          <strong>⚠ Insufficient data</strong> — below 50% completeness ({score.data_completeness_pct.toFixed(0)}%). Score withheld.
        </div>
      )}
    </div>
  );
};
