import { CommonModule } from '@angular/common';
import { Component, OnInit, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute } from '@angular/router';
import { AgentRunResult } from '../../core/models/email.models';
import { AgentService } from '../../core/services/agent.service';
import { UsersService } from '../../core/services/users.service';

@Component({
  selector: 'app-agent',
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <div class="container py-4">
      <h1 class="h3 mb-4">Agent Analysis</h1>
      <div class="card shadow-sm">
        <div class="card-body">
          <div class="mb-3">
            <label class="form-label">Mailbox</label>
            <select class="form-select" [(ngModel)]="userEmail">
              <option value="">Select user…</option>
              @for (u of users; track u.email) {
                <option [value]="u.email">{{ u.email }}</option>
              }
            </select>
          </div>
          <div class="mb-3">
            <label class="form-label">Instruction (optional)</label>
            <textarea class="form-control" rows="3" [(ngModel)]="instruction"></textarea>
          </div>
          <button class="btn btn-primary" [disabled]="!userEmail || running" (click)="run()">
            {{ running ? 'Running…' : 'Run Agent' }}
          </button>
          @if (error) {
            <div class="alert alert-danger mt-3">{{ error }}</div>
          }
          @if (result) {
            <div class="mt-4">
              <h2 class="h5">Result</h2>
              <p><strong>Thread:</strong> {{ result.thread_id }}</p>
              <p><strong>Messages:</strong> {{ result.message_count }}</p>
              @if (result.summary) {
                <p>{{ result.summary }}</p>
              }
              @if (result.draft_reply) {
                <h3 class="h6">Draft Reply</h3>
                <pre class="bg-light p-3 rounded">{{ result.draft_reply }}</pre>
              }
              <h3 class="h6 mt-3">Classifications</h3>
              <pre class="bg-light p-3 rounded small">{{ result.classifications | json }}</pre>
            </div>
          }
        </div>
      </div>
    </div>
  `,
})
export class AgentComponent implements OnInit {
  private readonly route = inject(ActivatedRoute);
  private readonly usersService = inject(UsersService);
  private readonly agentService = inject(AgentService);

  users: { email: string }[] = [];
  userEmail = '';
  instruction = '';
  running = false;
  error = '';
  result: AgentRunResult | null = null;

  ngOnInit(): void {
    this.usersService.listUsers().subscribe((res) => (this.users = res.users));
    this.route.paramMap.subscribe((params) => {
      const email = params.get('userEmail');
      if (email) this.userEmail = decodeURIComponent(email);
    });
  }

  run(): void {
    this.running = true;
    this.error = '';
    this.result = null;
    this.agentService
      .run({
        user_email: this.userEmail,
        instruction: this.instruction || undefined,
      })
      .subscribe({
        next: (res) => {
          this.result = res;
          this.running = false;
        },
        error: (err) => {
          this.error = err?.error?.detail ?? 'Agent run failed';
          this.running = false;
        },
      });
  }
}
