"""Showrunner — AI-powered video generation framework."""

__version__ = "0.1.0"

from showrunner.costs import CostEstimate, StageCostEstimate
from showrunner.events import (
    CancelToken,
    NarrationCompleted,
    PipelineCancelled,
    PipelineCancelledError,
    PipelineEvent,
    PipelineFailed,
    PlanReady,
    RenderCompleted,
    SceneCompleted,
    SceneFailed,
    SceneStarted,
    StageCompleted,
    StageStarted,
    WorkDirReady,
)
from showrunner.feedback import Feedback
from showrunner.formats.base import Format
from showrunner.pipeline import Pipeline
from showrunner.plan import Plan

__all__ = [
    "__version__",
    "Pipeline",
    "Plan",
    "Format",
    "Feedback",
    # Events (stability contract — see showrunner.events)
    "PipelineEvent",
    "StageStarted",
    "StageCompleted",
    "PlanReady",
    "WorkDirReady",
    "SceneStarted",
    "SceneCompleted",
    "SceneFailed",
    "NarrationCompleted",
    "RenderCompleted",
    "PipelineFailed",
    "PipelineCancelled",
    # Cancellation
    "CancelToken",
    "PipelineCancelledError",
    # Cost estimation
    "CostEstimate",
    "StageCostEstimate",
]
