import { CommonModule } from '@angular/common';
import { Component, OnInit, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { AgentTraining } from '../../core/models/email.models';
import { AgentService } from '../../core/services/agent.service';

const MAX_TEXT_LENGTH = 8000;

@Component({
  selector: 'app-agent',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink],
  templateUrl: './agent.html',
  styleUrl: './agent.scss',
})
export class AgentComponent implements OnInit {
  private readonly agentService = inject(AgentService);

  readonly maxLength = MAX_TEXT_LENGTH;

  generalRules = '';
  savedGeneralRules = '';
  draftReplyRules = '';
  savedDraftReplyRules = '';
  trainingUpdatedAt: string | null = null;
  trainingLoading = false;
  generalSaving = false;
  draftSaving = false;

  error = '';
  successMessage = '';

  ngOnInit(): void {
    this.loadTraining();
  }

  get generalDirty(): boolean {
    return this.generalRules !== this.savedGeneralRules;
  }

  get draftDirty(): boolean {
    return this.draftReplyRules !== this.savedDraftReplyRules;
  }

  loadTraining(): void {
    this.trainingLoading = true;
    this.agentService.getTraining().subscribe({
      next: (res) => this.applyTraining(res),
      error: (err) => {
        this.error = err?.error?.detail ?? 'Failed to load training rules';
        this.trainingLoading = false;
      },
    });
  }

  saveGeneralRules(): void {
    if (this.generalRules.length > this.maxLength) {
      this.error = `General rules must be at most ${this.maxLength} characters.`;
      return;
    }

    this.generalSaving = true;
    this.error = '';
    this.successMessage = '';
    this.agentService.saveGeneralRules(this.generalRules).subscribe({
      next: (res) => {
        this.applyTraining(res);
        this.generalSaving = false;
        this.successMessage = 'General rules saved.';
      },
      error: (err) => {
        this.error = err?.error?.detail ?? 'Failed to save general rules';
        this.generalSaving = false;
      },
    });
  }

  saveDraftReplyRules(): void {
    if (this.draftReplyRules.length > this.maxLength) {
      this.error = `Draft reply rules must be at most ${this.maxLength} characters.`;
      return;
    }

    this.draftSaving = true;
    this.error = '';
    this.successMessage = '';
    this.agentService.saveDraftReplyRules(this.draftReplyRules).subscribe({
      next: (res) => {
        this.applyTraining(res);
        this.draftSaving = false;
        this.successMessage = 'Draft reply rules saved.';
      },
      error: (err) => {
        this.error = err?.error?.detail ?? 'Failed to save draft reply rules';
        this.draftSaving = false;
      },
    });
  }

  private applyTraining(res: AgentTraining): void {
    this.generalRules = res.general_rules ?? '';
    this.savedGeneralRules = this.generalRules;
    this.draftReplyRules = res.draft_reply_rules ?? '';
    this.savedDraftReplyRules = this.draftReplyRules;
    this.trainingUpdatedAt = res.updated_at;
    this.trainingLoading = false;
  }
}