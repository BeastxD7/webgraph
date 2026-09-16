"""Site report: what a site shows people, what it shows machines, and how ready it is for
AI agents -- from the measurements the engine already makes. See `report.build`."""

from webgraph.report.bots import BOTS, BotPolicy, WellKnownBot, declared_policies
from webgraph.report.build import (
    LlmsFile,
    MeasuredHow,
    RobotsReport,
    SiteReport,
    build_site_report,
)
from webgraph.report.pages import PageReport
from webgraph.report.score import Finding, SiteScore, SubScore
from webgraph.report.signals import GROUPS, Signal, Signals, collect_signals
from webgraph.report.stack import StackEntry

__all__ = [
    "BOTS",
    "GROUPS",
    "BotPolicy",
    "Finding",
    "LlmsFile",
    "MeasuredHow",
    "PageReport",
    "RobotsReport",
    "Signal",
    "Signals",
    "SiteReport",
    "SiteScore",
    "StackEntry",
    "SubScore",
    "WellKnownBot",
    "build_site_report",
    "collect_signals",
    "declared_policies",
]
