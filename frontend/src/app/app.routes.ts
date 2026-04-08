import { Routes } from '@angular/router';
import { authGuard } from './guards/auth.guard';
import { LoginComponent } from './pages/login/login.component';
import { PortalComponent } from './pages/portal/portal.component';
import { NewQueryTypeComponent } from './pages/new-query-type/new-query-type.component';
import { NewQueryDetailsComponent } from './pages/new-query-details/new-query-details.component';
import { NewQueryReviewComponent } from './pages/new-query-review/new-query-review.component';
import { CheckStatusComponent } from './pages/check-status/check-status.component';

export const routes: Routes = [
  { path: 'login', component: LoginComponent },
  { path: 'portal', component: PortalComponent, canActivate: [authGuard] },
  { path: 'portal/new-query', component: NewQueryTypeComponent, canActivate: [authGuard] },
  { path: 'portal/new-query/details', component: NewQueryDetailsComponent, canActivate: [authGuard] },
  { path: 'portal/new-query/review', component: NewQueryReviewComponent, canActivate: [authGuard] },
  { path: 'status', component: CheckStatusComponent, canActivate: [authGuard] },
  { path: '', redirectTo: 'login', pathMatch: 'full' },
  { path: '**', redirectTo: 'login' },
];
