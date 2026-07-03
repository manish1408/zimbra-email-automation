import { CommonModule } from '@angular/common';
import { Component, OnInit, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { AgentTraining } from '../../core/models/email.models';
import { AgentService } from '../../core/services/agent.service';

const MAX_TRAINING_LENGTH = 8000;

@Component({
  selector: 'app-agent',
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <div class="container py-4">
      <h1 class="h3 mb-2">Agent Training</h1>
      <p class="text-muted mb-4">
        Global instructions for all mailboxes — affects classification, thread summaries, and draft replies.
      </p>

      <div class="card shadow-sm">
        <div class="card-body">
          <label class="form-label" for="trainingContent">Training text</label>
          <textarea
            id="trainingContent"
            class="form-control font-monospace"
            rows="14"
            style="min-height: 320px"
            [(ngModel)]="content"
            [disabled]="loading || saving"
            placeholder="Example: Always treat emails from vendor@example.com as logistics. Use a formal tone for billing inquiries."
          ></textarea>
          <div class="d-flex flex-wrap align-items-center gap-3 mt-3">
            <button
              class="btn btn-primary"
              [disabled]="loading || saving || !dirty"
              (click)="save()"
            >
              {{ saving ? 'Saving…' : 'Save Training' }}
            </button>
            <span class="small text-muted">{{ content.length }} / {{ maxLength }}</span>
            @if (updatedAt) {
              <span class="small text-muted">Last saved {{ updatedAt | date: 'medium' }}</span>
            }
          </div>
          @if (loading) {
            <div class="mt-3 text-muted small">Loading training…</div>
          }
          @if (error) {
            <div class="alert alert-danger mt-3 mb-0">{{ error }}</div>
          }
          @if (successMessage) {
            <div class="alert alert-success mt-3 mb-0">{{ successMessage }}</div>
          }
        </div>
      </div>
    </div>
  `,
})
export class AgentComponent implements OnInit {
  private readonly agentService = inject(AgentService);

  readonly maxLength = MAX_TRAINING_LENGTH;

  content = '';
  savedContent = '';
  updatedAt: string | null = null;
  loading = false;
  saving = false;
  error = '';
  successMessage = '';

  get dirty(): boolean {
    return this.content !== this.savedContent;
  }

  ngOnInit(): void {
    this.load();
  }

  load(): void {
    this.loading = true;
    this.error = '';
    this.agentService.getTraining().subscribe({
      next: (res) => this.applyTraining(res),
      error: (err) => {
        this.error = err?.error?.detail ?? 'Failed to load training';
        this.loading = false;
      },
    });
  }

  save(): void {
    if (this.content.length > this.maxLength) {
      this.error = `Training text must be at most ${this.maxLength} characters.`;
      return;
    }

    this.saving = true;
    this.error = '';
    this.successMessage = '';
    this.agentService.saveTraining(this.content).subscribe({
      next: (res) => {
        this.applyTraining(res);
        this.saving = false;
        this.successMessage = 'Training saved.';
      },
      error: (err) => {
        this.error = err?.error?.detail ?? 'Failed to save training';
        this.saving = false;
      },
    });
  }

  private applyTraining(res: AgentTraining): void {
    this.content = res.content ?? '';
    this.savedContent = this.content;
    this.updatedAt = res.updated_at;
    this.loading = false;
  }
}
