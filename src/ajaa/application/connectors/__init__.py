"""
src/ajaa/application/connectors/__init__.py

ATS application connectors registry & dispatch (PRD §10.2).
"""
from __future__ import annotations

from ajaa.application.connectors.base import (
    ApplicationConnector,
    Confirmation,
    FillOperation,
    FillPlan,
    FillReport,
    SubmitReport,
)
from ajaa.application.connectors.ashby import AshbyConnector
from ajaa.application.connectors.generic import GenericConnector
from ajaa.application.connectors.greenhouse import GreenhouseConnector
from ajaa.application.connectors.lever import LeverConnector
from ajaa.db.models import Job


def get_connector(job: Job) -> ApplicationConnector:
    """
    Select the appropriate ATS application connector for a job posting.
    """
    greenhouse = GreenhouseConnector()
    if greenhouse.matches(job):
        return greenhouse

    lever = LeverConnector()
    if lever.matches(job):
        return lever

    ashby = AshbyConnector()
    if ashby.matches(job):
        return ashby

    return GenericConnector()


__all__ = [
    "ApplicationConnector",
    "AshbyConnector",
    "Confirmation",
    "FillOperation",
    "FillPlan",
    "FillReport",
    "GenericConnector",
    "GreenhouseConnector",
    "LeverConnector",
    "SubmitReport",
    "get_connector",
]
