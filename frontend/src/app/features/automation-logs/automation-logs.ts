import { CommonModule, DOCUMENT } from '@angular/common';
import { Component, OnDestroy, OnInit, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { catchError, of } from 'rxjs';
import { formatMailDate } from '../../core/format-date';
import {
  AutomationLogEntry,
  MessageAutomationResult,
  User,
} from '../../core/models/email.models';
import { AutomationService } from '../../core/services/automation.service';
import { UsersService } from '../../core/services/users.service';

@Component({
  selector: 'app-automation-logs',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './automation-logs.html',
  styleUrl: './automation-logs.scss',
})
export class AutomationLogsComponent implements OnInit, OnDestroy {
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly usersService = inject(UsersService);
  private readonly automationService = inject(AutomationService);
  private readonly document = inject(DOCUMENT);

  users: User[] = [];
  selectedEmail = '';
  logs: AutomationLogEntry[] = [];
  selectedLog: AutomationLogEntry | null = null;
  detailResult: MessageAutomationResult | null = null;
  detailOpen = false;
  detailLoading = false;
  showRawJson = false;

  total = 0;
  limit = 50;
  offset = 0;
  hasMore = false;
  statusFilter = '';

  loading = false;
  loadingUsers = false;
  error = '';
  retryingId: number | null = null;

  ngOnInit(): void {
    this.loadUsers();
    this.route.paramMap.subscribe((params) => {
      const email = params.get('userEmail');
      if (email) {
        this.selectedEmail = decodeURIComponent(email);
        this.resetList();
        this.loadLogs();
      } else {
        this.selectedEmail = '';
        this.logs = [];
      }
    });
  }

  ngOnDestroy(): void {
    this.setBodyScrollLock(false);
  }

  private setBodyScrollLock(locked: boolean): void {
    this.document.body.classList.toggle('overflow-hidden', locked);
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
      this.router.navigate(['/automation-logs']);
      return;
    }
    this.router.navigate(['/automation-logs', encodeURIComponent(email)]);
  }

  onStatusFilterChange(): void {
    this.resetList();
    this.loadLogs();
  }

  resetList(): void {
    this.offset = 0;
    this.logs = [];
  }

  loadLogs(): void {
    if (!this.selectedEmail) return;
    this.loading = true;
    this.error = '';
    this.automationService
      .listLogs(this.selectedEmail, {
        limit: this.limit,
        offset: this.offset,
        status: this.statusFilter || undefined,
      })
      .subscribe({
        next: (res) => {
          this.logs = res.logs;
          this.total = res.total;
          this.hasMore = res.has_more;
          this.loading = false;
        },
        error: (err) => {
          this.error = err?.error?.detail ?? 'Failed to load automation logs';
          this.loading = false;
        },
      });
  }

  prevPage(): void {
    if (this.offset <= 0) return;
    this.offset = Math.max(0, this.offset - this.limit);
    this.loadLogs();
  }

  nextPage(): void {
    if (!this.hasMore) return;
    this.offset += this.limit;
    this.loadLogs();
  }

  openDetail(log: AutomationLogEntry, event?: Event): void {
    event?.stopPropagation();
    this.selectedLog = log;
    this.detailResult = null;
    this.detailOpen = true;
    this.detailLoading = true;
    this.showRawJson = false;
    this.setBodyScrollLock(true);

    if (!this.selectedEmail) {
      this.detailLoading = false;
      return;
    }

    this.automationService
      .getResult(this.selectedEmail, log.message_id)
      .pipe(catchError(() => of(null)))
      .subscribe({
        next: (res) => {
          this.detailResult = res;
          this.detailLoading = false;
        },
        error: () => {
          this.detailLoading = false;
        },
      });
  }

  closeDetail(): void {
    this.detailOpen = false;
    this.selectedLog = null;
    this.detailResult = null;
    this.detailLoading = false;
    this.setBodyScrollLock(false);
  }

  openInInbox(log: AutomationLogEntry, event?: Event): void {
    event?.stopPropagation();
    if (!this.selectedEmail) return;
    this.closeDetail();
    this.router.navigate(['/inbox', encodeURIComponent(this.selectedEmail)]);
  }

  retry(log: AutomationLogEntry, event?: Event): void {
    event?.stopPropagation();
    if (!this.selectedEmail || this.retryingId != null) return;
    this.retryingId = log.id;
    this.automationService.run(this.selectedEmail, log.message_id, true).subscribe({
      next: () => {
        this.retryingId = null;
        this.loadLogs();
        if (this.detailOpen && this.selectedLog?.id === log.id) {
          this.openDetail(log);
        }
      },
      error: (err) => {
        this.error = err?.error?.detail ?? 'Retry failed';
        this.retryingId = null;
      },
    });
  }

  formatDate(value?: string | null): string {
    return formatMailDate(value);
  }

  formatMs(ms?: number | null): string {
    if (ms == null) return '—';
    if (ms < 1000) return `${ms}ms`;
    return `${(ms / 1000).toFixed(1)}s`;
  }

  statusClass(status: string): string {
    switch (status) {
      case 'completed':
        return 'text-bg-success';
      case 'failed':
        return 'text-bg-danger';
      case 'skipped':
        return 'text-bg-secondary';
      default:
        return 'text-bg-light border text-dark';
    }
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

  confidencePercent(value: unknown): string {
    const n = typeof value === 'number' ? value : Number(value);
    if (Number.isNaN(n)) return '—';
    return `${Math.round(n * 100)}%`;
  }

  actionsSummary(log: AutomationLogEntry): string {
    const actions = log.actions;
    if (!actions) return '—';
    const parts: string[] = [];
    if (actions['folder_moved']) parts.push('moved');
    if (actions['forwarded_to']) parts.push('forwarded');
    if (actions['ack_sent']) parts.push('ack');
    if (actions['draft_saved']) parts.push('draft');
    return parts.length ? parts.join(', ') : actions['folder_path'] ? 'folder set' : '—';
  }

  traceSteps(log: AutomationLogEntry | null): Array<Record<string, unknown>> {
    if (!log) return [];
    const steps = log.automation_trace?.['steps'];
    return Array.isArray(steps) ? steps : [];
  }

  detailClassification(): Record<string, unknown> | null {
    return this.selectedLog?.classification ?? this.detailResult?.classification ?? null;
  }

  detailActions(): Record<string, unknown> | null {
    return this.selectedLog?.actions ?? this.detailResult?.actions ?? null;
  }

  detailDraftText(): string | null {
    return this.detailResult?.draft_reply_text ?? null;
  }

  detailAckText(): string | null {
    return this.detailResult?.ack_body_text ?? null;
  }

  stepError(step: Record<string, unknown>): string | null {
    const err = step['error'];
    return typeof err === 'string' && err ? err : null;
  }
}
