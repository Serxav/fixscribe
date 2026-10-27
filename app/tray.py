"""Printable fastener tray data (task 030): pure data, no web."""

from dataclasses import dataclass

from app.schemas import Guide


@dataclass(frozen=True)
class TrayCell:
    step: int
    title: str
    kind: str
    count: int
    numbers: list[int]
    image: str | None


def tray_cells(guide: Guide) -> list[TrayCell]:
    """One cell per step that removes fasteners, in step order."""
    cells = []
    for step in guide.steps:
        screws = step.screws
        if screws is None or screws.count <= 0:
            continue
        if screws.boxes:
            numbers = sorted(box.number for box in screws.boxes)
        else:
            numbers = list(range(1, screws.count + 1))
        cells.append(
            TrayCell(
                step=step.index,
                title=step.title,
                kind=screws.kind,
                count=screws.count,
                numbers=numbers,
                image=step.overlay or step.image,
            )
        )
    return cells


def reassembly_lines(guide: Guide) -> list[str]:
    """Reassembly order with the tray cell each line takes its fasteners from."""
    if not tray_cells(guide):
        return []
    return [
        f"{item.index}. {item.instruction} (tray cell {item.source_step})"
        for item in guide.reassembly
    ]
