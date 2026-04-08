import { Injectable } from '@angular/core';

/**
 * Stores wizard form data in memory across Steps P3, P4, P5.
 * No server calls — browser-only state as per solution flow doc.
 * Data is lost on page refresh (intentional for dev).
 */
@Injectable({ providedIn: 'root' })
export class WizardService {
  queryType = '';
  queryTypeLabel = '';
  subject = '';
  description = '';
  priority = 'medium';
  referenceNumber = '';

  reset(): void {
    this.queryType = '';
    this.queryTypeLabel = '';
    this.subject = '';
    this.description = '';
    this.priority = 'medium';
    this.referenceNumber = '';
  }
}
