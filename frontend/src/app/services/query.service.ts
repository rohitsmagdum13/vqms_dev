import { Injectable } from '@angular/core';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Observable } from 'rxjs';
import { AuthService } from './auth.service';

const API_URL = 'http://localhost:8000';

@Injectable({ providedIn: 'root' })
export class QueryService {
  constructor(private http: HttpClient, private auth: AuthService) {}

  private headers(): HttpHeaders {
    return new HttpHeaders({
      'X-Vendor-ID': this.auth.getVendorId(),
      'X-Vendor-Name': this.auth.getVendorName(),
    });
  }

  submitQuery(body: Record<string, unknown>): Observable<unknown> {
    return this.http.post(`${API_URL}/queries`, body, { headers: this.headers() });
  }

  getQueryStatus(queryId: string): Observable<unknown> {
    return this.http.get(`${API_URL}/queries/${queryId}`, { headers: this.headers() });
  }

  listQueries(): Observable<unknown> {
    return this.http.get(`${API_URL}/queries`, { headers: this.headers() });
  }

  getDashboardKpis(): Observable<unknown> {
    return this.http.get(`${API_URL}/dashboard/kpis`, { headers: this.headers() });
  }
}
