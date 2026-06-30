import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { SyncResult } from '../models/email.models';
import { ApiClient } from './api-client.service';

@Injectable({ providedIn: 'root' })
export class SyncService {
  constructor(private readonly api: ApiClient) {}

  syncAll(query?: string, maxAccounts?: number): Observable<SyncResult> {
    return this.api.post<SyncResult>('/sync', undefined, {
      ...(query ? { query } : {}),
      ...(maxAccounts ? { max_accounts: maxAccounts } : {}),
    });
  }

  syncUser(email: string, query?: string): Observable<SyncResult> {
    return this.api.post<SyncResult>(
      `/sync/users/${this.api.encodeEmail(email)}`,
      undefined,
      query ? { query } : undefined,
    );
  }
}
