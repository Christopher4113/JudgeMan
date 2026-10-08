from pathlib import Path

from pydantic import BaseModel

# All axes are yes/no. None means the axis does not apply to that step.
# unverified_completion applies to the submit step only.
# outcome_process_mismatch is the run-level flag, stored on the last step only.
AXES = ("progress", "redundant", "risky", "unverified_completion", "outcome_process_mismatch")


class Step(BaseModel):
    index: int
    thought: str = ""
    command: str = ""  # empty means the model produced no valid command
    output: str = ""
    returncode: int | None = None
    is_submit: bool = False


class Trajectory(BaseModel):
    id: str
    task: str
    steps: list[Step]
    exit_status: str = ""
    submission: str = ""
    resolved: bool | None = None  # did the hidden tests pass
    model: str = ""


class StepLabel(BaseModel):
    trajectory_id: str
    step: int
    source: str  # "checks", "human", or a judge model name
    progress: bool | None = None
    redundant: bool | None = None
    risky: bool | None = None
    unverified_completion: bool | None = None
    outcome_process_mismatch: bool | None = None
    flags: list[str] = []
    critique: str = ""
    seconds: float | None = None  # how long a person spent on the step, or a judge call took


def applicable(traj: Trajectory, step: Step) -> tuple[str, ...]:
    """The axes that can be labeled on this step."""
    axes = ["progress", "redundant", "risky"]
    if step.is_submit:
        axes.append("unverified_completion")
    if step.index == len(traj.steps) - 1 and traj.resolved is not None:
        axes.append("outcome_process_mismatch")
    return tuple(axes)


def read_labels(path: Path) -> list[StepLabel]:
    if not path.exists():
        return []
    lines = path.read_text().splitlines()
    return [StepLabel.model_validate_json(line) for line in lines if line.strip()]


def write_labels(path: Path, labels: list[StepLabel], append: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a" if append else "w") as f:
        for label in labels:
            f.write(label.model_dump_json() + "\n")
