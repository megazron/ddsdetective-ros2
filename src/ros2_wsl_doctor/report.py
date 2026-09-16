"""Findings and how they are printed. No colour, no dependencies."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import Enum


class Status(str, Enum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    SKIP = "SKIP"
    INFO = "INFO"


@dataclass
class Finding:
    check: str
    status: Status
    finding: str
    fix: str = ""
    details: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        return d


def worst(findings: list[Finding]) -> Status:
    order = [Status.FAIL, Status.WARN, Status.PASS, Status.INFO, Status.SKIP]
    for s in order:
        if any(f.status == s for f in findings):
            return s
    return Status.SKIP


def exit_code(findings: list[Finding]) -> int:
    return 1 if any(f.status == Status.FAIL for f in findings) else 0


def render_table(findings: list[Finding], verbose: bool = True) -> str:
    """A plain-text table: CHECK | STATUS | FINDING, fixes underneath."""
    if not findings:
        return "no findings"
    cw = max(len("check"), max(len(f.check) for f in findings))
    lines = []
    head = f"{'CHECK':<{cw}}  {'STATUS':<6}  FINDING"
    lines.append(head)
    lines.append("-" * len(head) + "-" * 30)
    for f in findings:
        lines.append(f"{f.check:<{cw}}  {f.status.value:<6}  {f.finding}")
        if f.fix:
            lines.append(f"{'':<{cw}}  {'':<6}  fix: {f.fix}")
        if verbose:
            for d in f.details:
                lines.append(f"{'':<{cw}}  {'':<6}    {d}")
    counts = {}
    for f in findings:
        counts[f.status.value] = counts.get(f.status.value, 0) + 1
    summary = ", ".join(f"{k} {v}" for k, v in sorted(counts.items()))
    lines.append("")
    lines.append(f"overall: {worst(findings).value}  ({summary})")
    return "\n".join(lines)


def render_json(findings: list[Finding]) -> str:
    return json.dumps({"overall": worst(findings).value,
                       "findings": [f.to_dict() for f in findings]}, indent=2)
