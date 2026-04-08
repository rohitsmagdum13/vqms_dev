import { Component } from '@angular/core';
import { RouterOutlet, RouterLink } from '@angular/router';
import { AuthService } from './services/auth.service';

@Component({
  selector: 'app-root',
  imports: [RouterOutlet, RouterLink],
  template: `
    <h1>VQMS — Vendor Query Management System</h1>
    @if (auth.isLoggedIn()) {
      <a routerLink="/portal">Portal</a> |
      <a routerLink="/status">Check Status</a> |
      <a routerLink="/login" (click)="auth.logout()">Logout</a>
    } @else {
      <a routerLink="/login">Login</a>
    }
    <hr />
    <router-outlet />
  `,
  styles: [],
})
export class App {
  constructor(public auth: AuthService) {}
}
