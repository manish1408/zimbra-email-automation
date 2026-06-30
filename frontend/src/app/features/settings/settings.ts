import { CommonModule } from '@angular/common';
import { Component, OnInit, inject } from '@angular/core';
import { ConnectionTestResponse, HealthResponse, LocalMailboxStats } from '../../core/models/email.models';
import { LocalDataService } from '../../core/services/local-data.service';
import { SystemService } from '../../core/services/system.service';
import { SyncService } from '../../core/services/sync.service';
import { UsersService } from '../../core/services/users.service';

@Component({
  selector: 'app-settings',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div class="container py-4">
      <h1 class="h3 mb-4">Settings &amp; Connection</h1>

      <div class="row g-4">
        <div class="col-md-6">
          <div class="card shadow-sm h-100">
            <div class="card-body">
              <h2 class="h5">System Health</h2>
              @if (health) {
                <p>
                  Status:
                  <span class="badge" [class.text-bg-success]="health.zimbra_connected" [class.text-bg-danger]="!health.zimbra_connected">
                    {{ health.status }}
                  </span>
                </p>
                <p class="mb-0 small text-muted">Host: {{ health.zimbra_host }}</p>
              } @else {
                <div class="spinner-border spinner-border-sm"></div>
              }
              <button class="btn btn-sm btn-outline-primary mt-3" (click)="testConnection()">Test Connection</button>
              @if (connectionTest) {
                <pre class="bg-light p-2 rounded small mt-2">{{ connectionTest | json }}</pre>
              }
            </div>
          </div>
        </div>

        <div class="col-md-6">
          <div class="card shadow-sm h-100">
            <div class="card-body">
              <h2 class="h5">Bulk Sync</h2>
              <p class="text-muted small">Sync all mailboxes to local PostgreSQL.</p>
              <button class="btn btn-primary btn-sm" [disabled]="syncing" (click)="syncAll()">
                {{ syncing ? 'Syncing…' : 'Sync All Users' }}
              </button>
              @if (syncMessage) {
                <p class="mt-2 small">{{ syncMessage }}</p>
              }
            </div>
          </div>
        </div>

        @if (stats) {
          <div class="col-12">
            <div class="card shadow-sm">
              <div class="card-body">
                <h2 class="h5">Local DB Stats — {{ stats.account }}</h2>
                <div class="row">
                  <div class="col-auto"><strong>Total:</strong> {{ stats.total }}</div>
                  <div class="col-auto"><strong>Unanalyzed:</strong> {{ stats.unanalyzed }}</div>
                  <div class="col-auto"><strong>Last poll:</strong> {{ stats.last_poll_at || '—' }}</div>
                </div>
              </div>
            </div>
          </div>
        }
      </div>
    </div>
  `,
})
export class SettingsComponent implements OnInit {
  private readonly systemService = inject(SystemService);
  private readonly syncService = inject(SyncService);
  private readonly localDataService = inject(LocalDataService);
  private readonly usersService = inject(UsersService);

  health: HealthResponse | null = null;
  connectionTest: ConnectionTestResponse | null = null;
  stats: LocalMailboxStats | null = null;
  syncing = false;
  syncMessage = '';

  ngOnInit(): void {
    this.systemService.health().subscribe((h) => (this.health = h));
    this.usersService.listUsers().subscribe((res) => {
      if (res.users[0]) {
        this.localDataService.getStats(res.users[0].email).subscribe({
          next: (s) => (this.stats = s),
          error: () => (this.stats = null),
        });
      }
    });
  }

  testConnection(): void {
    this.systemService.testConnection().subscribe((r) => (this.connectionTest = r));
  }

  syncAll(): void {
    this.syncing = true;
    this.syncService.syncAll().subscribe({
      next: (r) => {
        this.syncMessage = `Synced ${r.accounts_processed} accounts, ${r.total_messages} messages.`;
        this.syncing = false;
      },
      error: (err) => {
        this.syncMessage = err?.error?.detail ?? 'Sync failed';
        this.syncing = false;
      },
    });
  }
}
