import { Component, OnInit, inject } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { HealthResponse } from './core/models/email.models';
import { SystemService } from './core/services/system.service';

@Component({
  selector: 'app-root',
  imports: [RouterOutlet, RouterLink, RouterLinkActive],
  templateUrl: './app.html',
  styleUrl: './app.scss',
})
export class App implements OnInit {
  private readonly systemService = inject(SystemService);
  health: HealthResponse | null = null;

  ngOnInit(): void {
    this.systemService.health().subscribe({
      next: (h) => (this.health = h),
      error: () => (this.health = null),
    });
  }
}
