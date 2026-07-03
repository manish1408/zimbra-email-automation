import { Routes } from '@angular/router';
import { AgentComponent } from './features/agent/agent';
import { InboxComponent } from './features/inbox/inbox';
import { SettingsComponent } from './features/settings/settings';

export const routes: Routes = [
  { path: '', redirectTo: 'inbox', pathMatch: 'full' },
  { path: 'inbox', component: InboxComponent },
  { path: 'inbox/:userEmail', component: InboxComponent },
  { path: 'agent', component: AgentComponent },
  { path: 'settings', component: SettingsComponent },
];
