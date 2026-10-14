import { useEffect, useState } from "react";
import { errorMessage } from "./errors";

export interface LoaderState<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
}

/**
 * Runs `load` whenever `deps` change. Responses that arrive after a newer request
 * started (or after unmount) are ignored, so a slow reply can never replace newer data.
 * Passing `null` as the loader means "nothing to load".
 */
export function useLoader<T>(load: (() => Promise<T>) | null, deps: unknown[]): LoaderState<T> {
  const [state, setState] = useState<LoaderState<T>>({ data: null, error: null, loading: load !== null });

  useEffect(() => {
    if (load === null) {
      setState({ data: null, error: null, loading: false });
      return;
    }
    let active = true;
    setState((previous) => ({ ...previous, error: null, loading: true }));
    load().then(
      (data) => {
        if (active) {
          setState({ data, error: null, loading: false });
        }
      },
      (error: unknown) => {
        if (active) {
          setState({ data: null, error: errorMessage(error), loading: false });
        }
      },
    );
    return () => {
      active = false;
    };
    // The caller controls the dependency list (request identity), not the loader closure.
  }, deps);

  return state;
}
