import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { AgentRunRequest, AgentRunResult } from '../models/email.models';
import { ApiClient } from './api-client.service';

@Injectable({ providedIn: 'root' })
export class AgentService {
  constructor(private readonly api: ApiClient) {}

  run(request: AgentRunRequest): Observable<AgentRunResult> {
    return this.api.post<AgentRunResult>('/agent/run', request);
  }

  getSession(threadId: string): Observable<{ thread_id: string; state: unknown; next: unknown }> {
    return this.api.get(`/agent/sessions/${encodeURIComponent(threadId)}`);
  }
}
