import { Component } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { WizardService } from '../../services/wizard.service';

@Component({
  selector: 'app-new-query-type',
  imports: [FormsModule],
  template: `
    <h2>Step 1 of 3: Select Query Type</h2>

    <div>
      <label>
        <input type="radio" name="queryType" value="billing" [(ngModel)]="selectedType" /> Invoice Issue
      </label>
      <br />
      <label>
        <input type="radio" name="queryType" value="technical" [(ngModel)]="selectedType" /> Purchase Order
      </label>
      <br />
      <label>
        <input type="radio" name="queryType" value="account" [(ngModel)]="selectedType" /> Payment Query
      </label>
      <br />
      <label>
        <input type="radio" name="queryType" value="compliance" [(ngModel)]="selectedType" /> Contract Issue
      </label>
      <br />
      <label>
        <input type="radio" name="queryType" value="other" [(ngModel)]="selectedType" /> General Inquiry
      </label>
    </div>

    <br />
    <button (click)="onNext()" [disabled]="!selectedType">Next</button>
    <button (click)="goBack()">Back to Portal</button>
  `,
  styles: [],
})
export class NewQueryTypeComponent {
  selectedType = '';

  // Map backend enum values to human-readable labels for the review step
  private typeLabels: Record<string, string> = {
    billing: 'Invoice Issue',
    technical: 'Purchase Order',
    account: 'Payment Query',
    compliance: 'Contract Issue',
    other: 'General Inquiry',
  };

  constructor(private wizard: WizardService, private router: Router) {
    // Restore selection if user navigates back from step 2
    if (this.wizard.queryType) {
      this.selectedType = this.wizard.queryType;
    }
  }

  onNext(): void {
    this.wizard.queryType = this.selectedType;
    this.wizard.queryTypeLabel = this.typeLabels[this.selectedType] || this.selectedType;
    this.router.navigate(['/portal/new-query/details']);
  }

  goBack(): void {
    this.router.navigate(['/portal']);
  }
}
