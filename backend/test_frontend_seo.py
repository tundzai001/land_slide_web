import asyncio
import json
from pathlib import Path
from xml.etree import ElementTree

from app.routers import frontend


def test_built_public_shells_have_consistent_absolute_metadata():
    index = Path(frontend.FRONTEND_DIR, "index.html").read_text(encoding="utf-8")
    map_shell = Path(frontend.FRONTEND_DIR, "map.html").read_text(encoding="utf-8")
    private = Path(frontend.FRONTEND_DIR, "app.html").read_text(encoding="utf-8")

    assert '<link rel="canonical" href="https://monitoring.aitogy.com/">' in index
    assert '<link rel="canonical" href="https://monitoring.aitogy.com/map">' in map_shell
    assert 'property="og:url" content="https://monitoring.aitogy.com/' in index
    assert 'property="og:url" content="https://monitoring.aitogy.com/map"' in map_shell
    assert 'content="noindex, noarchive"' in private
    assert "react.production.min.js" not in index
    assert "ReactDOM" not in index

    structured = index.split('<script type="application/ld+json">', 1)[1].split("</script>", 1)[0]
    assert json.loads(structured)["@context"] == "https://schema.org"


def test_sitemap_only_contains_public_indexable_routes():
    response = asyncio.run(frontend.sitemap_xml())
    document = ElementTree.fromstring(response.body)
    locations = [node.text for node in document.findall("{*}url/{*}loc")]
    assert locations == ["https://monitoring.aitogy.com/", "https://monitoring.aitogy.com/map"]


def test_private_shells_send_x_robots_tag():
    response = asyncio.run(frontend.read_login())
    assert response.headers["x-robots-tag"] == "noindex, noarchive"
    response = asyncio.run(frontend.read_app())
    assert response.headers["x-robots-tag"] == "noindex, noarchive"
