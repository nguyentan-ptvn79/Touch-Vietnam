from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DashboardHeading:
    eyebrow_key: str
    title_key: str


@dataclass(frozen=True)
class DashboardBlock:
    key: str
    template: str
    title_key: str


@dataclass(frozen=True)
class DashboardRow:
    section_class: str
    container_class: str
    blocks: tuple[DashboardBlock, ...]
    heading: DashboardHeading | None = None


def build_dashboard_layout() -> list[DashboardRow]:
    return [
        DashboardRow(
            section_class="section-block",
            container_class="summary-grid",
            heading=DashboardHeading(
                eyebrow_key="dashboard_eyebrow",
                title_key="dashboard_title",
            ),
            blocks=(
                DashboardBlock(
                    key="metrics",
                    template="dashboard_sections/metrics.html",
                    title_key="dashboard_title",
                ),
            ),
        ),
        DashboardRow(
            section_class="section-block",
            container_class="two-column",
            blocks=(
                DashboardBlock(
                    key="saved_trips",
                    template="dashboard_sections/saved_trips.html",
                    title_key="dashboard_saved_trips_title",
                ),
                DashboardBlock(
                    key="expenses",
                    template="dashboard_sections/expenses.html",
                    title_key="dashboard_expense_title",
                ),
            ),
        ),
        DashboardRow(
            section_class="section-block",
            container_class="feature-grid",
            blocks=(
                DashboardBlock(
                    key="bookings",
                    template="dashboard_sections/bookings.html",
                    title_key="dashboard_bookings_title",
                ),
                DashboardBlock(
                    key="top_places",
                    template="dashboard_sections/top_places.html",
                    title_key="dashboard_top_places_title",
                ),
                DashboardBlock(
                    key="settings",
                    template="dashboard_sections/settings.html",
                    title_key="dashboard_settings_title",
                ),
            ),
        ),
        DashboardRow(
            section_class="section-block",
            container_class="two-column",
            blocks=(
                DashboardBlock(
                    key="ar",
                    template="dashboard_sections/ar.html",
                    title_key="dashboard_ar_title",
                ),
                DashboardBlock(
                    key="offline",
                    template="dashboard_sections/offline.html",
                    title_key="dashboard_offline_title",
                ),
            ),
        ),
        DashboardRow(
            section_class="section-block",
            container_class="feature-grid",
            heading=DashboardHeading(
                eyebrow_key="dashboard_upgrade_eyebrow",
                title_key="dashboard_upgrade_title",
            ),
            blocks=(
                DashboardBlock(
                    key="upgrades",
                    template="dashboard_sections/upgrades.html",
                    title_key="dashboard_upgrade_title",
                ),
            ),
        ),
    ]


def get_dashboard_blocks(layout: list[DashboardRow]) -> list[DashboardBlock]:
    seen_keys: set[str] = set()
    blocks: list[DashboardBlock] = []
    for row in layout:
        for block in row.blocks:
            if block.key in seen_keys:
                continue
            seen_keys.add(block.key)
            blocks.append(block)
    return blocks


def filter_dashboard_layout(
    layout: list[DashboardRow],
    visible_keys: set[str],
) -> list[DashboardRow]:
    filtered_rows: list[DashboardRow] = []
    for row in layout:
        visible_blocks = tuple(block for block in row.blocks if block.key in visible_keys)
        if not visible_blocks:
            continue
        filtered_rows.append(
            DashboardRow(
                section_class=row.section_class,
                container_class=row.container_class,
                blocks=visible_blocks,
                heading=row.heading,
            )
        )
    return filtered_rows
