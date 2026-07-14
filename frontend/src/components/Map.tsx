import React, { useEffect, useMemo } from 'react';
import { MapContainer, TileLayer, Marker, Popup, Circle, useMap } from 'react-leaflet';
import L from 'leaflet';
import type { CandidateRegion, CandidateSite } from '../types';
import markerIcon2x from 'leaflet/dist/images/marker-icon-2x.png';
import markerIcon from 'leaflet/dist/images/marker-icon.png';
import markerShadow from 'leaflet/dist/images/marker-shadow.png';

delete (L.Icon.Default.prototype as any)._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: markerIcon2x,
  iconUrl: markerIcon,
  shadowUrl: markerShadow,
});

interface MapProps {
  regions: CandidateRegion[];
  sites: CandidateSite[];
  selectedSite: CandidateSite | null;
  onSelectSite: (site: CandidateSite) => void;
}

// Helper to auto-focus the map on coordinates when they change
const MapController: React.FC<{ center: [number, number]; zoom: number }> = ({ center, zoom }) => {
  const map = useMap();
  useEffect(() => {
    map.setView(center, zoom);
  }, [center, zoom, map]);
  return null;
};

const MapComponent: React.FC<MapProps> = ({ regions, sites, selectedSite, onSelectSite }) => {
  // Determine map center
  let center: [number, number] = [39.8283, -98.5795]; // Geographical center of USA
  let zoom = 4;

  if (selectedSite) {
    center = [selectedSite.lat, selectedSite.lng];
    zoom = 11;
  } else if (regions.length > 0) {
    center = [regions[0].centroid_lat, regions[0].centroid_lng];
    zoom = 7;
  }

  // Build site icon configs — memoized so L.divIcon objects are only rebuilt when
  // the selection or score data actually changes, not on every parent re-render.
  const siteIconMap = useMemo(() => {
    const iconMap = new Map<string, ReturnType<typeof L.divIcon>>();
    for (const site of sites) {
      const isSelected = selectedSite?.id === site.id;
      const score = site.score?.composite_score;
      const completeness = site.score?.data_completeness_pct ?? 0;

      let color = '#9ca3af';
      if (site.score && score !== null) {
        if (score >= 0.75) color = '#16a34a';
        else if (score >= 0.5) color = '#d97706';
        else color = '#dc2626';
      } else if (site.score && completeness < 50.0) {
        color = '#6b7280';
      }

      const size = isSelected ? 34 : 26;
      const innerSize = isSelected ? 12 : 10;
      const borderStyle = isSelected ? '2.5px solid #ffffff' : '2.5px solid #0f172a';
      const background = isSelected ? '#0f172a' : '#ffffff';
      const boxShadow = isSelected
        ? '0 4px 12px rgba(0,0,0,0.4), 0 0 0 1px rgba(0,0,0,0.15)'
        : '0 3px 8px rgba(0,0,0,0.3)';

      iconMap.set(site.id, L.divIcon({
        className: 'custom-div-icon',
        html: `
          <div style="position:relative;display:flex;align-items:center;justify-content:center;width:${size}px;height:${size}px">
            <div style="position:absolute;inset:0;border-radius:50%;background:${background};border:${borderStyle};box-shadow:${boxShadow};display:flex;align-items:center;justify-content:center">
              <div style="width:${innerSize}px;height:${innerSize}px;border-radius:50%;background:${color};"></div>
            </div>
            ${site.is_synthetic ? `<div style="position:absolute;top:-2px;right:-2px;width:10px;height:10px;background:#7c3aed;border-radius:50%;border:1.5px solid white;box-shadow:0 1px 3px rgba(0,0,0,0.3)"></div>` : ''}
          </div>
        `,
        iconSize: [size, size],
        iconAnchor: [size / 2, size / 2],
      }));
    }
    return iconMap;
    // Recompute only when sites list, scores, or selected site changes
  }, [sites, selectedSite?.id]);

  const mapKey = regions.map(r => r.id).join('-');


  return (
    <div style={{ width: '100%', height: '100%', position: 'relative' }}>
      <MapContainer
        key={mapKey || 'empty'}
        center={center}
        zoom={zoom}
        style={{ width: '100%', height: '100%' }}
        scrollWheelZoom={true}
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />

        {/* Render Candidate Regions (Stage 1 output) */}
        {regions.map((region) => (
          <Circle
            key={region.id}
            center={[region.centroid_lat, region.centroid_lng]}
            radius={region.radius_km * 1000}
            pathOptions={{
              fillColor: '#3b82f6',
              fillOpacity: 0.07,
              color: '#3b82f6',
              weight: 1.5,
              dashArray: '5, 8'
            }}
          >
            <Popup>
              <div style={{ padding: '4px 2px' }}>
                <p style={{ fontWeight: 700, fontSize: 13 }}>{region.name}</p>
                <p style={{ fontSize: 11, color: '#6b7280', marginTop: 2 }}>Siting Radius: {region.radius_km.toFixed(1)} km</p>
              </div>
            </Popup>
          </Circle>
        ))}

        {/* Render Candidate Sites */}
        {sites.map((site) => (
          <Marker
            key={site.id}
            position={[site.lat, site.lng]}
            icon={siteIconMap.get(site.id)}
            eventHandlers={{
              click: () => onSelectSite(site),
            }}
          >
            <Popup>
              <div style={{ padding: '4px 2px', minWidth: 160 }}>
                <p style={{ fontWeight: 700, fontSize: 13, lineHeight: 1.3 }}>{site.name}</p>
                <p style={{ fontSize: 11, color: '#9ca3af', marginTop: 2 }}>
                  {site.is_synthetic ? '📌 Illustrative Site' : site.source}
                </p>
                {site.score ? (
                  <div style={{ marginTop: 8, paddingTop: 6, borderTop: '1px solid #e5e7eb' }}>
                    <p style={{ fontSize: 12, fontWeight: 700 }}>
                      Score:{' '}
                      <span style={{ color: '#1d4ed8' }}>
                        {site.score.composite_score !== null ? site.score.composite_score.toFixed(3) : 'Insufficient Data'}
                      </span>
                    </p>
                    <p style={{ fontSize: 10, color: '#9ca3af' }}>Completeness: {site.score.data_completeness_pct.toFixed(0)}%</p>
                  </div>
                ) : (
                  <p style={{ fontSize: 11, marginTop: 4, color: '#6b7280', fontStyle: 'italic' }}>Not scored yet</p>
                )}
              </div>
            </Popup>
          </Marker>
        ))}

        <MapController center={center} zoom={zoom} />
      </MapContainer>
    </div>
  );
};

export { MapComponent as Map };
