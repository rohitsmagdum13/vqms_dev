import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Router } from '@angular/router';
import { Observable, tap } from 'rxjs';

const API_URL = 'http://localhost:8000';

export interface LoginResponse {
  token: string;
  vendor_id: string;
  email: string;
  vendor_name: string;
  role: string;
}

@Injectable({ providedIn: 'root' })
export class AuthService {
  constructor(private http: HttpClient, private router: Router) {}

  login(email: string, password: string): Observable<LoginResponse> {
    return this.http
      .post<LoginResponse>(`${API_URL}/auth/login`, { email, password })
      .pipe(
        tap((res) => {
          localStorage.setItem('token', res.token);
          localStorage.setItem('vendor_id', res.vendor_id);
          localStorage.setItem('email', res.email);
          localStorage.setItem('vendor_name', res.vendor_name);
        })
      );
  }

  logout(): void {
    localStorage.removeItem('token');
    localStorage.removeItem('vendor_id');
    localStorage.removeItem('email');
    localStorage.removeItem('vendor_name');
    this.router.navigate(['/login']);
  }

  isLoggedIn(): boolean {
    return !!localStorage.getItem('token');
  }

  getVendorId(): string {
    return localStorage.getItem('vendor_id') || '';
  }

  getEmail(): string {
    return localStorage.getItem('email') || '';
  }

  getVendorName(): string {
    return localStorage.getItem('vendor_name') || '';
  }

  getToken(): string {
    return localStorage.getItem('token') || '';
  }
}
