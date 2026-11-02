import { DatePipe } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, OnInit, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';

import { HistoryItem } from '../../models';
import { Api, getErrorMessage } from '../../services/api';

@Component({
  selector: 'app-history',
  imports: [DatePipe, RouterLink],
  templateUrl: './history.html',
  styleUrl: './history.css',
})
export class History implements OnInit {
  private api = inject(Api);

  items = signal<HistoryItem[]>([]);
  error = signal('');

  ngOnInit(): void {
    this.api.getHistory().subscribe({
      next: (items) => this.items.set(items),
      error: (err: HttpErrorResponse) => this.error.set(getErrorMessage(err)),
    });
  }
}
