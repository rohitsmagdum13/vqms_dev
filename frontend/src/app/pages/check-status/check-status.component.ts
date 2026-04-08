import { Component } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { JsonPipe } from '@angular/common';
import { QueryService } from '../../services/query.service';

@Component({
  selector: 'app-check-status',
  imports: [FormsModule, JsonPipe],
  template: `
    <h2>Check Query Status</h2>

    <div>
      <label>Query ID: </label>
      <input type="text" [(ngModel)]="queryId" name="queryId" placeholder="VQ-2026-XXXX" />
      <button (click)="onCheck()">Check Status</button>
    </div>

    @if (result) {
      <br />
      <pre>{{ result | json }}</pre>
    }
    @if (error) {
      <br />
      <div><b>Error:</b> {{ error }}</div>
    }
  `,
  styles: [],
})
export class CheckStatusComponent {
  queryId = '';
  result: unknown = null;
  error = '';

  constructor(private queryService: QueryService) {}

  onCheck(): void {
    this.result = null;
    this.error = '';

    this.queryService.getQueryStatus(this.queryId).subscribe({
      next: (res) => {
        this.result = res;
      },
      error: (err: unknown) => {
        const e = err as { error?: { detail?: string }; message?: string };
        this.error = e.error?.detail || e.message || 'Unknown error';
      },
    });
  }
}
