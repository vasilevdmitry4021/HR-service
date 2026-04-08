import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import type { Candidate } from "@/lib/types";

import { CandidateCard } from "./CandidateCard";

vi.mock("next/link", () => {
  return {
    default: function MockLink(props: { children: ReactNode; href: string }) {
      return <a href={props.href}>{props.children}</a>;
    },
  };
});

const baseCandidate: Candidate = {
  id: "c1",
  hh_resume_id: "hh-1",
  title: "Java Developer",
  full_name: "Иван Иванов",
  skills: ["Java", "Spring"],
  area: "Москва",
  experience_years: 4,
};

describe("CandidateCard", () => {
  it("показывает заголовок и вызывает onToggleFavorite", async () => {
    const user = userEvent.setup();
    const onToggle = vi.fn();

    render(
      <CandidateCard
        candidate={baseCandidate}
        onToggleFavorite={onToggle}
      />,
    );

    expect(screen.getByText("Java Developer")).toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: /Добавить в избранное/i }),
    );
    expect(onToggle).toHaveBeenCalledWith(baseCandidate);
  });

  it("показывает состояние избранного при переданном favoriteId", () => {
    render(
      <CandidateCard
        candidate={baseCandidate}
        favoriteId="fav-uuid"
        onToggleFavorite={() => {}}
      />,
    );
    expect(
      screen.getByRole("button", { name: /Убрать из избранного/i }),
    ).toBeInTheDocument();
  });
});
