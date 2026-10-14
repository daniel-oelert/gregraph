import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { StatusCards } from "./StatusCards";
import { status } from "../test/fixtures";
import type { StatusResponse } from "../api/types";

function renderCards(overrides: Partial<StatusResponse>) {
  const onSelect = vi.fn();
  render(<StatusCards status={{ ...status, ...overrides }} loading={false} error={null} onSelect={onSelect} />);
  return { onSelect };
}

describe("StatusCards link labels", () => {
  it("shows the full 'SRC type TGT' label and opens the SOURCE document on click", async () => {
    const { onSelect } = renderCards({ pending: ["RE-AAAAAA refines RE-BBBBBB"] });
    const user = userEvent.setup();

    const button = screen.getByRole("button", { name: "RE-AAAAAA refines RE-BBBBBB" });
    expect(button).toHaveTextContent("RE-AAAAAA refines RE-BBBBBB");
    await user.click(button);

    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect).toHaveBeenCalledWith("RE-AAAAAA");
  });

  it("uses the same source extraction for outdated and stale lists", async () => {
    const { onSelect } = renderCards({
      pending: [],
      outdated: ["RE-CCCCCC verifies RE-AAAAAA"],
      stale: ["RE-DDDDDD depends-on-x RE-AAAAAA"],
    });
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "RE-CCCCCC verifies RE-AAAAAA" }));
    await user.click(screen.getByRole("button", { name: "RE-DDDDDD depends-on-x RE-AAAAAA" }));

    expect(onSelect.mock.calls).toEqual([["RE-CCCCCC"], ["RE-DDDDDD"]]);
  });

  it("still opens a bare canonical document ID", async () => {
    const { onSelect } = renderCards({ pending: ["RE-BBBBBB"] });
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "RE-BBBBBB" }));

    expect(onSelect).toHaveBeenCalledWith("RE-BBBBBB");
  });

  it("renders malformed labels as plain text and never navigates to them", async () => {
    const malformed = [
      "RE-AAAAAA verifies",
      "not a label at all",
      "re-aaaaaa refines RE-BBBBBB",
      "RE-AAAAAA Refines RE-BBBBBB",
      "RE-AAAAAA refines RE-BBBBBB extra",
      "XXXXXXXXXX-AAAAAA refines RE-BBBBBB",
      "RE-AAAAAA refines RE-ZZZZZ!",
    ];
    const { onSelect } = renderCards({ pending: malformed });
    const user = userEvent.setup();

    for (const label of malformed) {
      const text = screen.getByText(label);
      expect(text.closest("button")).toBeNull();
      await user.click(text);
    }

    expect(onSelect).not.toHaveBeenCalled();
  });

  it("does not render any list button for an empty status list", () => {
    renderCards({ pending: [], outdated: [], stale: [] });

    const cards = screen.getByRole("region", { name: "Status summary" });
    expect(within(cards).queryByRole("button")).toBeNull();
  });
});
