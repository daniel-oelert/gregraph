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
    const { onSelect } = renderCards({ pending: ["RE-STORY-AAAAAA refines RE-STORY-BBBBBB"] });
    const user = userEvent.setup();

    const button = screen.getByRole("button", { name: "RE-STORY-AAAAAA refines RE-STORY-BBBBBB" });
    expect(button).toHaveTextContent("RE-STORY-AAAAAA refines RE-STORY-BBBBBB");
    await user.click(button);

    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect).toHaveBeenCalledWith("RE-STORY-AAAAAA");
  });

  it("uses the same source extraction for outdated and stale lists", async () => {
    const { onSelect } = renderCards({
      pending: [],
      outdated: ["RE-TEST-CCCCCC verifies RE-STORY-AAAAAA"],
      stale: ["RE-ASM-DDDDDD depends-on-x RE-STORY-AAAAAA"],
    });
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "RE-TEST-CCCCCC verifies RE-STORY-AAAAAA" }));
    await user.click(screen.getByRole("button", { name: "RE-ASM-DDDDDD depends-on-x RE-STORY-AAAAAA" }));

    expect(onSelect.mock.calls).toEqual([["RE-TEST-CCCCCC"], ["RE-ASM-DDDDDD"]]);
  });

  it("still opens a bare canonical document ID", async () => {
    const { onSelect } = renderCards({ pending: ["RE-STORY-BBBBBB"] });
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "RE-STORY-BBBBBB" }));

    expect(onSelect).toHaveBeenCalledWith("RE-STORY-BBBBBB");
  });

  it("renders malformed labels as plain text and never navigates to them", async () => {
    const malformed = [
      "RE-STORY-AAAAAA verifies",
      "not a label at all",
      "re-feat-aaaaaa refines RE-GOAL-BBBBBB",
      "RE-STORY-AAAAAA Refines RE-STORY-BBBBBB",
      "RE-STORY-AAAAAA refines RE-STORY-BBBBBB extra",
      "XXXXXXXXXX-STORY-AAAAAA refines RE-STORY-BBBBBB",
      "RE-STORY-AAAAAA refines RE-ZZZZZ!",
      "RE-AAAAAA refines RE-BBBBBB",
      "RE-FEAT-AAAAAA refines RE-BBBBBB",
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
