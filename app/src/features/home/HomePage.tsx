import { StartLesson } from "../tutor/StartLesson";
import { Dashboard } from "./Dashboard";

export function HomePage() {
  return (
    <div className="mx-auto max-w-3xl space-y-6 p-6">
      <StartLesson />
      <Dashboard />
    </div>
  );
}
