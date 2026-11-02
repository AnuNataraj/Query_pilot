import {
  AfterViewInit, Component, ElementRef, Input, OnChanges, OnDestroy, ViewChild,
} from '@angular/core';
import Chart from 'chart.js/auto';

import { Cell, ChartInfo } from '../../models';

@Component({
  selector: 'app-result-chart',
  imports: [],
  templateUrl: './result-chart.html',
  styleUrl: './result-chart.css',
})
export class ResultChart implements AfterViewInit, OnChanges, OnDestroy {
  @Input() columns: string[] = [];
  @Input() rows: Cell[][] = [];
  @Input() chart!: ChartInfo;

  @ViewChild('canvas') canvas!: ElementRef<HTMLCanvasElement>;

  private chartInstance?: Chart;

  ngAfterViewInit(): void {
    this.drawChart();
  }

  ngOnChanges(): void {
    if (this.canvas) {
      this.drawChart();
    }
  }

  ngOnDestroy(): void {
    this.chartInstance?.destroy();
  }

  private drawChart(): void {
    this.chartInstance?.destroy();
    if (!this.chart.label_column || !this.chart.value_columns?.length) {
      return;
    }

    // Chart the first numeric column against the label column
    const labelIndex = this.columns.indexOf(this.chart.label_column);
    const valueColumn = this.chart.value_columns[0];
    const valueIndex = this.columns.indexOf(valueColumn);

    this.chartInstance = new Chart(this.canvas.nativeElement, {
      type: this.chart.type === 'line' ? 'line' : 'bar',
      data: {
        labels: this.rows.map((row) => String(row[labelIndex])),
        datasets: [
          {
            label: valueColumn,
            data: this.rows.map((row) => Number(row[valueIndex])),
            backgroundColor: '#4a90d9',
            borderColor: '#4a90d9',
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          y: { beginAtZero: true },
        },
      },
    });
  }
}
