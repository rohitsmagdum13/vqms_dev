import { Component } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { AuthService } from '../../services/auth.service';

@Component({
  selector: 'app-login',
  imports: [FormsModule],
  template: `
    <h2>VQMS — Vendor Login</h2>

    <form (ngSubmit)="onLogin()">
      <div>
        <label>Email: </label>
        <input type="text" [(ngModel)]="email" name="email" placeholder="vendor@company.com" />
      </div>
      <br />
      <div>
        <label>Password: </label>
        <input type="password" [(ngModel)]="password" name="password" placeholder="any password" />
      </div>
      <br />
      <button type="submit">Login</button>
    </form>

    @if (error) {
      <br />
      <div><b>Login failed:</b> {{ error }}</div>
    }

    <br />
    <small>Dev mode — any email/password works. No real auth.</small>
  `,
  styles: [],
})
export class LoginComponent {
  email = '';
  password = '';
  error = '';

  constructor(private auth: AuthService, private router: Router) {}

  onLogin(): void {
    this.error = '';

    if (!this.email || !this.password) {
      this.error = 'Email and password are required.';
      return;
    }

    this.auth.login(this.email, this.password).subscribe({
      next: () => {
        this.router.navigate(['/portal']);
      },
      error: (err: unknown) => {
        const e = err as { error?: { detail?: string }; message?: string };
        this.error = e.error?.detail || e.message || 'Unknown error';
      },
    });
  }
}
