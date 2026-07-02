export interface User {
  id: string;
  email: string;
  display_name?: string | null;
  status?: string | null;
}

export interface UserListResponse {
  total: number;
  users: User[];
}

export interface MessageSummary {
  id: string;
  account: string;
  subject?: string | null;
  from?: string | null;
  to?: string[];
  date?: string | null;
  fragment?: string | null;
  folder?: string | null;
  size?: number | null;
  is_read?: boolean | null;
}

export interface MessageDetail extends MessageSummary {
  body?: string | null;
}

export interface InboxResponse {
  user: User;
  query: string;
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
  messages: MessageSummary[];
}

export interface MessageSearchResponse extends InboxResponse {}

export interface Folder {
  id: string;
  name: string;
  path?: string | null;
  unread_count?: number | null;
  message_count?: number | null;
}

export interface FolderListResponse {
  user: User;
  folders: Folder[];
}

export interface HealthResponse {
  status: string;
  zimbra_host: string;
  zimbra_connected: boolean;
}

export interface ConnectionTestResponse {
  connected: boolean;
  zimbra_host: string;
  admin_user: string;
  account_count: number;
  message: string;
}

export interface AccountMessages {
  user: User;
  message_count: number;
  messages: MessageSummary[];
}

export interface SyncResult {
  accounts_processed: number;
  total_messages: number;
  accounts: AccountMessages[];
}

export interface AgentRunRequest {
  user_email: string;
  limit?: number;
  instruction?: string;
  session_id?: string;
}

export interface AgentRunResult {
  thread_id: string;
  user_email: string;
  dominant_intent?: string | null;
  dominant_category?: string | null;
  message_count: number;
  classifications: Record<string, unknown>[];
  compliance_flags: string[];
  summary?: string | null;
  draft_reply?: string | null;
  report: Record<string, unknown>;
}

export interface MessageMetadata {
  zimbra_id: string;
  account: string;
  category?: string | null;
  is_spam: boolean;
  folder_path?: string | null;
  forwarded_to?: string | null;
  ack_sent_at?: string | null;
  draft_saved: boolean;
  classification?: Record<string, unknown> | null;
  draft_reply_text?: string | null;
  ack_body_text?: string | null;
  report?: Record<string, unknown> | null;
  error?: string | null;
  processed_at?: string | null;
  analyzed_at?: string | null;
}

export interface MessageAutomationRunRequest {
  force?: boolean;
}

export interface MessageAutomationRunSummary {
  id: number;
  thread_id: string;
  status: string;
  dry_run: boolean;
  classification?: Record<string, unknown> | null;
  actions?: Record<string, unknown> | null;
  draft_reply_text?: string | null;
  ack_body_text?: string | null;
  error?: string | null;
  created_at?: string | null;
}

export interface MessageAutomationResult {
  account: string;
  message_id: string;
  thread_id: string;
  status: string;
  dry_run: boolean;
  classification?: Record<string, unknown> | null;
  actions?: Record<string, unknown> | null;
  draft_reply_text?: string | null;
  ack_body_text?: string | null;
  report: Record<string, unknown>;
  error?: string | null;
  processed_at?: string | null;
  runs?: MessageAutomationRunSummary[];
}

export interface MessageAutomationRunListResponse {
  account: string;
  message_id: string;
  runs: MessageAutomationRunSummary[];
}

export interface LocalMailboxStats {
  account: string;
  total: number;
  unanalyzed: number;
  last_seen_date?: string | null;
  last_poll_at?: string | null;
  last_poll_new_count: number;
}

export interface LocalMessageListResponse {
  account: string;
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
  messages: MessageSummary[];
}

export type MailSource = 'live' | 'cached';
