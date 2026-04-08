import { Component, OnInit } from '@angular/core';
import { Router } from '@angular/router';
import { AuthService } from '../../services/auth.service';
import { QueryService } from '../../services/query.service';

interface Kpis {
  open_queries: number;
  resolved_queries: number;
  avg_resolution_hours: number;
}

interface QueryRow {
  query_id: string;
  status: string;
  source: string;
  created_at: string;
}

@Component({
  selector: 'app-portal',
  imports: [],
  template: `
    <h2>Portal Dashboard</h2>
    <p>Welcome, {{ email }}</p>
    <p>Vendor ID: {{ vendorId }}</p>

    <hr />
    <h3>KPIs</h3>
    <ul>
      <li>Open queries: {{ kpis.open_queries }}</li>
      <li>Resolved queries: {{ kpis.resolved_queries }}</li>
      <li>Avg resolution time: {{ kpis.avg_resolution_hours }} hours</li>
    </ul>

    <hr />
    <button (click)="goNewQuery()">+ New Query</button>
    <button (click)="onLogout()">Logout</button>

    <hr />
    <h3>Recent Queries</h3>
    @if (queries.length === 0) {
      <p>No queries yet.</p>
    } @else {
      <table border="1">
        <tr>
          <th>Query ID</th>
          <th>Status</th>
          <th>Source</th>
          <th>Created At</th>
        </tr>
        @for (q of queries; track q.query_id) {
          <tr>
            <td>{{ q.query_id }}</td>
            <td>{{ q.status }}</td>
            <td>{{ q.source }}</td>
            <td>{{ q.created_at }}</td>
          </tr>
        }
      </table>
    }
  `,
  styles: [],
})
export class PortalComponent implements OnInit {
  email = '';
  vendorId = '';
  kpis: Kpis = { open_queries: 0, resolved_queries: 0, avg_resolution_hours: 0 };
  queries: QueryRow[] = [];

  constructor(
    private auth: AuthService,
    private queryService: QueryService,
    private router: Router,
  ) {}

  ngOnInit(): void {
    this.email = this.auth.getEmail();
    this.vendorId = this.auth.getVendorId();
    this.loadKpis();
    this.loadQueries();
  }

  loadKpis(): void {
    this.queryService.getDashboardKpis().subscribe({
      next: (res) => {
        this.kpis = res as Kpis;
      },
      error: () => {
        /* KPIs stay at zero on failure */
      },
    });
  }

  loadQueries(): void {
    this.queryService.listQueries().subscribe({
      next: (res) => {
        const data = res as { queries: QueryRow[] };
        this.queries = data.queries || [];
      },
      error: () => {
        /* queries stay empty on failure */
      },
    });
  }

  goNewQuery(): void {
    this.router.navigate(['/portal/new-query']);
  }

  onLogout(): void {
    this.auth.logout();
  }
}
