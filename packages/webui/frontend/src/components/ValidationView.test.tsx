import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ValidationView } from "./ValidationView";
import type { ValidationResponse } from "../api/types";

const response: ValidationResponse = {
  findings: [
    { code: "E-CYCLE", severity: "E", message: "Cycle found.", doc_id: "RE-FEAT-AAAAAA", path: null, fix: "Remove an edge." },
    { code: "W-ORPHAN", severity: "W", message: "Orphan.", doc_id: "RE-GOAL-BBBBBB", path: null, fix: null },
  ],
  error_count: 1,
  warning_count: 1,
};

function renderView(validation: ValidationResponse = response) {
  const onSelect = vi.fn();
  render(<ValidationView validation={validation} loading={false} error={null} onSelect={onSelect} />);
  return { onSelect };
}

describe("ValidationView severities", () => {
  it("labels E and W findings distinctly with the real core severity values", () => {
    renderView();

    const errorItem = screen.getByText("E-CYCLE").closest("li") as HTMLElement;
    const warnItem = screen.getByText("W-ORPHAN").closest("li") as HTMLElement;
    expect(within(errorItem).getByText("Error")).toBeInTheDocument();
    expect(within(warnItem).getByText("Warning")).toBeInTheDocument();
    expect(within(errorItem).getByText("Error").className).toMatch(/bg-amber-100/);
    expect(within(warnItem).getByText("Warning").className).not.toMatch(/bg-amber-100/);
  });

  it("counts errors and warnings from the response", () => {
    renderView({ ...response, error_count: 3, warning_count: 2 });

    expect(screen.getByText("Errors: 3 · Warnings: 2")).toBeInTheDocument();
  });
});

describe("ValidationView subjects", () => {
  it("opens the document for a finding that has a doc_id", async () => {
    const { onSelect } = renderView();
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Open RE-FEAT-AAAAAA" }));

    expect(onSelect).toHaveBeenCalledWith("RE-FEAT-AAAAAA");
  });

  it("shows a path finding as escaped text with no link and no document action", async () => {
    const hostile = "<img src=x onerror=alert(1)>.md";
    const { onSelect } = renderView({
      findings: [{ code: "E-ASSET-MISSING", severity: "E", message: "Asset missing.", doc_id: null, path: hostile, fix: null }],
      error_count: 1,
      warning_count: 0,
    });

    expect(screen.getByText(hostile)).toBeInTheDocument();
    expect(screen.getByText(hostile).closest("a")).toBeNull();
    expect(screen.getByText(hostile).closest("button")).toBeNull();
    expect(document.querySelector("img")).toBeNull();
    expect(onSelect).not.toHaveBeenCalled();
  });
});
