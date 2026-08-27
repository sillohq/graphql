"""``sillo_graphql.context`` — what a resolver is handed."""

from __future__ import annotations

import pytest

from sillo_graphql.context import GraphContext, ResponseHandle


class TestResponseHandle:
    def test_starts_empty(self):
        assert not ResponseHandle()

    def test_becomes_truthy_once_anything_is_asked_for(self):
        handle = ResponseHandle()
        handle.set_header("x-a", "1")
        assert handle

    def test_a_cookie_alone_makes_it_truthy(self):
        handle = ResponseHandle()
        handle.set_cookie("a", "b")
        assert handle

    def test_a_deletion_alone_makes_it_truthy(self):
        handle = ResponseHandle()
        handle.delete_cookie("a")
        assert handle

    def test_a_status_alone_makes_it_truthy(self):
        handle = ResponseHandle()
        handle.set_status(404)
        assert handle

    def test_the_first_status_is_kept_when_a_lower_one_follows(self):
        handle = ResponseHandle()
        handle.set_status(404)
        handle.set_status(200)
        assert handle.status_code == 404

    def test_a_higher_status_wins(self):
        handle = ResponseHandle()
        handle.set_status(200)
        handle.set_status(500)
        assert handle.status_code == 500

    def test_headers_are_copied_rather_than_shared(self):
        handle = ResponseHandle()
        handle.set_header("x", "1")
        headers = handle.headers
        headers["x"] = "2"
        assert handle.headers["x"] == "1"

    def test_apply_replays_everything_onto_a_response(self):
        class Fake:
            def __init__(self):
                self.headers, self.cookies, self.deleted = {}, [], []

            def set_header(self, name, value):
                self.headers[name] = value

            def set_cookie(self, *args, **kwargs):
                self.cookies.append((args, kwargs))

            def delete_cookie(self, *args, **kwargs):
                self.deleted.append(args)

        handle = ResponseHandle()
        handle.set_header("x-a", "1")
        handle.set_cookie("session", "abc", httponly=True)
        handle.delete_cookie("old")

        response = handle.apply(Fake())
        assert response.headers == {"x-a": "1"}
        assert response.cookies == [(("session", "abc"), {"httponly": True})]
        assert response.deleted == [("old",)]
