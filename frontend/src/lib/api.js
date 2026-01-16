/**
 * API Client for SyncApply Backend
 * =================================
 * 
 * Handles all API calls to the FastAPI backend
 */

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';

/**
 * Make an authenticated API request
 */
async function apiRequest(endpoint, options = {}, token = null) {
  const headers = {
    'Content-Type': 'application/json',
    ...options.headers,
  };
  
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  
  const response = await fetch(`${API_BASE}${endpoint}`, {
    ...options,
    headers,
  });
  
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Unknown error' }));
    throw new Error(error.detail || 'API request failed');
  }
  
  return response.json();
}

/**
 * Fetch emails from Gmail
 */
export async function fetchEmails(token, query = 'in:inbox', maxResults = 10) {
  const params = new URLSearchParams({ query, max_results: maxResults });
  return apiRequest(`/api/emails?${params}`, {}, token);
}

/**
 * Fetch a single email by ID
 */
export async function fetchEmail(token, emailId) {
  return apiRequest(`/api/emails/${emailId}`, {}, token);
}

/**
 * Save an email as a job application
 */
export async function saveApplication(token, emailId) {
  return apiRequest(`/api/applications/save/${emailId}`, { method: 'POST' }, token);
}

/**
 * Get all saved applications (no auth needed for viewing)
 */
export async function getApplications() {
  return apiRequest('/api/applications');
}

/**
 * Process and save the latest email
 */
export async function processLatestEmail(token, query = 'in:inbox') {
  const params = new URLSearchParams({ query });
  return apiRequest(`/api/applications/process-latest?${params}`, { method: 'POST' }, token);
}

/**
 * Health check
 */
export async function healthCheck() {
  return apiRequest('/');
}
