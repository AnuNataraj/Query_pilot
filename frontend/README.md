# QueryPilot frontend (Angular)

See the main README one folder up for full setup.

```bash
npm install
npm start          # http://localhost:4200, forwards /api to Django on port 8000
npm run build      # production build into dist/
```

Files:

- `src/app/services/api.ts`: all HTTP calls to the Django API
- `src/app/models.ts`: TypeScript types for the API responses
- `src/app/pages/ask/`: question box, answer, chart, data table, SQL editor, steps
- `src/app/pages/knowledge/`: knowledge base form and table
- `src/app/pages/history/`: past questions
- `src/app/components/result-chart/`: Chart.js chart
- `proxy.conf.json`: sends `/api` requests to `http://127.0.0.1:8000`
