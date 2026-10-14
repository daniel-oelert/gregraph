import { ApiError } from "../api/client";

/** Human-readable message for any failure thrown by the API client or the runtime. */
export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return error.message;
  }
  if (error instanceof Error && error.message !== "") {
    return error.message;
  }
  return "Unexpected error. Try again.";
}
