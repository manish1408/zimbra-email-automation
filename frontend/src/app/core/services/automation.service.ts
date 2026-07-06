import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import {
  AutomationLogListResponse,
  MessageAutomationResult,
  MessageAutomationRunListResponse,
} from '../models/email.models';
import { ApiClient } from './api-client.service';

@Injectable({ providedIn: 'root' })
export class AutomationService {
  constructor(private readonly api: ApiClient) {}

  private basePath(email: string, messageId: string): string {
    return `/automation/users/${this.api.encodeEmail(email)}/messages/${encodeURIComponent(messageId)}`;
  }

  run(email: string, messageId: string, force = false): Observable<MessageAutomationResult> {
    return this.api.post<MessageAutomationResult>(`${this.basePath(email, messageId)}/run`, {
      force,
    });
  }

  getResult(email: string, messageId: string): Observable<MessageAutomationResult> {
    return this.api.get<MessageAutomationResult>(this.basePath(email, messageId));
  }

  listRuns(
    email: string,
    messageId: string,
    limit = 10,
  ): Observable<MessageAutomationRunListResponse> {
    return this.api.get<MessageAutomationRunListResponse>(
      `${this.basePath(email, messageId)}/runs`,
      { limit },
    );
  }

  listLogs(
    email: string,
    options: { limit?: number; offset?: number; status?: string } = {},
  ): Observable<AutomationLogListResponse> {
    const params: Record<string, string | number> = {};
    if (options.limit != null) params['limit'] = options.limit;
    if (options.offset != null) params['offset'] = options.offset;
    if (options.status) params['status'] = options.status;
    return this.api.get<AutomationLogListResponse>(
      `/automation/users/${this.api.encodeEmail(email)}/logs`,
      params,
    );
  }
}
