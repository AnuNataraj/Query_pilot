import { Component, OnInit, inject, signal } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';

import { Api } from './services/api';

@Component({
  selector: 'app-root',
  imports: [RouterOutlet, RouterLink, RouterLinkActive],
  templateUrl: './app.html',
  styleUrl: './app.css',
})
export class App implements OnInit {
  private api = inject(Api);

  modelName = signal('');
  backendDown = signal(false);

  ngOnInit(): void {
    this.api.getHealth().subscribe({
      next: (health) => {
        if (health.llm.provider === 'demo') {
          this.modelName.set('Offline demo (no LLM)');
        } else {
          this.modelName.set(`${health.llm.provider} / ${health.llm.model}`);
        }
      },
      error: () => this.backendDown.set(true),
    });
  }
}
