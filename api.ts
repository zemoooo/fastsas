import type { StoreData, UserData, AgentStatus, KnowledgeDoc } from './types';

const API_BASE = import.meta.env.VITE_API_URL || '';

async function apiFetch(path: string, options?: RequestInit): Promise<any> {
  const res = await fetch(`${API_BASE}${path}`, {
    credentials: 'include',
    ...options,
    headers: {
      ...options?.headers,
    },
  });

  if (!res.ok) {
    let detail = 'حدث خطأ غير متوقع';
    try {
      const data = await res.json();
      detail = data.detail || data.message || detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }

  return res.json();
}

export async function registerStore(
  storeName: string,
  username: string,
  email: string,
  password: string
): Promise<any> {
  const form = new FormData();
  form.append('store_name', storeName);
  form.append('username', username);
  form.append('email', email);
  form.append('password', password);
  return apiFetch('/api/register-store', { method: 'POST', body: form });
}

export async function verifyEmail(email: string, code: string): Promise<any> {
  const form = new FormData();
  form.append('email', email);
  form.append('code', code);
  return apiFetch('/api/verify-email', { method: 'POST', body: form });
}

export async function resendVerification(email: string): Promise<any> {
  const form = new FormData();
  form.append('email', email);
  return apiFetch('/api/resend-verification', { method: 'POST', body: form });
}

export async function login(username: string, password: string): Promise<any> {
  const form = new FormData();
  form.append('username', username);
  form.append('password', password);
  return apiFetch('/api/login', { method: 'POST', body: form });
}

export async function logout(): Promise<void> {
  await apiFetch('/api/logout', { method: 'POST' });
}

export async function getMe(): Promise<{ user: UserData; store: StoreData }> {
  return apiFetch('/api/me');
}

export async function updateAgent(
  storeId: string,
  storeUrl: string,
  whatsappNumber: string,
  agentNotes: string,
  pdfFile?: File | null
): Promise<any> {
  const form = new FormData();
  form.append('store_id', storeId);
  form.append('store_url', storeUrl);
  form.append('whatsapp_number', whatsappNumber);
  form.append('agent_notes', agentNotes);
  if (pdfFile) {
    form.append('pdf_file', pdfFile);
  }
  return apiFetch('/api/update-agent', { method: 'POST', body: form });
}

export async function getWhatsappQR(storeId: string): Promise<any> {
  return apiFetch(`/api/whatsapp/qr/${storeId}`);
}

export async function getWhatsappStatus(storeId: string): Promise<any> {
  return apiFetch(`/api/whatsapp/status/${storeId}`);
}

export async function sendChat(storeId: string, message: string, senderId?: string): Promise<any> {
  return apiFetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ store_id: storeId, message, sender_id: senderId || 'preview_user' }),
  });
}

export async function getAgentStatus(): Promise<AgentStatus> {
  return apiFetch('/api/agent/status');
}

export async function getAgentTools(): Promise<any> {
  return apiFetch('/api/agent/tools');
}

export async function listKnowledge(): Promise<{ documents: KnowledgeDoc[]; count: number }> {
  return apiFetch('/api/knowledge/list');
}

export async function addKnowledge(title: string, content: string, source?: string, docType?: string): Promise<any> {
  const form = new FormData();
  form.append('title', title);
  form.append('content', content);
  form.append('source', source || 'manual');
  form.append('doc_type', docType || 'text');
  return apiFetch('/api/knowledge/add', { method: 'POST', body: form });
}

export async function deleteKnowledge(docId: string): Promise<any> {
  return apiFetch(`/api/knowledge/${docId}`, { method: 'DELETE' });
}

export async function scrapeUrl(url: string, title?: string): Promise<any> {
  const form = new FormData();
  form.append('url', url);
  form.append('title', title || '');
  return apiFetch('/api/knowledge/scrape', { method: 'POST', body: form });
}

export async function searchKnowledge(query: string): Promise<any> {
  const form = new FormData();
  form.append('query', query);
  return apiFetch('/api/knowledge/search', { method: 'POST', body: form });
}
