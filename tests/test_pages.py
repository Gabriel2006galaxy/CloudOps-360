"""Smoke test: every page renders for every role with the development seed data.

Catches template errors and dead links that unit tests could miss.
"""
import contextlib
import io
import re

import pytest

from app.models import Ticket

ROLE_LOGINS = {'admin': 'AdminPass123!', 'tech_sarah': 'TechPass123!', 'emp_jordan': 'EmpPass123!'}


@pytest.fixture
def seeded(app):
    from scripts.seed_data import seed_database
    with contextlib.redirect_stdout(io.StringIO()):
        seed_database()
    return app


@pytest.mark.parametrize('username', list(ROLE_LOGINS))
def test_all_reachable_pages_render_without_errors(seeded, username):
    client = seeded.test_client()
    resp = client.post('/auth/login', data={'username_or_email': username, 'password': ROLE_LOGINS[username]})
    assert resp.status_code == 302

    # Crawl every internal link reachable from the dashboard (one level deep, plus ticket pages)
    to_visit = ['/dashboard', '/tickets', '/notifications', '/auth/profile', '/tickets/create']
    seen = set()
    while to_visit:
        path = to_visit.pop()
        if path in seen or len(seen) > 120:
            continue
        seen.add(path)
        resp = client.get(path, follow_redirects=True)
        assert resp.status_code in (200, 403), f'{username} {path} -> {resp.status_code}'
        if resp.status_code == 200 and resp.mimetype == 'text/html':
            for href in re.findall(r'href="(/[^"#]*)"', resp.get_data(as_text=True)):
                if href.startswith(('/static', '/attachments', '/notifications/', '/admin/audit-logs/export')):
                    continue
                if href not in seen:
                    to_visit.append(href.replace('&amp;', '&'))
    assert len(seen) > 10


def test_ticket_pages_visible_to_staff(seeded):
    client = seeded.test_client()
    client.post('/auth/login', data={'username_or_email': 'admin', 'password': 'AdminPass123!'})
    for ticket in Ticket.query.all():
        assert client.get(f'/tickets/{ticket.reference_id}').status_code == 200


def test_public_pages(client):
    for path in ('/', '/auth/login', '/auth/register', '/health'):
        assert client.get(path).status_code == 200
    assert client.get('/does-not-exist').status_code == 404
