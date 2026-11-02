import { Routes } from '@angular/router';

import { Ask } from './pages/ask/ask';
import { History } from './pages/history/history';
import { Knowledge } from './pages/knowledge/knowledge';

export const routes: Routes = [
  { path: '', component: Ask },
  { path: 'knowledge', component: Knowledge },
  { path: 'history', component: History },
  { path: '**', redirectTo: '' },
];
