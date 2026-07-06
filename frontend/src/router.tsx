import { createBrowserRouter } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { JobDetail } from "./pages/JobDetail";
import { Search } from "./pages/Search";
import { SubmitJob } from "./pages/SubmitJob";

export const router = createBrowserRouter([
  {
    element: <AppShell />,
    children: [
      { path: "/", element: <SubmitJob /> },
      { path: "/jobs/:jobId", element: <JobDetail /> },
      { path: "/search", element: <Search /> },
    ],
  },
]);
