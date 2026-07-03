import { CommonModule, DOCUMENT } from '@angular/common';
import {
  Component,
  EventEmitter,
  Input,
  OnChanges,
  OnDestroy,
  Output,
  SimpleChanges,
  inject,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { catchError, of } from 'rxjs';
import { MessageAutomationResult, MessageSummary, ThreadSummary } from '../../../core/models/email.models';
import { formatMailDate } from '../../../core/format-date';
import { AutomationService } from '../../../core/services/automation.service';
import { LocalDataService } from '../../../core/services/local-data.service';

@Component({
  selector: 'app-automation-drawer',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './automation-drawer.html',
  styleUrl: './automation-drawer.scss',
})
export class AutomationDrawerComponent implements OnChanges, OnDestroy {
  private readonly automationService = inject(AutomationService);
  private readonly localDataService = inject(LocalDataService);
  private readonly document = inject(DOCUMENT);

  @Input() account = '';
  @Input() message: MessageSummary | null = null;
  @Input() open = false;
  @Output() closed = new EventEmitter<void>();
  @Output() resultUpdated = new EventEmitter<MessageAutomationResult | null>();

  result: MessageAutomationResult | null = null;
  threadSummary: ThreadSummary | null = null;
  loading = false;
  running = false;
  loadError = '';
  forceRerun = false;
  showHistory = false;

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['open']) {
      this.setBodyScrollLock(this.open);
    }
    if ((changes['open'] || changes['message']) && this.open && this.message && this.account) {
      this.loadExistingResults();
    }
    if (changes['open'] && !this.open) {
      this.result = null;
      this.threadSummary = null;
      this.loadError = '';
      this.showHistory = false;
    }
  }

  ngOnDestroy(): void {
    this.setBodyScrollLock(false);
  }

  private setBodyScrollLock(locked: boolean): void {
    this.document.body.classList.toggle('overflow-hidden', locked);
  }

  onBackdropClick(): void {
    this.close();
  }

  close(): void {
    this.closed.emit();
  }

  runAutomation(): void {
    if (!this.account || !this.message || this.running) return;
    this.running = true;
    this.loadError = '';
    this.automationService.run(this.account, this.message.id, this.forceRerun).subscribe({
      next: (res) => {
        this.result = res;
        this.running = false;
        this.applyThreadSummaryFromResult(res);
        this.resultUpdated.emit(res);
        this.refreshRuns();
      },
      error: (err) => {
        this.loadError = err?.error?.detail ?? 'Automation run failed';
        this.running = false;
      },
    });
  }

  /** Load cached automation data only — never triggers a pipeline run. */
  loadExistingResults(): void {
    if (!this.account || !this.message) return;
    this.loading = true;
    this.loadError = '';
    this.threadSummary = null;
    this.automationService
      .getResult(this.account, this.message.id)
      .pipe(catchError(() => of(null)))
      .subscribe({
        next: (res) => {
          this.result = res;
          this.loading = false;
          this.applyThreadSummaryFromResult(res);
          if (!this.threadSummary) {
            this.loadCachedThreadSummary();
          }
        },
        error: () => {
          this.loading = false;
        },
      });
  }

  private loadCachedThreadSummary(): void {
    if (!this.account || !this.message || this.threadSummary) return;
    this.localDataService
      .getMetadata(this.account, this.message.id)
      .pipe(catchError(() => of(null)))
      .subscribe((meta) => {
        if (!meta?.thread_summary || typeof meta.thread_summary !== 'object') return;
        const summary = meta.thread_summary as Record<string, unknown>;
        this.threadSummary = {
          account: meta.account,
          message_id: meta.zimbra_id,
          history_points: Array.isArray(summary['history_points'])
            ? (summary['history_points'] as string[])
            : [],
          current_points: Array.isArray(summary['current_points'])
            ? (summary['current_points'] as string[])
            : [],
          focus: typeof summary['focus'] === 'string' ? summary['focus'] : '',
        };
      });
  }

  private applyThreadSummaryFromResult(result: MessageAutomationResult | null): void {
    const summary = result?.thread_summary;
    if (!summary || typeof summary !== 'object') return;
    this.threadSummary = {
      account: result?.account ?? this.account,
      message_id: result?.message_id ?? this.message?.id ?? '',
      history_points: Array.isArray(summary['history_points'])
        ? (summary['history_points'] as string[])
        : [],
      current_points: Array.isArray(summary['current_points'])
        ? (summary['current_points'] as string[])
        : [],
      focus: typeof summary['focus'] === 'string' ? summary['focus'] : '',
    };
  }

  refreshRuns(): void {
    if (!this.account || !this.message) return;
    this.automationService.listRuns(this.account, this.message.id).subscribe({
      next: (res) => {
        if (this.result) {
          this.result = { ...this.result, runs: res.runs };
        }
      },
    });
  }

  draftReplyText(): string | null {
    if (this.result?.draft_reply_text) {
      return this.result.draft_reply_text;
    }
    const runWithDraft = this.result?.runs?.find((run) => run.draft_reply_text);
    return runWithDraft?.draft_reply_text ?? null;
  }

  ackBodyText(): string | null {
    if (this.result?.ack_body_text) {
      return this.result.ack_body_text;
    }
    const runWithAck = this.result?.runs?.find((run) => run.ack_body_text);
    return runWithAck?.ack_body_text ?? null;
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
    return formatMailDate(value);
  }

  confidencePercent(value: unknown): string {
    const n = typeof value === 'number' ? value : Number(value);
    if (Number.isNaN(n)) return '—';
    return `${Math.round(n * 100)}%`;
  }

  statusClass(status: string): string {
    const map: Record<string, string> = {
      completed: 'text-bg-success',
      failed: 'text-bg-danger',
      skipped: 'text-bg-secondary',
    };
    return map[status] ?? 'text-bg-light border text-dark';
  }
}
