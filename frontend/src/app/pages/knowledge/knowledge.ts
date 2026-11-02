import { HttpErrorResponse } from '@angular/common/http';
import { Component, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { KnowledgeDoc } from '../../models';
import { Api, getErrorMessage } from '../../services/api';

@Component({
  selector: 'app-knowledge',
  imports: [FormsModule],
  templateUrl: './knowledge.html',
  styleUrl: './knowledge.css',
})
export class Knowledge implements OnInit {
  private api = inject(Api);

  docs = signal<KnowledgeDoc[]>([]);
  error = signal('');
  message = signal('');

  editingId: number | null = null;
  form: KnowledgeDoc = { title: '', kind: 'glossary', content: '' };

  types = [
    { value: 'glossary', label: 'Business rule' },
    { value: 'table', label: 'Table guide' },
    { value: 'example', label: 'Example query' },
  ];

  ngOnInit(): void {
    this.loadDocs();
  }

  loadDocs(): void {
    this.api.getKnowledge().subscribe({
      next: (docs) => this.docs.set(docs),
      error: (err: HttpErrorResponse) => this.error.set(getErrorMessage(err)),
    });
  }

  save(): void {
    this.error.set('');
    this.message.set('');
    if (!this.form.title.trim() || !this.form.content.trim()) {
      this.error.set('Please fill in the title and content.');
      return;
    }

    const request = this.editingId
      ? this.api.updateKnowledge(this.editingId, this.form)
      : this.api.addKnowledge(this.form);

    request.subscribe({
      next: (doc) => {
        this.message.set(`Saved "${doc.title}". Ask a question that uses it on the Ask page.`);
        this.resetForm();
        this.loadDocs();
      },
      error: (err: HttpErrorResponse) => this.error.set(getErrorMessage(err)),
    });
  }

  edit(doc: KnowledgeDoc): void {
    this.editingId = doc.id ?? null;
    this.form = { title: doc.title, kind: doc.kind, content: doc.content };
    this.message.set('');
    this.error.set('');
    window.scrollTo(0, 0);
  }

  remove(doc: KnowledgeDoc): void {
    if (!doc.id || !confirm(`Delete "${doc.title}"?`)) {
      return;
    }
    this.api.deleteKnowledge(doc.id).subscribe({
      next: () => {
        this.message.set(`Deleted "${doc.title}".`);
        if (this.editingId === doc.id) {
          this.resetForm();
        }
        this.loadDocs();
      },
      error: (err: HttpErrorResponse) => this.error.set(getErrorMessage(err)),
    });
  }

  fillExample(): void {
    this.form = {
      title: 'VIP customer',
      kind: 'glossary',
      content: 'A VIP customer has lifetime revenue (completed orders only) of at least $10,000.',
    };
  }

  resetForm(): void {
    this.editingId = null;
    this.form = { title: '', kind: 'glossary', content: '' };
  }

  typeLabel(kind: string): string {
    return this.types.find((t) => t.value === kind)?.label ?? kind;
  }
}
