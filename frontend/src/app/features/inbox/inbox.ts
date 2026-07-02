import { CommonModule } from '@angular/common';
import { Component, OnInit, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { forkJoin, of } from 'rxjs';
import { catchError } from 'rxjs/operators';
import {
  Folder,
  MailSource,
  MessageAutomationResult,
  MessageDetail,
  MessageMetadata,
  MessageSummary,
  User,
} from '../../core/models/email.models';
import { LocalDataService } from '../../core/services/local-data.service';
import { MailboxService } from '../../core/services/mailbox.service';
import { SyncService } from '../../core/services/sync.service';
import { UsersService } from '../../core/services/users.service';
import { AutomationDrawerComponent } from './automation-drawer/automation-drawer';

interface FolderFilter {
  label: string;
  query: string;
}

@Component({
  selector: 'app-inbox',
  standalone: true,
  imports: [CommonModule, FormsModule, AutomationDrawerComponent],
  templateUrl: './inbox.html',
  styleUrl: './inbox.scss',
})
export class InboxComponent implements OnInit {
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly usersService = inject(UsersService);
  private readonly mailboxService = inject(MailboxService);
  private readonly localDataService = inject(LocalDataService);
  private readonly syncService = inject(SyncService);

  users: User[] = [];
  selectedEmail = '';
  userFilter = '';

  folders: Folder[] = [];
  activeQuery = 'is:anywhere';
  activeFolderLabel = 'All mail';
  searchQuery = '';

  messages: MessageSummary[] = [];
  selectedMessage: MessageDetail | null = null;
  selectedMetadata: MessageMetadata | null = null;
  relatedMessages: MessageSummary[] = [];
  metadataCache: Record<string, MessageMetadata> = {};

  automationOpen = false;
  automationMessage: MessageSummary | null = null;

  total = 0;
  limit = 50;
  offset = 0;
  hasMore = false;

  source: MailSource = 'live';
  loadingUsers = false;
  loadingMessages = false;
  loadingDetail = false;
  syncing = false;
  error = '';
  syncMessage = '';

  readonly folderFilters: FolderFilter[] = [
    { label: 'All mail', query: 'is:anywhere' },
    { label: 'Inbox', query: 'in:inbox' },
    { label: 'Sent', query: 'in:sent' },
    { label: 'Drafts', query: 'in:drafts' },
    { label: 'Trash', query: 'in:trash' },
  ];

  ngOnInit(): void {
    this.loadUsers();
    this.route.paramMap.subscribe((params) => {
      const email = params.get('userEmail');
      if (email) {
        this.selectedEmail = decodeURIComponent(email);
        this.resetList();
        this.loadMailboxData();
      } else {
        this.selectedEmail = '';
        this.messages = [];
        this.selectedMessage = null;
      }
    });
  }

  get filteredUsers(): User[] {
    const q = this.userFilter.trim().toLowerCase();
    if (!q) return this.users;
    return this.users.filter(
      (u) =>
        u.email.toLowerCase().includes(q) ||
        (u.display_name ?? '').toLowerCase().includes(q),
    );
  }

  get selectedUser(): User | undefined {
    return this.users.find((u) => u.email === this.selectedEmail);
  }

  loadUsers(): void {
    this.loadingUsers = true;
    this.usersService.listUsers().subscribe({
      next: (res) => {
        this.users = res.users;
        this.loadingUsers = false;
      },
      error: (err) => {
        this.error = err?.error?.detail ?? 'Failed to load users';
        this.loadingUsers = false;
      },
    });
  }

  onUserSelect(email: string): void {
    if (!email) {
      this.router.navigate(['/inbox']);
      return;
    }
    this.router.navigate(['/inbox', encodeURIComponent(email)]);
  }

  onSourceChange(source: MailSource): void {
    this.source = source;
    this.resetList();
    this.loadMessages();
  }

  selectFolder(filter: FolderFilter): void {
    this.activeQuery = filter.query;
    this.activeFolderLabel = filter.label;
    this.resetList();
    this.loadMessages();
  }

  selectZimbraFolder(folder: Folder): void {
    const name = (folder.path || folder.name).toLowerCase();
    this.activeQuery = `in:${name}`;
    this.activeFolderLabel = folder.name;
    this.resetList();
    this.loadMessages();
  }

  onSearch(): void {
    const q = this.searchQuery.trim();
    if (!q) return;
    this.activeQuery = q;
    this.activeFolderLabel = `Search: ${q}`;
    this.resetList();
    this.loadMessages();
  }

  loadMailboxData(): void {
    if (!this.selectedEmail) return;
    this.mailboxService.listFolders(this.selectedEmail).subscribe({
      next: (res) => (this.folders = res.folders),
      error: () => (this.folders = []),
    });
    this.loadMessages();
  }

  loadMessages(): void {
    if (!this.selectedEmail) return;
    this.loadingMessages = true;
    this.error = '';

    const onSuccess = (res: { messages: MessageSummary[]; total: number; has_more: boolean }) => {
      this.messages = res.messages;
      this.total = res.total;
      this.hasMore = res.has_more;
      this.loadingMessages = false;
      this.prefetchMetadata(res.messages);
      if (this.messages.length && !this.selectedMessage) {
        this.selectMessage(this.messages[0]);
      }
    };

    const onError = (err: { error?: { detail?: string } }) => {
      this.error = err?.error?.detail ?? 'Failed to load messages';
      this.loadingMessages = false;
    };

    if (this.source === 'live') {
      this.mailboxService
        .searchMessages(this.selectedEmail, this.activeQuery, this.limit, this.offset)
        .subscribe({ next: onSuccess, error: onError });
    } else {
      this.localDataService
        .listMessages(this.selectedEmail, this.limit, this.offset)
        .subscribe({ next: onSuccess, error: onError });
    }
  }

  selectMessage(message: MessageSummary): void {
    if (!this.selectedEmail) return;
    this.loadingDetail = true;
    this.selectedMetadata = null;

    const detail$ =
      this.source === 'live'
        ? this.mailboxService.getMessage(this.selectedEmail, message.id)
        : this.localDataService.getMessage(this.selectedEmail, message.id);

    const metadata$ = this.localDataService
      .getMetadata(this.selectedEmail, message.id)
      .pipe(catchError(() => of(null)));

    forkJoin({ detail: detail$, metadata: metadata$ }).subscribe({
      next: ({ detail, metadata }) => {
        this.selectedMessage = detail;
        this.selectedMetadata = metadata;
        if (metadata) {
          this.metadataCache[message.id] = metadata;
        }
        this.relatedMessages = this.findRelated(detail);
        this.loadingDetail = false;
      },
      error: (err) => {
        this.error = err?.error?.detail ?? 'Failed to load message';
        this.loadingDetail = false;
      },
    });
  }

  prevPage(): void {
    if (this.offset === 0) return;
    this.offset = Math.max(0, this.offset - this.limit);
    this.loadMessages();
  }

  nextPage(): void {
    if (!this.hasMore) return;
    this.offset += this.limit;
    this.loadMessages();
  }

  syncUser(): void {
    if (!this.selectedEmail) return;
    this.syncing = true;
    this.error = '';
    this.syncMessage = '';
    this.syncService.syncUser(this.selectedEmail).subscribe({
      next: (result) => {
        this.syncing = false;
        this.syncMessage = `Synced ${result.message_count} messages to local database.`;
        if (this.source === 'cached') {
          this.loadMessages();
        }
      },
      error: (err) => {
        this.error = err?.error?.detail ?? 'Sync failed';
        this.syncing = false;
      },
    });
  }

  categoryClass(category?: string | null): string {
    const map: Record<string, string> = {
      spam: 'bg-danger',
      marketing: 'bg-info text-dark',
      customer_support: 'bg-primary',
      billing: 'bg-warning text-dark',
      logistics: 'bg-secondary',
      careers: 'bg-success',
      orders: 'bg-dark',
      enquiry: 'bg-light text-dark border',
      general: 'bg-light text-dark border',
    };
    return map[category ?? ''] ?? 'bg-light text-dark border';
  }

  formatDate(value?: string | null): string {
    if (!value) return '—';
    const d = new Date(value);
    return Number.isNaN(d.getTime()) ? value : d.toLocaleString();
  }

  formatSize(bytes?: number | null): string {
    if (!bytes) return '—';
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  isHtmlBody(body?: string | null): boolean {
    if (!body) return false;
    const trimmed = body.trim();
    return /<\s*(html|body|div|table|p|span|center|!doctype)\b/i.test(trimmed);
  }

  getBodySrcdoc(body?: string | null): string {
    const content = body?.trim();
    if (!content) return '';

    if (/<\s*html[\s>]/i.test(content)) {
      return content;
    }

    return `<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <base target="_blank">
  <style>
    body {
      font-family: system-ui, -apple-system, sans-serif;
      font-size: 14px;
      line-height: 1.5;
      color: #1f2937;
      margin: 0;
      padding: 12px;
      word-wrap: break-word;
      overflow-wrap: anywhere;
    }
    img { max-width: 100%; height: auto; }
    table { max-width: 100%; }
    a { color: #2563eb; }
  </style>
</head>
<body>${content}</body>
</html>`;
  }

  plainBody(body?: string | null, fragment?: string | null): string {
    return body || fragment || '(no body)';
  }

  openAutomationDrawer(message: MessageSummary, event: Event): void {
    event.stopPropagation();
    this.automationMessage = message;
    this.automationOpen = true;
  }

  closeAutomationDrawer(): void {
    this.automationOpen = false;
    this.automationMessage = null;
  }

  onAutomationUpdated(result: MessageAutomationResult | null): void {
    if (!result || !this.automationMessage) return;
    const meta: MessageMetadata = {
      zimbra_id: result.message_id,
      account: result.account,
      category: (result.classification?.['category'] as string) ?? null,
      is_spam: Boolean(result.classification?.['is_spam']),
      folder_path: (result.actions?.['folder_path'] as string) ?? null,
      forwarded_to: (result.actions?.['forwarded_to'] as string) ?? null,
      ack_sent_at: result.actions?.['ack_sent'] ? new Date().toISOString() : null,
      draft_saved: Boolean(result.actions?.['draft_saved']),
      classification: result.classification ?? null,
      draft_reply_text: result.draft_reply_text ?? null,
      ack_body_text: result.ack_body_text ?? null,
      report: result.report ?? null,
      error: result.error ?? null,
      processed_at: result.processed_at ?? new Date().toISOString(),
      analyzed_at: result.processed_at ?? new Date().toISOString(),
    };
    this.metadataCache[result.message_id] = meta;
    if (this.selectedMessage?.id === result.message_id) {
      this.selectedMetadata = meta;
    }
  }

  rowMetadata(messageId: string): MessageMetadata | undefined {
    return this.metadataCache[messageId];
  }

  private prefetchMetadata(messages: MessageSummary[]): void {
    if (!this.selectedEmail) return;
    for (const msg of messages) {
      if (this.metadataCache[msg.id]) continue;
      this.localDataService
        .getMetadata(this.selectedEmail, msg.id)
        .pipe(catchError(() => of(null)))
        .subscribe((meta) => {
          if (meta) {
            this.metadataCache[msg.id] = meta;
          }
        });
    }
  }

  private resetList(): void {
    this.offset = 0;
    this.selectedMessage = null;
    this.selectedMetadata = null;
    this.relatedMessages = [];
    this.metadataCache = {};
  }

  private findRelated(message: MessageDetail): MessageSummary[] {
    const subject = this.normalizeSubject(message.subject);
    if (!subject) return [];
    return this.messages.filter(
      (m) => m.id !== message.id && this.normalizeSubject(m.subject) === subject,
    );
  }

  private normalizeSubject(subject?: string | null): string {
    return (subject ?? '')
      .replace(/^(re|fwd|fw):\s*/gi, '')
      .trim()
      .toLowerCase();
  }
}
