export interface StoreData {
  id: string;
  store_name: string;
  store_url: string;
  whatsapp_number: string;
  agent_notes: string;
  has_catalog: boolean;
  created_at: string;
}

export interface UserData {
  id: string;
  username: string;
  email: string;
  email_verified: boolean;
}

export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
}

export interface KnowledgeDoc {
  id: string;
  title: string | null;
  content: string;
  source: string | null;
  doc_type: string | null;
  created_at: string | null;
}

export interface AgentStatus {
  agent_type: string;
  model: string;
  tools: string[];
  tool_count: number;
  langgraph_available: boolean;
  anthropic_configured: boolean;
  tavily_configured: boolean;
  firecrawl_configured: boolean;
  shopify_configured: boolean;
  google_calendar_configured: boolean;
  evolution_configured: boolean;
  knowledge_bases: number;
}

export type ViewType = 'dashboard' | 'agent' | 'knowledge' | 'whatsapp' | 'chat' | 'settings';
