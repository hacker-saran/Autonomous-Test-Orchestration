import { createContext, useContext, useReducer, type Dispatch, type ReactNode } from "react";
import { type Action, initialRunState, runReducer, type RunState } from "./runReducer";

const StateContext = createContext<RunState | null>(null);
const DispatchContext = createContext<Dispatch<Action> | null>(null);

export function RunProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(runReducer, initialRunState);
  return (
    <StateContext.Provider value={state}>
      <DispatchContext.Provider value={dispatch}>{children}</DispatchContext.Provider>
    </StateContext.Provider>
  );
}

export function useRunState(): RunState {
  const ctx = useContext(StateContext);
  if (!ctx) throw new Error("useRunState must be used within a RunProvider");
  return ctx;
}

export function useRunDispatch(): Dispatch<Action> {
  const ctx = useContext(DispatchContext);
  if (!ctx) throw new Error("useRunDispatch must be used within a RunProvider");
  return ctx;
}
