"""Tests for the showcase static site builder."""

import json
from unittest import mock

import pytest

from redditpulse import services
from redditpulse.config import Settings, override_settings
from redditpulse.showcase import builder

from conftest import make_comment


@pytest.fixture(autouse=True)
def temp_db(tmp_path):
    override_settings(Settings(db_path=tmp_path / "showcase.db"))
    yield
    override_settings(Settings())


def _seed_topic(name, analyzed=True):
    comments = [
        make_comment(f"{name}-a", body="I love this, wonderful!", score=50,
                     created_utc=1735689600),
        make_comment(f"{name}-b", body="This is terrible.", score=3,
                     created_utc=1738368000),
    ]
    fake = mock.Mock()
    fake.search_comments.return_value = comments
    with mock.patch("redditpulse.services.search.get_fetcher", return_value=fake):
        services.search_topic(topic=name, keywords=["kw"])
    if analyzed:
        services.analyze_topic(name, sentiment_only=True)


def test_slugify():
    assert builder.slugify("AI and Privacy v2!") == "ai-and-privacy-v2"
    assert builder.slugify("***") == "topic"


def test_build_site_includes_analyzed_topics(tmp_path):
    _seed_topic("Electric Cars")
    _seed_topic("No Analysis Yet", analyzed=False)
    out = builder.build_site(output_dir=tmp_path / "site")

    index = (out / "index.html").read_text()
    assert "Electric Cars" in index
    assert "No Analysis Yet" not in index
    assert (out / ".nojekyll").exists()

    page = (out / "topics" / "electric-cars.html").read_text()
    assert '<script id="payload"' in page
    payload = json.loads(
        page.split('type="application/json">')[1].split("</script>")[0]
        .replace("<\\/", "</"))
    assert payload["analysis"]["sentiment"]["total"] == 2
    assert payload["sections"] == builder.SECTIONS
    assert payload["date_range"]["from"] <= payload["date_range"]["to"]
    assert payload["top_comments"]


def test_build_site_respects_config(tmp_path):
    _seed_topic("Shown")
    _seed_topic("Hidden")
    services.set_showcase_config("Hidden", {"enabled": False})
    services.set_showcase_config("Shown", {
        "enabled": True,
        "title": "A Custom Title",
        "description": "Hand-written intro <b>text</b>",
        "sections": ["sentiment", "top_comments"],
        "section_notes": {"sentiment": "Note about the mood."},
    })

    out = builder.build_site(output_dir=tmp_path / "site")
    index = (out / "index.html").read_text()
    assert "A Custom Title" in index
    assert "Hidden" not in index

    page = (out / "topics" / "shown.html").read_text()
    assert "A Custom Title" in page
    assert "&lt;b&gt;text&lt;/b&gt;" in page  # description is escaped
    payload = json.loads(
        page.split('type="application/json">')[1].split("</script>")[0]
        .replace("<\\/", "</"))
    assert payload["sections"] == ["sentiment", "top_comments"]
    assert payload["section_notes"]["sentiment"] == "Note about the mood."


def test_build_site_empty_db(tmp_path):
    out = builder.build_site(output_dir=tmp_path / "site")
    assert "No showcased topics yet" in (out / "index.html").read_text()
