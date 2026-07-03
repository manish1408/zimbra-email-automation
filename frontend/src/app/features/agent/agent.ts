import { CommonModule } from '@angular/common';
import { Component, OnInit, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import {
  AgentTraining,
  ClassificationEmployee,
  ClassificationRules,
} from '../../core/models/email.models';
import { AgentService } from '../../core/services/agent.service';

const MAX_TEXT_LENGTH = 8000;

@Component({
  selector: 'app-agent',
  standalone: true,
  imports: [CommonModule, FormsModule],
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

  rules: ClassificationRules | null = null;
  savedRulesJson = '';
  rulesUpdatedAt: string | null = null;
  rulesLoading = false;
  rulesSaving = false;

  error = '';
  successMessage = '';

  ngOnInit(): void {
    this.loadTraining();
    this.loadRules();
  }

  get generalDirty(): boolean {
    return this.generalRules !== this.savedGeneralRules;
  }

  get draftDirty(): boolean {
    return this.draftReplyRules !== this.savedDraftReplyRules;
  }

  get rulesDirty(): boolean {
    return this.rules ? JSON.stringify(this.rules) !== this.savedRulesJson : false;
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

  loadRules(): void {
    this.rulesLoading = true;
    this.agentService.getClassificationRules().subscribe({
      next: (res) => this.applyRules(res),
      error: (err) => {
        this.error = err?.error?.detail ?? 'Failed to load classification rules';
        this.rulesLoading = false;
      },
    });
  }

  saveRules(): void {
    if (!this.rules || this.rules.categories.length === 0) {
      this.error = 'At least one category is required.';
      return;
    }

    const slugs = this.rules.categories.map((c) => c.slug.trim());
    if (new Set(slugs).size !== slugs.length) {
      this.error = 'Category slugs must be unique.';
      return;
    }

    this.rulesSaving = true;
    this.error = '';
    this.successMessage = '';
    this.agentService.saveClassificationRules(this.rules).subscribe({
      next: (res) => {
        this.applyRules(res);
        this.rulesSaving = false;
        this.successMessage = 'Classification rules saved.';
      },
      error: (err) => {
        this.error = err?.error?.detail ?? 'Failed to save classification rules';
        this.rulesSaving = false;
      },
    });
  }

  addCategory(): void {
    if (!this.rules) return;
    const nextOrder = (this.rules.categories.at(-1)?.sort_order ?? 0) + 10;
    this.rules.categories = [
      ...this.rules.categories,
      {
        slug: '',
        display_name: '',
        classification_hints: '',
        folder: '',
        forward_to: null,
        send_ack: true,
        needs_live_agent: false,
        is_spam: false,
        route_by_person: false,
        skip_forward: false,
        sort_order: nextOrder,
        enabled: true,
      },
    ];
  }

  removeCategory(index: number): void {
    if (!this.rules) return;
    this.rules.categories = this.rules.categories.filter((_, i) => i !== index);
  }

  addEmployee(): void {
    if (!this.rules) return;
    this.rules.employees = [
      ...this.rules.employees,
      { name: '', email: '', aliases: [] },
    ];
  }

  removeEmployee(index: number): void {
    if (!this.rules) return;
    this.rules.employees = this.rules.employees.filter((_, i) => i !== index);
  }

  aliasesText(employee: ClassificationEmployee): string {
    return (employee.aliases ?? []).join(', ');
  }

  setAliases(employee: ClassificationEmployee, value: string): void {
    employee.aliases = value
      .split(',')
      .map((part) => part.trim())
      .filter(Boolean);
  }

  private applyTraining(res: AgentTraining): void {
    this.generalRules = res.general_rules ?? '';
    this.savedGeneralRules = this.generalRules;
    this.draftReplyRules = res.draft_reply_rules ?? '';
    this.savedDraftReplyRules = this.draftReplyRules;
    this.trainingUpdatedAt = res.updated_at;
    this.trainingLoading = false;
  }

  private applyRules(res: ClassificationRules): void {
    this.rules = {
      ...res,
      config: { ...res.config },
      categories: res.categories.map((c) => ({ ...c })),
      employees: res.employees.map((e) => ({
        ...e,
        aliases: [...(e.aliases ?? [])],
      })),
    };
    this.savedRulesJson = JSON.stringify(this.rules);
    this.rulesUpdatedAt = res.updated_at;
    this.rulesLoading = false;
  }
}
