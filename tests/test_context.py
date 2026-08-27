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


class TestGraphContext:
    def test_connection_is_the_http_context_over_http(self, http_context):
        context = GraphContext(http=http_context)
        assert context.connection is http_context

    def test_connection_is_the_socket_over_a_websocket(self):
        socket = object()
        assert GraphContext(socket=socket).connection is socket

    def test_connection_is_none_when_there_is_neither(self):
        assert GraphContext().connection is None

    def test_the_legacy_ctx_key_still_works(self, http_context):
        context = GraphContext(http=http_context)
        assert context["ctx"] is http_context

    def test_attributes_are_readable_as_keys(self, http_context):
        context = GraphContext(http=http_context)
        assert context["http"] is http_context

    def test_extra_keys_are_readable(self):
        context = GraphContext(extra={"tenant": "acme"})
        assert context["tenant"] == "acme"

    def test_an_unknown_key_raises(self):
        with pytest.raises(KeyError):
            GraphContext()["nope"]

    def test_length_and_iteration_agree(self):
        context = GraphContext(extra={"tenant": "acme"})
        assert len(context) == len(list(context))
        assert len(set(context)) == len(context)

    def test_an_extra_key_shadowing_an_attribute_is_counted_once(self):
        context = GraphContext(extra={"http": "shadow", "cost": 1})
        assert len(context) == len(set(context))

    def test_it_is_a_mapping(self, http_context):
        assert dict(GraphContext(http=http_context))["ctx"] is http_context

    def test_user_is_none_without_authentication_middleware(self, http_context):
        # `ctx.user` raises rather than answering when no middleware is
        # mounted, and a resolver should see "nobody", not a 500.
        assert GraphContext(http=http_context).user is None

    def test_user_is_none_with_no_connection_at_all(self):
        assert GraphContext().user is None

    def test_user_is_read_through_rather_than_snapshotted(self):
        class Late:
            user = None

        socket = Late()
        context = GraphContext(socket=socket)
        assert context.user is None
        socket.user = "ada"
        assert context.user == "ada"

    def test_repr_says_which_transport(self, http_context):
        assert "http" in repr(GraphContext(http=http_context))
        assert "ws" in repr(GraphContext(socket=object()))

    def test_a_dependency_cache_starts_empty(self):
        assert GraphContext().dependency_cache == {}

    def test_the_clock_starts_when_the_context_does(self):
        assert GraphContext().started > 0
