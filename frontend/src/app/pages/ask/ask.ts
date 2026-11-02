import { DecimalPipe } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute } from '@angular/router';

import { ResultChart } from '../../components/result-chart/result-chart';
import { AskResponse, Cell, PlanStep, Step } from '../../models';
import { Api, getErrorMessage } from '../../services/api';

@Component({
  selector: 'app-ask',
  imports: [FormsModule, DecimalPipe, ResultChart],
  templateUrl: './ask.html',
  styleUrl: './ask.css',
})
export class Ask implements OnInit {
  private api = inject(Api);
  private route = inject(ActivatedRoute);

  question = '';
  followUp = false;
  lastAnswered: { question: string; sql: string } | null = null;

  suggestions = signal<string[]>([]);
  loading = signal(false);
  error = signal('');
  result = signal<AskResponse | null>(null);

  // SQL editor
  sql = '';
  sqlError = signal('');
  sqlEdited = signal(false);
  plan = signal<PlanStep[]>([]);

  ngOnInit(): void {
    this.api.getHealth().subscribe({
      next: (health) => this.suggestions.set(health.suggestions),
      error: () => {},
    });

    // The History page links here with ?q=... to ask a question again
    const q = this.route.snapshot.queryParamMap.get('q');
    if (q) {
      this.question = q;
      this.ask();
    }
  }

  ask(): void {
    const question = this.question.trim();
    if (!question || this.loading()) {
      return;
    }

    const previous = this.followUp ? this.lastAnswered : null;

    this.loading.set(true);
    this.error.set('');
    this.result.set(null);
    this.resetSqlTools();

    this.api.ask(question, previous).subscribe({
      next: (res) => {
        this.result.set(res);
        this.sql = res.sql;
        this.loading.set(false);
        if (res.status === 'answered') {
          this.lastAnswered = { question: res.question, sql: res.sql };
        }
        this.followUp = false;
      },
      error: (err: HttpErrorResponse) => {
        this.error.set(getErrorMessage(err));
        this.loading.set(false);
      },
    });
  }

  askSample(question: string): void {
    this.question = question;
    this.followUp = false;
    this.ask();
  }

  runSql(): void {
    this.sqlError.set('');
    this.api.runSql(this.sql).subscribe({
      next: (res) => {
        const current = this.result();
        if (current) {
          this.result.set({
            ...current,
            ...res,
            status: 'answered',
            error: '',
            follow_ups: [],
          });
        }
        this.sqlEdited.set(true);
        this.plan.set([]);
      },
      error: (err: HttpErrorResponse) => this.sqlError.set(getErrorMessage(err)),
    });
  }

  explainSql(): void {
    this.sqlError.set('');
    this.api.explainSql(this.sql).subscribe({
      next: (res) => this.plan.set(res.plan),
      error: (err: HttpErrorResponse) => this.sqlError.set(getErrorMessage(err)),
    });
  }

  isNumber(value: Cell): boolean {
    return typeof value === 'number';
  }

  statusMessage(status: string): string {
    switch (status) {
      case 'unanswerable':
        return 'This question cannot be answered from the data.';
      case 'blocked':
        return 'The query was blocked by the safety check.';
      default:
        return 'The AI could not write a working query.';
    }
  }

  stepDetails(step: Step): string {
    if (step.detail.error) {
      return step.detail.error;
    }
    switch (step.kind) {
      case 'retrieve':
        return `${step.detail.docs?.length ?? 0} knowledge base entries found`;
      case 'generate':
        return step.detail.reasoning ?? '';
      case 'guard':
        return 'Read-only SELECT query';
      case 'execute':
        return `${step.detail.rows} rows returned`;
      default:
        return '';
    }
  }

  private resetSqlTools(): void {
    this.sqlError.set('');
    this.sqlEdited.set(false);
    this.plan.set([]);
  }
}
