import { Link } from "react-router";

export function NotFoundPage() {
  return (
    <main className="mx-auto max-w-2xl space-y-4 p-8">
      <h1 className="text-2xl font-bold">Not found</h1>
      <Link to="/" className="text-blue-700 underline">
        Go home
      </Link>
    </main>
  );
}
