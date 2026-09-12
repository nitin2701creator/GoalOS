/**
 * API client for the GoalOS Integrations Manager backend.
 * Never stores secrets in localStorage — uses session-only tokens.
 */

const API_BASE = '/api';

let authToken: string | null = null;
let csrfToken: string | null = null;

export function setAuth(token: string, csrf: string) {
  authToken = token;
  csrfToken = csrf;
}

async function fetchFreshCSRFToken(): Promise<string> {
  const res = await request<{ csrf_token: string }>('/auth/csrf');
  return res.csrf_token;
}

export function clearAuth() {
  authToken = null;
  csrfToken = null;
}

export function isAuthenticated(): boolean {
  return authToken !== null;
}

async function request<T = any>(path: string, options: RequestInit = {}): Promise<T> {
  const method = (options.method || 'GET').toUpperCase();
  const isStateChanging = ['POST', 'PUT', 'DELETE'].includes(method);
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string> || {}),
  };

  if (authToken) {
    headers['Authorization'] = `Bearer ${authToken}`;
  }

  // Only include CSRF token for state-changing requests
  if (isStateChanging && csrfToken) {
    headers['X-CSRF-Token'] = csrfToken;
  }

  let attempt = 0;
  let lastError = null;

  while (attempt < 2) {
    const res = await fetch(`${API_BASE}${path}`, {
      ...options,
      headers,
    });

    if (res.status === 401) {
      clearAuth();
      window.location.reload();
      throw new Error('Unauthorized');
    }

    if (!res.ok) {
      const body = await res.json().catch(() => ({ detail: res.statusText }));
      lastError = new Error(body.detail || 'Request failed');

      // Handle CSRF 403 error with retry logic
      if (res.status === 403 && body.detail === 'Invalid or missing CSRF token') {
        if (attempt === 0) {
          // Fetch a fresh CSRF token and retry
          const freshToken = await fetchFreshCSRFToken();
          csrfToken = freshToken;
          attempt++;
          continue;
        } else {
          // Second attempt failed, throw the error
          throw lastError;
        }
      } else {
        throw lastError;
      }
    }

    return res.json();
  }

  throw new Error('Unexpected error');
}

// ── Auth ──────────────────────────────────────────────────────────────

export async function login(username: string, password: string) {
  const res = await request<{ access_token: string; csrf_token: string }>(
    '/auth/login',
    {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    },
  );
  setAuth(res.access_token, res.csrf_token);
  return res;
}

// ── Integrations ──────────────────────────────────────────────────────

export interface IntegrationSummary {
  id: number;
  slug: string;
  name: string;
  description: string;
  icon: string;
  auth_type: string;
  status: string;
  last_connected_at: string | null;
  error_message: string | null;
}

export interface IntegrationDetail extends IntegrationSummary {
  credential_fields: Array<{ key: string; label: string; type: string; required: boolean }>;
  has_credentials: boolean;
  has_oauth: boolean;
}

export interface MaskedCredential {
  key: string;
  label: string;
  masked_value: string;
  is_set: boolean;
}

export function listIntegrations(): Promise<IntegrationSummary[]> {
  return request('/integrations');
}

export function getIntegration(slug: string): Promise<IntegrationDetail> {
  return request(`/integrations/${slug}`);
}

export function getMaskedCredentials(slug: string): Promise<MaskedCredential[]> {
  return request(`/integrations/${slug}/credentials`);
}

export function saveCredentials(slug: string, credentials: Record<string, string>) {
  return request(`/integrations/${slug}/credentials`, {
    method: 'POST',
    body: JSON.stringify({ credentials }),
  });
}

export function testConnection(slug: string) {
  return request(`/integrations/${slug}/test`, { method: 'POST' });
}

export function connectIntegration(slug: string) {
  return request<{ success: boolean; message: string; redirect_url?: string }>(
    `/integrations/${slug}/connect`,
    { method: 'POST' },
  );
}

export function disconnectIntegration(slug: string) {
  return request(`/integrations/${slug}/disconnect`, { method: 'POST' });
}

export function getIntegrationStatus(slug: string) {
  return request(`/integrations/${slug}/status`);
}
