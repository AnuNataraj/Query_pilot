// Types for the data returned by the Django API.

export type Cell = string | number | null;

export interface Step {
  id: string;
  kind: 'retrieve' | 'generate' | 'guard' | 'execute' | 'insight';
  status: 'running' | 'done' | 'error';
  label: string;
  ms: number | null;
  detail: {
    docs?: ContextDoc[];
    sql?: string | null;
    reasoning?: string;
    error?: string;
    rows?: number;
  };
}

export interface ContextDoc {
  id: number;
  title: string;
  kind: string;
  score: number;
  content?: string;
}

export interface ChartInfo {
  type: 'line' | 'bar' | 'kpi' | 'none';
  label_column?: string;
  value_columns?: string[];
}

export interface AskResponse {
  id: number;
  status: 'answered' | 'unanswerable' | 'blocked' | 'failed';
  question: string;
  sql: string;
  reasoning: string;
  assumptions: string[];
  attempts: number;
  insight: string;
  follow_ups: string[];
  chart: ChartInfo;
  context: ContextDoc[];
  error: string;
  provider: string;
  latency_ms: number;
  columns: string[];
  rows: Cell[][];
  row_count: number;
  truncated: boolean;
  elapsed_ms: number;
  steps: Step[];
}

export interface SqlResult {
  sql: string;
  columns: string[];
  rows: Cell[][];
  row_count: number;
  truncated: boolean;
  elapsed_ms: number;
  chart: ChartInfo;
  insight: string;
}

export interface PlanStep {
  id: number;
  parent: number;
  detail: string;
}

export interface Health {
  llm: { provider: string; model: string; ready: boolean; error: string };
  warehouse_ready: boolean;
  data_from: string | null;
  data_to: string | null;
  knowledge_docs: number;
  suggestions: string[];
}

export interface HistoryItem {
  id: number;
  question: string;
  sql: string;
  status: string;
  attempts: number;
  row_count: number | null;
  latency_ms: number;
  created_at: string;
}

export interface KnowledgeDoc {
  id?: number;
  title: string;
  kind: string;
  content: string;
}
