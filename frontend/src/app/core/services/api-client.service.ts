import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { environment } from '../../../environments/environment';

@Injectable({ providedIn: 'root' })
export class ApiClient {
  private readonly base = environment.apiBaseUrl;

  constructor(private readonly http: HttpClient) {}

  encodeEmail(email: string): string {
    return encodeURIComponent(email);
  }

  get<T>(path: string, params?: Record<string, string | number | boolean | null | undefined>): Observable<T> {
    let httpParams = new HttpParams();
    if (params) {
      for (const [key, value] of Object.entries(params)) {
        if (value !== null && value !== undefined) {
          httpParams = httpParams.set(key, String(value));
        }
      }
    }
    return this.http.get<T>(`${this.base}${path}`, { params: httpParams });
  }

  post<T>(path: string, body?: unknown, params?: Record<string, string | number | boolean>): Observable<T> {
    let httpParams = new HttpParams();
    if (params) {
      for (const [key, value] of Object.entries(params)) {
        httpParams = httpParams.set(key, String(value));
      }
    }
    return this.http.post<T>(`${this.base}${path}`, body ?? {}, { params: httpParams });
  }
}
