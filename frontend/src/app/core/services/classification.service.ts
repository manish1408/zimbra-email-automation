import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import {
  ClassificationRules,
  MailboxClassificationRules,
} from '../models/email.models';
import { ApiClient } from './api-client.service';

@Injectable({ providedIn: 'root' })
export class ClassificationService {
  constructor(private readonly api: ApiClient) {}

  getGlobal(): Observable<ClassificationRules> {
    return this.api.get<ClassificationRules>('/classification/global');
  }

  saveGlobal(rules: ClassificationRules): Observable<ClassificationRules> {
    return this.api.put<ClassificationRules>('/classification/global', rules);
  }

  getMailbox(email: string): Observable<MailboxClassificationRules> {
    return this.api.get<MailboxClassificationRules>(
      `/classification/mailboxes/${this.api.encodeEmail(email)}`,
    );
  }

  saveMailbox(
    email: string,
    rules: MailboxClassificationRules,
  ): Observable<MailboxClassificationRules> {
    return this.api.put<MailboxClassificationRules>(
      `/classification/mailboxes/${this.api.encodeEmail(email)}`,
      {
        extra_instructions: rules.extra_instructions,
        default_forward: rules.default_forward,
        categories: rules.categories,
      },
    );
  }

  seedMailbox(email: string): Observable<MailboxClassificationRules> {
    return this.api.post<MailboxClassificationRules>(
      `/classification/mailboxes/${this.api.encodeEmail(email)}/seed`,
    );
  }
}