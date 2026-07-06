import { Routes } from '@angular/router';
import { AgentComponent } from './features/agent/agent';
import { AutomationLogsComponent } from './features/automation-logs/automation-logs';
import { InboxComponent } from './features/inbox/inbox';
import { SettingsComponent } from './features/settings/settings';

export const routes: Routes = [
  { path: '', redirectTo: 'inbox', pathMatch: 'full' },
  { path: 'inbox', component: InboxComponent },
  { path: 'inbox/:userEmail', component: InboxComponent },
  { path: 'automation-logs', component: AutomationLogsComponent },
  { path: 'automation-logs/:userEmail', component: AutomationLogsComponent },
  { path: 'agent', component: AgentComponent },
  { path: 'settings', component: SettingsComponent },
];
