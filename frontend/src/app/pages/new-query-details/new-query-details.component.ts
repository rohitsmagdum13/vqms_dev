import { Component, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { WizardService } from '../../services/wizard.service';

@Component({
  selector: 'app-new-query-details',
  imports: [FormsModule],
  template: `
    <h2>Step 2 of 3: Enter Details</h2>
    <p>Type: {{ wizard.queryTypeLabel }}</p>

    <form (ngSubmit)="onNext()">
      <div>
        <label>Subject: </label>
        <input type="text" [(ngModel)]="wizard.subject" name="subject" required placeholder="Query subject" />
      </div>
      <br />
      <div>
        <label>Description: </label><br />
        <textarea [(ngModel)]="wizard.description" name="description" required rows="5" cols="60" placeholder="Describe your query in detail"></textarea>
      </div>
      <br />
      <div>
        <label>Priority: </label>
        <select [(ngModel)]="wizard.priority" name="priority" required>
          <option value="low">Low</option>
          <option value="medium">Medium</option>
          <option value="high">High</option>
          <option value="critical">Critical</option>
        </select>
      </div>
      <br />
      <div>
        <label>Reference Number: </label>
        <input type="text" [(ngModel)]="wizard.referenceNumber" name="referenceNumber" placeholder="INV-2026-0451 (optional)" />
      </div>
      <br />
      <button type="submit">Next — Review</button>
      <button type="button" (click)="goBack()">Back</button>
    </form>
  `,
  styles: [],
})
export class NewQueryDetailsComponent implements OnInit {
  constructor(public wizard: WizardService, private router: Router) {}

  ngOnInit(): void {
    // If user somehow skipped step 1, send them back
    if (!this.wizard.queryType) {
      this.router.navigate(['/portal/new-query']);
    }
  }

  onNext(): void {
    if (!this.wizard.subject || !this.wizard.description) {
      return; // Let browser native validation handle it
    }
    this.router.navigate(['/portal/new-query/review']);
  }

  goBack(): void {
    this.router.navigate(['/portal/new-query']);
  }
}
