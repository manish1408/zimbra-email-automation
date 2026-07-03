import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { AgentTraining, ClassificationRules } from '../models/email.models';
import { ApiClient } from './api-client.service';

@Injectable({ providedIn: 'root' })
export class AgentService {
  constructor(private readonly api: ApiClient) {}

  getTraining(): Observable<AgentTraining> {
    return this.api.get<AgentTraining>('/agent/training');
  }

  saveGeneralRules(generalRules: string): Observable<AgentTraining> {
    return this.api.put<AgentTraining>('/agent/training/general-rules', {
      general_rules: generalRules,
    });
  }

  saveDraftReplyRules(draftReplyRules: string): Observable<AgentTraining> {
    return this.api.put<AgentTraining>('/agent/training/draft-reply-rules', {
      draft_reply_rules: draftReplyRules,
    });
  }

  getClassificationRules(): Observable<ClassificationRules> {
    return this.api.get<ClassificationRules>('/agent/classification-rules');
  }

  saveClassificationRules(rules: ClassificationRules): Observable<ClassificationRules> {
    return this.api.put<ClassificationRules>('/agent/classification-rules', rules);
  }
}
