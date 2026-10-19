import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import SearchSelect, { filterOptions } from "./SearchSelect";

afterEach(cleanup);

const OPTIONS = [
  { id: "1", label: "Consultation, general (RM 30.00)" },
  { id: "2", label: "Consultation, specialist (RM 80.00)" },
  { id: "3", label: "Blood test, full count (RM 25.00)" },
  { id: "4", label: "Chest X-ray (RM 60.00)" },
];

describe("filterOptions", () => {
  it("narrows with every extra word and ignores case", () => {
    expect(filterOptions(OPTIONS, "")).toHaveLength(4);
    expect(filterOptions(OPTIONS, "cons")).toHaveLength(2);
    expect(filterOptions(OPTIONS, "CONS spec").map((o) => o.id)).toEqual(["2"]);
    expect(filterOptions(OPTIONS, "zzz")).toEqual([]);
  });
  it("puts labels that start with the text first", () => {
    expect(filterOptions(OPTIONS, "chest")[0].id).toBe("4");
    const opts = [{ id: "a", label: "Full blood count" }, { id: "b", label: "Blood test" }];
    expect(filterOptions(opts, "blood")[0].id).toBe("b");
  });
});

function Harness({ onPick }) {
  const [v, setV] = useState("");
  return <SearchSelect id="it" options={OPTIONS} value={v} onChange={(x) => { setV(x); onPick(x); }} />;
}

describe("SearchSelect", () => {
  it("narrows the list as you type and picks with a click", () => {
    const onPick = vi.fn();
    render(<Harness onPick={onPick} />);
    const box = screen.getByRole("combobox");
    fireEvent.focus(box);
    expect(screen.getAllByRole("option")).toHaveLength(4);
    fireEvent.change(box, { target: { value: "cons" } });
    expect(screen.getAllByRole("option")).toHaveLength(2);
    fireEvent.change(box, { target: { value: "cons spec" } });
    expect(screen.getAllByRole("option")).toHaveLength(1);
    fireEvent.mouseDown(screen.getByRole("option"));
    expect(onPick).toHaveBeenLastCalledWith("2");
    expect(box.value).toBe("Consultation, specialist (RM 80.00)");
  });

  it("picks with the keyboard and clears the pick when you type again", () => {
    const onPick = vi.fn();
    render(<Harness onPick={onPick} />);
    const box = screen.getByRole("combobox");
    fireEvent.change(box, { target: { value: "x-ray" } });
    fireEvent.keyDown(box, { key: "Enter" });
    expect(onPick).toHaveBeenLastCalledWith("4");
    fireEvent.change(box, { target: { value: "Chest X-ra" } });
    expect(onPick).toHaveBeenLastCalledWith("");
  });

  it("says so when nothing matches", () => {
    render(<Harness onPick={() => {}} />);
    const box = screen.getByRole("combobox");
    fireEvent.change(box, { target: { value: "qqq" } });
    expect(screen.getByText(/No match/)).toBeTruthy();
  });
});
