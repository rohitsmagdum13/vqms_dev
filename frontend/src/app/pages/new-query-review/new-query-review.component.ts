import { Component, OnInit } from '@angular/core';
import { Router } from '@angular/router';
import { WizardService } from '../../services/wizard.service';
import { QueryService } from '../../services/query.service';

interface SubmitResult {
  query_id: string;
  status: string;
  correlation_id: string;
  execution_id: string;
}

@Component({
  selector: 'app-new-query-review',
  imports: [],
  template: `
    <h2>Step 3 of 3: Review Your Query</h2>

    @if (!submitted) {
      <p><b>Type:</b> {{ wizard.queryTypeLabel }}</p>
      <p><b>Subject:</b> {{ wizard.subject }}</p>
      <p><b>Description:</b> {{ wizard.description }}</p>
      <p><b>Priority:</b> {{ wizard.priority }}</p>
      <p><b>Reference:</b> {{ wizard.referenceNumber || '(none)' }}</p>

      <br />
      <button (click)="onEdit()">Edit</button>
      <button (click)="onSubmit()">Submit Query</button>

      @if (error) {
        <br />
        <div><b>Error:</b> {{ error }}</div>
      }
    } @else {
      <p><b>Query submitted successfully!</b></p>
      <p>Query ID: {{ result.query_id }}</p>
      <p>Status: {{ result.status }}</p>
      <p>Correlation ID: {{ result.correlation_id }}</p>

      <br />
      <button (click)="goPortal()">Back to Portal</button>
    }
  `,
  styles: [],
})
export class NewQueryReviewComponent implements OnInit {
  submitted = false;
  error = '';
  result: SubmitResult = { query_id: '', status: '', correlation_id: '', execution_id: '' };

  constructor(
    public wizard: WizardService,
    private queryService: QueryService,
    private router: Router,
  ) {}

  ngOnInit(): void {
    // If user somehow skipped steps 1-2, send them back
    if (!this.wizard.queryType || !this.wizard.subject) {
      this.router.navigate(['/portal/new-query']);
    }
  }

  onEdit(): void {
    this.router.navigate(['/portal/new-query/details']);
  }

  onSubmit(): void {
    this.error = '';

    const body: Record<string, unknown> = {
      query_type: this.wizard.queryType,
      subject: this.wizard.subject,
      description: this.wizard.description,
      priority: this.wizard.priority,
    };

    if (this.wizard.referenceNumber) {
      body['reference_number'] = this.wizard.referenceNumber;
    }

    this.queryService.submitQuery(body).subscribe({
      next: (res) => {
        this.result = res as SubmitResult;
        this.submitted = true;
        this.wizard.reset();
      },
      error: (err: unknown) => {
        const e = err as { error?: { detail?: string }; message?: string };
        this.error = e.error?.detail || e.message || 'Unknown error';
      },
    });
  }

  goPortal(): void {
    this.router.navigate(['/portal']);
  }
}
