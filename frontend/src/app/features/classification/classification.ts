import { CommonModule } from '@angular/common';
import { Component, OnInit, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import {
  ClassificationCategory,
  ClassificationEmployee,
  ClassificationRules,
  MailboxClassificationRules,
  User,
} from '../../core/models/email.models';
import { ClassificationService } from '../../core/services/classification.service';
import { UsersService } from '../../core/services/users.service';
import { MailboxSelectComponent } from '../../shared/mailbox-select/mailbox-select';

@Component({
  selector: 'app-classification',
  standalone: true,
  imports: [CommonModule, FormsModule, MailboxSelectComponent],
  templateUrl: './classification.html',
  styleUrl: './classification.scss',
})
export class ClassificationComponent implements OnInit {
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly usersService = inject(UsersService);
  private readonly classificationService = inject(ClassificationService);

  readonly globalValue = '__global__';

  users: User[] = [];
  selectedEmail = this.globalValue;
  loadingUsers = false;

  globalRules: ClassificationRules | null = null;
  savedGlobalJson = '';
  mailboxRules: MailboxClassificationRules | null = null;
  savedMailboxJson = '';

  loading = false;
  saving = false;
  seeding = false;
  error = '';
  successMessage = '';
  updatedAt: string | null = null;

  ngOnInit(): void {
    this.loadUsers();
    this.route.paramMap.subscribe((params) => {
      const email = params.get('userEmail');
      this.selectedEmail = email ? decodeURIComponent(email) : this.globalValue;
      this.loadRules();
    });
  }

  get isGlobal(): boolean {
    return this.selectedEmail === this.globalValue;
  }

  get dirty(): boolean {
    if (this.isGlobal) {
      return this.globalRules
        ? JSON.stringify(this.globalRules) !== this.savedGlobalJson
        : false;
    }
    return this.mailboxRules
      ? JSON.stringify(this.mailboxRules) !== this.savedMailboxJson
      : false;
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
    if (!email || email === this.globalValue) {
      this.router.navigate(['/classification']);
      return;
    }
    this.router.navigate(['/classification', encodeURIComponent(email)]);
  }

  loadRules(): void {
    this.loading = true;
    this.error = '';
    this.successMessage = '';
    if (this.isGlobal) {
      this.classificationService.getGlobal().subscribe({
        next: (res) => this.applyGlobal(res),
        error: (err) => {
          this.error = err?.error?.detail ?? 'Failed to load global classification rules';
          this.loading = false;
        },
      });
      return;
    }
    this.classificationService.getMailbox(this.selectedEmail).subscribe({
      next: (res) => this.applyMailbox(res),
      error: (err) => {
        this.error = err?.error?.detail ?? 'Failed to load mailbox classification rules';
        this.loading = false;
      },
    });
  }

  saveRules(): void {
    this.error = '';
    this.successMessage = '';
    if (this.isGlobal) {
      if (!this.globalRules || this.globalRules.categories.length === 0) {
        this.error = 'At least one spam category is required.';
        return;
      }
      const slugs = this.globalRules.categories.map((c) => c.slug.trim());
      if (new Set(slugs).size !== slugs.length) {
        this.error = 'Category slugs must be unique.';
        return;
      }
      this.globalRules.categories.forEach((category) => {
        category.is_spam = true;
        category.folder = this.globalRules?.config.spam_folder || 'Junk';
        category.skip_forward = true;
      });
      this.saving = true;
      this.classificationService.saveGlobal(this.globalRules).subscribe({
        next: (res) => {
          this.applyGlobal(res);
          this.saving = false;
          this.successMessage = 'Global classification rules saved.';
        },
        error: (err) => {
          this.error = err?.error?.detail ?? 'Failed to save global classification rules';
          this.saving = false;
        },
      });
      return;
    }

    if (!this.mailboxRules) return;
    const slugs = this.mailboxRules.categories.map((c) => c.slug.trim());
    if (new Set(slugs).size !== slugs.length) {
      this.error = 'Category slugs must be unique.';
      return;
    }
    this.mailboxRules.categories.forEach((category) => {
      category.is_spam = false;
    });
    this.saving = true;
    this.classificationService.saveMailbox(this.selectedEmail, this.mailboxRules).subscribe({
      next: (res) => {
        this.applyMailbox(res);
        this.saving = false;
        this.successMessage = 'Mailbox classification rules saved.';
      },
      error: (err) => {
        this.error = err?.error?.detail ?? 'Failed to save mailbox classification rules';
        this.saving = false;
      },
    });
  }

  seedMailbox(): void {
    this.seeding = true;
    this.error = '';
    this.successMessage = '';
    this.classificationService.seedMailbox(this.selectedEmail).subscribe({
      next: (res) => {
        this.applyMailbox(res);
        this.seeding = false;
        this.successMessage = 'Starter categories copied onto this mailbox.';
      },
      error: (err) => {
        this.error = err?.error?.detail ?? 'Failed to copy starter categories';
        this.seeding = false;
      },
    });
  }

  addCategory(): void {
    const categories = this.isGlobal
      ? this.globalRules?.categories
      : this.mailboxRules?.categories;
    if (!categories) return;
    const nextOrder = (categories.at(-1)?.sort_order ?? 0) + 10;
    const next: ClassificationCategory = {
      slug: this.isGlobal ? 'spam' : '',
      display_name: this.isGlobal ? 'Spam' : '',
      classification_hints: '',
      folder: this.isGlobal ? (this.globalRules?.config.spam_folder || 'Junk') : '',
      forward_to: null,
      needs_live_agent: false,
      is_spam: this.isGlobal,
      route_by_person: false,
      skip_forward: this.isGlobal,
      sort_order: nextOrder,
      enabled: true,
    };
    categories.push(next);
  }

  removeCategory(index: number): void {
    const categories = this.isGlobal
      ? this.globalRules?.categories
      : this.mailboxRules?.categories;
    if (!categories) return;
    categories.splice(index, 1);
  }

  addEmployee(): void {
    if (!this.globalRules) return;
    this.globalRules.employees = [
      ...this.globalRules.employees,
      { name: '', email: '', aliases: [] },
    ];
  }

  removeEmployee(index: number): void {
    if (!this.globalRules) return;
    this.globalRules.employees = this.globalRules.employees.filter((_, i) => i !== index);
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

  private applyGlobal(res: ClassificationRules): void {
    this.globalRules = {
      ...res,
      config: { ...res.config },
      categories: res.categories.map((c) => ({ ...c })),
      employees: res.employees.map((e) => ({
        ...e,
        aliases: [...(e.aliases ?? [])],
      })),
    };
    this.mailboxRules = null;
    this.savedGlobalJson = JSON.stringify(this.globalRules);
    this.updatedAt = res.updated_at;
    this.loading = false;
  }

  private applyMailbox(res: MailboxClassificationRules): void {
    this.mailboxRules = {
      ...res,
      categories: res.categories.map((c) => ({ ...c })),
    };
    this.globalRules = null;
    this.savedMailboxJson = JSON.stringify(this.mailboxRules);
    this.updatedAt = res.updated_at;
    this.loading = false;
  }
}