import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Service, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { AskResponse, Health, HistoryItem, KnowledgeDoc, PlanStep, SqlResult } from '../models';

// The Angular dev server forwards /api requests to Django (see proxy.conf.json).
const API_URL = '/api';

@Service()
export class Api {
  private http = inject(HttpClient);

  getHealth(): Observable<Health> {
    return this.http.get<Health>(`${API_URL}/health/`);
  }

  ask(question: string, previous: { question: string; sql: string } | null): Observable<AskResponse> {
    // stream=false: wait for the whole answer instead of reading it step by step
    return this.http.post<AskResponse>(`${API_URL}/ask/?stream=false`, { question, previous });
  }

  runSql(sql: string): Observable<SqlResult> {
    return this.http.post<SqlResult>(`${API_URL}/sql/run/`, { sql });
  }

  explainSql(sql: string): Observable<{ plan: PlanStep[] }> {
    return this.http.post<{ plan: PlanStep[] }>(`${API_URL}/sql/explain/`, { sql });
  }

  getHistory(): Observable<HistoryItem[]> {
    return this.http.get<HistoryItem[]>(`${API_URL}/history/`);
  }

  getKnowledge(): Observable<KnowledgeDoc[]> {
    return this.http.get<KnowledgeDoc[]>(`${API_URL}/knowledge/`);
  }

  addKnowledge(doc: KnowledgeDoc): Observable<KnowledgeDoc> {
    return this.http.post<KnowledgeDoc>(`${API_URL}/knowledge/`, doc);
  }

  updateKnowledge(id: number, doc: KnowledgeDoc): Observable<KnowledgeDoc> {
    return this.http.put<KnowledgeDoc>(`${API_URL}/knowledge/${id}/`, doc);
  }

  deleteKnowledge(id: number): Observable<void> {
    return this.http.delete<void>(`${API_URL}/knowledge/${id}/`);
  }
}

export function getErrorMessage(err: HttpErrorResponse): string {
  if (err.error?.error) {
    return err.error.error;
  }
  if (err.error?.detail) {
    return err.error.detail;
  }
  if (err.status === 0 || err.status >= 500) {
    return 'Could not connect to the backend. Make sure Django is running (python manage.py runserver).';
  }
  return `Request failed (status ${err.status}).`;
}
