import createClient from "openapi-fetch";
import type { paths } from "./schema";

// Same-origin everywhere: the Vite dev proxy and nginx both route
// /transcribe and /transcript to the API.
export const client = createClient<paths>({ baseUrl: "" });
