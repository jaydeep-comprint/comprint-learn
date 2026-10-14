import { HealthStatus } from "../features/health/HealthStatus";

export function HomePage() {
  return (
    <main className="mx-auto max-w-2xl space-y-4 p-8">
      <h1 className="text-3xl font-bold">Learning App</h1>
      <HealthStatus />
    </main>
  );
}
