"""
tests/unit/test_ats_scrapers.py

Unit tests for Greenhouse and Lever ATS scrapers using mocked responses.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest

from ajaa.scraper.base import SearchQuery
from ajaa.scraper.greenhouse import GreenhouseScraper
from ajaa.scraper.lever import LeverScraper


class TestGreenhouseScraper:
    def test_greenhouse_scrape_mock(self):
        mock_payload = {
            "jobs": [
                {
                    "id": 12345,
                    "title": "Staff Backend Engineer",
                    "absolute_url": "https://boards.greenhouse.io/acme/jobs/12345",
                    "location": {"name": "Remote"},
                    "content": "Python, Django, Postgres",
                    "updated_at": "2026-09-01T12:00:00Z",
                },
                {
                    "id": 12346,
                    "title": "Marketing Manager",
                    "absolute_url": "https://boards.greenhouse.io/acme/jobs/12346",
                    "location": {"name": "New York"},
                    "content": "Growth marketing",
                    "updated_at": "2026-09-01T12:00:00Z",
                },
            ]
        }

        with patch("httpx.Client.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.json.return_value = mock_payload
            mock_resp.raise_for_status.return_value = None
            mock_get.return_value = mock_resp

            scraper = GreenhouseScraper(board_tokens=["acme"])
            jobs = scraper.scrape(SearchQuery(keywords=["engineer"], max_results=10))

            assert len(jobs) == 1
            assert jobs[0].title == "Staff Backend Engineer"
            assert jobs[0].source == "greenhouse:acme"
            assert jobs[0].remote is True


class TestLeverScraper:
    def test_lever_scrape_mock(self):
        mock_payload = [
            {
                "id": "lever-1",
                "text": "Principal Infrastructure Engineer",
                "applyUrl": "https://jobs.lever.co/corp/lever-1/apply",
                "categories": {
                    "location": "San Francisco / Remote",
                    "commitment": "Full Time",
                    "workplaceType": "remote",
                },
                "description": "Kubernetes, Terraform, AWS",
                "createdAt": 1725700000000,
            },
            {
                "id": "lever-2",
                "text": "Office Assistant",
                "applyUrl": "https://jobs.lever.co/corp/lever-2/apply",
                "categories": {"location": "London", "commitment": "Part Time"},
                "description": "General office duties",
                "createdAt": 1725700000000,
            },
        ]

        with patch("httpx.Client.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.json.return_value = mock_payload
            mock_resp.raise_for_status.return_value = None
            mock_get.return_value = mock_resp

            scraper = LeverScraper(sites=["corp"])
            jobs = scraper.scrape(SearchQuery(keywords=["infrastructure"], max_results=10))

            assert len(jobs) == 1
            assert jobs[0].title == "Principal Infrastructure Engineer"
            assert jobs[0].source == "lever:corp"
            assert jobs[0].remote is True


class TestAshbyScraper:
    def test_ashby_scrape_mock(self):
        from ajaa.scraper.ashby import AshbyScraper

        mock_payload = {
            "jobs": [
                {
                    "id": "ashby-1",
                    "title": "Senior AI Researcher",
                    "jobUrl": "https://jobs.ashbyhq.com/openai/ashby-1",
                    "applyUrl": "https://jobs.ashbyhq.com/openai/ashby-1/application",
                    "locationName": "San Francisco, CA (Remote)",
                    "isRemote": True,
                    "department": "Research",
                    "team": "Alignment",
                    "employmentType": "FullTime",
                    "compensation": {
                        "compensationTierSummary": "$250,000 - $350,000",
                    },
                    "descriptionPlain": "Deep Learning, PyTorch, Multi-agent",
                    "publishedAt": "2026-09-01T12:00:00Z",
                },
                {
                    "id": "ashby-2",
                    "title": "Recruiting Coordinator",
                    "jobUrl": "https://jobs.ashbyhq.com/openai/ashby-2",
                    "locationName": "New York, NY",
                    "isRemote": False,
                    "department": "People",
                    "descriptionPlain": "Scheduling interviews",
                    "publishedAt": "2026-09-01T12:00:00Z",
                },
            ]
        }

        with patch("httpx.Client.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.json.return_value = mock_payload
            mock_resp.raise_for_status.return_value = None
            mock_get.return_value = mock_resp

            scraper = AshbyScraper(boards=["openai"])
            jobs = scraper.scrape(SearchQuery(keywords=["researcher"], max_results=10))

            assert len(jobs) == 1
            assert jobs[0].title == "Senior AI Researcher"
            assert jobs[0].source == "ashby:openai"
            assert jobs[0].salary_raw == "$250,000 - $350,000"
            assert jobs[0].remote is True