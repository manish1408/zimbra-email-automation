import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import {
  FolderListResponse,
  InboxResponse,
  MessageDetail,
  MessageSearchResponse,
} from '../models/email.models';
import { ApiClient } from './api-client.service';

@Injectable({ providedIn: 'root' })
export class MailboxService {
  constructor(private readonly api: ApiClient) {}

  private userPath(email: string): string {
    return `/users/${this.api.encodeEmail(email)}`;
  }

  getInbox(email: string, limit = 50, offset = 0): Observable<InboxResponse> {
    return this.api.get<InboxResponse>(`${this.userPath(email)}/inbox`, { limit, offset });
  }

  searchMessages(
    email: string,
    query: string,
    limit = 50,
    offset = 0,
  ): Observable<MessageSearchResponse> {
    return this.api.get<MessageSearchResponse>(`${this.userPath(email)}/messages`, {
      query,
      limit,
      offset,
    });
  }

  getMessage(email: string, messageId: string): Observable<MessageDetail> {
    return this.api.get<MessageDetail>(
      `${this.userPath(email)}/messages/${encodeURIComponent(messageId)}`,
    );
  }

  listFolders(email: string): Observable<FolderListResponse> {
    return this.api.get<FolderListResponse>(`${this.userPath(email)}/folders`);
  }
}
