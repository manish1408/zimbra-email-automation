import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import {
  LocalMailboxStats,
  LocalMessageListResponse,
  MessageDetail,
  MessageMetadata,
} from '../models/email.models';
import { ApiClient } from './api-client.service';

@Injectable({ providedIn: 'root' })
export class LocalDataService {
  constructor(private readonly api: ApiClient) {}

  private userPath(email: string): string {
    return `/local/users/${this.api.encodeEmail(email)}`;
  }

  listMessages(
    email: string,
    limit = 50,
    offset = 0,
    analyzed?: boolean,
  ): Observable<LocalMessageListResponse> {
    return this.api.get<LocalMessageListResponse>(`${this.userPath(email)}/messages`, {
      limit,
      offset,
      analyzed,
    });
  }

  getMessage(email: string, messageId: string): Observable<MessageDetail> {
    return this.api.get<MessageDetail>(
      `${this.userPath(email)}/messages/${encodeURIComponent(messageId)}`,
    );
  }

  getMetadata(email: string, messageId: string): Observable<MessageMetadata> {
    return this.api.get<MessageMetadata>(
      `${this.userPath(email)}/messages/${encodeURIComponent(messageId)}/metadata`,
    );
  }

  getStats(email: string): Observable<LocalMailboxStats> {
    return this.api.get<LocalMailboxStats>(`${this.userPath(email)}/stats`);
  }
}
