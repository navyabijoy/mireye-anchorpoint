export interface Run {
  id: string;
  name: string;
  status: 'pending' | 'processing_demand' | 'demand_completed' | 'processing_scoring' | 'completed' | 'failed';
  hub_count: number;
  transport_weight: number;
  power_weight: number;
  buildability_weight: number;
  context_weight: number;
  hazard_weight: number;
  created_at: string;
  regions: CandidateRegion[];
}

export interface CandidateRegion {
  id: string;
  run_id: string;
  centroid_lat: number;
  centroid_lng: number;
  radius_km: number;
  name: string;
}

export interface SiteScore {
  dimension_scores_json: Record<string, number>;
  composite_score: number | null;
  data_completeness_pct: number;
  scored_at: string;
  scoring_version: string;
}

export interface CandidateSite {
  id: string;
  region_id: string;
  name: string;
  lat: number;
  lng: number;
  is_synthetic: boolean;
  source: string;
  parcel_ref?: string;
  score?: SiteScore | null;
}

export interface CitationDetail {
  field_name: string;
  // Narrowed from any — Mireye returns strings, numbers, or booleans
  value: string | number | boolean | null;
  unit: string | null;
  source: string | null;
  source_url: string | null;
  confidence: string | null;
  fetched_at: string | null;
  present: boolean;
  error: string | null;
}

export interface SiteCitations {
  site_id: string;
  name: string;
  lat: number;
  lng: number;
  is_synthetic: boolean;
  citations: Record<string, CitationDetail[]>;
}

export interface ProgressMessage {
  type: 'progress' | 'status';
  status?: string;
  site_id?: string;
  site_name?: string;
  progress?: number;
  message: string;
}
