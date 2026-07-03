import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { AgentTraining } from '../models/email.models';
import { ApiClient } from './api-client.service';

@Injectable({ providedIn: 'root' })
export class AgentService {
  constructor(private readonly api: ApiClient) {}

  getTraining(): Observable<AgentTraining> {
    return this.api.get<AgentTraining>('/agent/training');
  }

  saveTraining(content: string): Observable<AgentTraining> {
    return this.api.put<AgentTraining>('/agent/training', { content });
  }
}
