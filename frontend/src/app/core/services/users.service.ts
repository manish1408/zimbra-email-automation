import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { User, UserListResponse } from '../models/email.models';
import { ApiClient } from './api-client.service';

@Injectable({ providedIn: 'root' })
export class UsersService {
  constructor(private readonly api: ApiClient) {}

  listUsers(): Observable<UserListResponse> {
    return this.api.get<UserListResponse>('/users');
  }

  getUser(email: string): Observable<User> {
    return this.api.get<User>(`/users/${this.api.encodeEmail(email)}`);
  }
}
