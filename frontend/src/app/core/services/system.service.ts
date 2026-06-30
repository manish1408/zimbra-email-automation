import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { ConnectionTestResponse, HealthResponse } from '../models/email.models';
import { ApiClient } from './api-client.service';

@Injectable({ providedIn: 'root' })
export class SystemService {
  constructor(private readonly api: ApiClient) {}

  health(): Observable<HealthResponse> {
    return this.api.get<HealthResponse>('/system/health');
  }

  testConnection(): Observable<ConnectionTestResponse> {
    return this.api.get<ConnectionTestResponse>('/system/test-connection');
  }
}
