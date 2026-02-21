import axios from 'axios';

const API_BASE_URL = 'http://localhost:8000';

const api = axios.create({
  baseURL: API_BASE_URL,
});

export interface Firm {
  id: string;
  name: string;
  created_at?: string;
}

export interface Matter {
  id: string;
  firm_id: string;
  title: string;
  client_ref?: string;
  created_at?: string;
}

export interface Document {
  id: string;
  matter_id: string;
  filename: string;
  mime_type: string;
  sha256: string;
  bytes: number;
  uploaded_at: string;
}

export interface Run {
  id: string;
  matter_id: string;
  status: 'pending' | 'running' | 'success' | 'partial' | 'failed';
  started_at?: string;
  finished_at?: string;
  metrics?: Record<string, any>;
  warnings?: string[];
  error_message?: string;
  processing_seconds?: number;
}

export interface ArtifactMeta {
  artifact_type: string;
  storage_uri: string;
  sha256: string;
  bytes: number;
}

export interface LatestExports {
  run_id: string;
  status: string;
  artifacts: ArtifactMeta[];
}

export const getFirms = async () => {
  const response = await api.get<Firm[]>('/firms');
  return response.data;
};

export const createFirm = async (name: string) => {
  const response = await api.post<Firm>('/firms', { name });
  return response.data;
};

export const getFirmMatters = async (firmId: string) => {
  const response = await api.get<Matter[]>(`/firms/${firmId}/matters`);
  return response.data;
};

export const createMatter = async (firmId: string, title: string, clientRef?: string) => {
  const response = await api.post<Matter>(`/firms/${firmId}/matters`, { title, client_ref: clientRef });
  return response.data;
};

export const getMatter = async (matterId: string) => {
  const response = await api.get<Matter>(`/matters/${matterId}`);
  return response.data;
};

export const getMatterDocuments = async (matterId: string) => {
  const response = await api.get<Document[]>(`/matters/${matterId}/documents`);
  return response.data;
};

export const uploadDocument = async (matterId: string, file: File) => {
  const formData = new FormData();
  formData.append('file', file);
  const response = await api.post<Document>(`/matters/${matterId}/documents`, formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
  });
  return response.data;
};

export const getMatterRuns = async (matterId: string) => {
  const response = await api.get<Run[]>(`/matters/${matterId}/runs`);
  return response.data;
};

export const createRun = async (matterId: string, config: { max_pages?: number } = {}) => {
  const response = await api.post<Run>(`/matters/${matterId}/runs`, config);
  return response.data;
};

export const getRun = async (runId: string) => {
  const response = await api.get<Run>(`/runs/${runId}`);
  return response.data;
};

export const getArtifactUrl = (runId: string, type: string) => {
  return `${API_BASE_URL}/runs/${runId}/artifacts/${type}`;
};

export const getLatestExports = async (matterId: string) => {
  const response = await api.get<LatestExports>(`/matters/${matterId}/exports/latest`);
  return response.data;
};
