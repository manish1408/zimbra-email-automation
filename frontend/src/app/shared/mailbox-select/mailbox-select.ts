import { CommonModule } from '@angular/common';
import {
  Component,
  ElementRef,
  HostListener,
  Input,
  output,
  viewChild,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { User } from '../../core/models/email.models';

export interface MailboxSelectOption {
  value: string;
  label: string;
}

@Component({
  selector: 'app-mailbox-select',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './mailbox-select.html',
  styleUrl: './mailbox-select.scss',
})
export class MailboxSelectComponent {
  @Input() users: User[] = [];
  @Input() value = '';
  @Input() disabled = false;
  @Input() placeholder = 'Search mailboxes…';
  @Input() emptyLabel = '';
  @Input() extraOptions: MailboxSelectOption[] = [];

  readonly valueChange = output<string>();
  readonly searchInput = viewChild<ElementRef<HTMLInputElement>>('searchInput');

  open = false;
  query = '';
  highlightIndex = 0;

  constructor(private readonly host: ElementRef<HTMLElement>) {}

  get selectedLabel(): string {
    if (this.emptyLabel && !this.value) {
      return this.emptyLabel;
    }
    const extra = this.extraOptions.find((option) => option.value === this.value);
    if (extra) {
      return extra.label;
    }
    const user = this.users.find((item) => item.email === this.value);
    if (!user) {
      return this.value || this.placeholder;
    }
    return user.display_name ? `${user.display_name} — ${user.email}` : user.email;
  }

  get filteredOptions(): MailboxSelectOption[] {
    const q = this.query.trim().toLowerCase();
    const extras = this.extraOptions.filter(
      (option) => !q || option.label.toLowerCase().includes(q),
    );
    const users = this.users
      .filter((user) => {
        if (!q) return true;
        return (
          user.email.toLowerCase().includes(q) ||
          (user.display_name ?? '').toLowerCase().includes(q)
        );
      })
      .map((user) => ({
        value: user.email,
        label: user.display_name ? `${user.display_name} — ${user.email}` : user.email,
      }));
    const options = [...extras, ...users];
    if (this.emptyLabel) {
      const emptyMatches = !q || this.emptyLabel.toLowerCase().includes(q);
      if (emptyMatches) {
        return [{ value: '', label: this.emptyLabel }, ...options];
      }
    }
    return options;
  }

  toggle(): void {
    if (this.disabled) return;
    if (this.open) {
      this.close();
      return;
    }
    this.openPanel();
  }

  openPanel(): void {
    if (this.disabled) return;
    this.open = true;
    this.query = '';
    this.highlightIndex = Math.max(
      0,
      this.filteredOptions.findIndex((option) => option.value === this.value),
    );
    setTimeout(() => this.searchInput()?.nativeElement.focus(), 0);
  }

  close(): void {
    this.open = false;
    this.query = '';
  }

  select(value: string): void {
    this.valueChange.emit(value);
    this.close();
  }

  onQueryChange(): void {
    this.highlightIndex = 0;
  }

  onKeydown(event: KeyboardEvent): void {
    if (!this.open) {
      if (event.key === 'ArrowDown' || event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        this.openPanel();
      }
      return;
    }

    const options = this.filteredOptions;
    if (event.key === 'Escape') {
      event.preventDefault();
      this.close();
      return;
    }
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      this.highlightIndex = Math.min(this.highlightIndex + 1, Math.max(options.length - 1, 0));
      return;
    }
    if (event.key === 'ArrowUp') {
      event.preventDefault();
      this.highlightIndex = Math.max(this.highlightIndex - 1, 0);
      return;
    }
    if (event.key === 'Enter') {
      event.preventDefault();
      const option = options[this.highlightIndex];
      if (option) {
        this.select(option.value);
      }
    }
  }

  @HostListener('document:click', ['$event'])
  onDocumentClick(event: MouseEvent): void {
    if (!this.open) return;
    if (!this.host.nativeElement.contains(event.target as Node)) {
      this.close();
    }
  }
}
