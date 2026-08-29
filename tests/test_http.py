"""``sillo_graphql.transport.http`` — framing, negotiation and status codes."""

from __future__ import annotations

import json

import pytest

from sillo_graphql import IDE, Transport, Uploads
from sillo_graphql.testing import GraphClient
from sillo_graphql.transport.http import (
    APPLICATION_JSON,
    GRAPHQL_RESPONSE_JSON,
    negotiate,
)

SPEC = {"accept": GRAPHQL_RESPONSE_JSON}


class TestNegotiation:
    @pytest.mark.parametrize(
        ("accept", "expected"),
        [
            (None, APPLICATION_JSON),
            ("", APPLICATION_JSON),
            ("*/*", APPLICATION_JSON),
            ("application/json", APPLICATION_JSON),
            ("text/html", APPLICATION_JSON),
            (GRAPHQL_RESPONSE_JSON, GRAPHQL_RESPONSE_JSON),
            (f"{GRAPHQL_RESPONSE_JSON};charset=utf-8", GRAPHQL_RESPONSE_JSON),
            (f"{GRAPHQL_RESPONSE_JSON}, application/json", GRAPHQL_RESPONSE_JSON),
            (f"application/json, {GRAPHQL_RESPONSE_JSON}", APPLICATION_JSON),
        ],
    )
    def test_the_legacy_type_wins_ties_and_defaults(self, accept, expected):
        assert negotiate(accept, enabled=True) == expected

    def test_it_can_be_switched_off_entirely(self):
        assert negotiate(GRAPHQL_RESPONSE_JSON, enabled=False) == APPLICATION_JSON


class TestPost:
    def test_a_query_is_answered(self, gql):
        result = gql.query("{ hello }")
        assert result.status_code == 200
        assert result.data == {"hello": "world"}

    def test_variables_and_operation_name_are_forwarded(self, gql):
        result = gql.execute(
            "query A($t: String!) { search(term: $t) } query B { hello }",
            variables={"t": "abc"},
            operation_name="A",
        )
        assert result.data == {"search": "cba"}

    def test_a_body_that_is_not_json_is_a_400(self, gql):
        response = gql._client.post(
            "/graphql",
            content=b"not json",
            headers={"content-type": "application/json"},
        )
        assert response.status_code == 400
        assert "not valid JSON" in response.json()["errors"][0]["message"]

    def test_a_body_that_is_not_an_object_is_a_400(self, gql):
        response = gql._client.post("/graphql", json="a string")
        assert response.status_code == 400

    def test_a_missing_query_is_a_400_not_a_500(self, gql):
        response = gql._client.post("/graphql", json={})
        assert response.status_code == 400
        assert response.json()["errors"][0]["extensions"]["code"] == "BAD_USER_INPUT"

    def test_an_unknown_content_type_is_a_415(self, gql):
        response = gql._client.post(
            "/graphql", content=b"x", headers={"content-type": "text/csv"}
        )
        assert response.status_code == 415

    def test_a_body_with_no_content_type_is_read_as_json(self, gql):
        response = gql._client.post(
            "/graphql", content=json.dumps({"query": "{ hello }"}).encode()
        )
        assert response.json()["data"] == {"hello": "world"}

    def test_a_graphql_body_is_the_document(self, gql):
        response = gql._client.post(
            "/graphql",
            content=b"{ hello }",
            headers={"content-type": "application/graphql"},
        )
        assert response.json()["data"] == {"hello": "world"}

    def test_graphql_bodies_can_be_refused(self, build):
        app = build(transport=Transport(graphql_content_type=False))
        with GraphClient(app) as gql:
            response = gql._client.post(
                "/graphql",
                content=b"{ hello }",
                headers={"content-type": "application/graphql"},
            )
        assert response.status_code == 415

    def test_a_form_body_is_accepted(self, gql):
        response = gql._client.post("/graphql", data={"query": "{ hello }"})
        assert response.json()["data"] == {"hello": "world"}

    def test_a_form_body_with_bad_variables_is_a_400(self, gql):
        response = gql._client.post(
            "/graphql", data={"query": "{ hello }", "variables": "{oops"}
        )
        assert response.status_code == 400

    def test_a_body_over_the_limit_is_a_413(self, build):
        with GraphClient(build(transport=Transport(max_body=64))) as gql:
            response = gql._client.post(
                "/graphql", json={"query": "{ hello }" + " " * 200}
            )
        assert response.status_code == 413

    def test_another_method_is_a_405(self, gql):
        assert gql._client.request("PUT", "/graphql").status_code == 405


class TestGet:
    def test_a_query_over_get_works(self, gql):
        assert gql.execute("{ hello }", method="GET").data == {"hello": "world"}

    def test_a_mutation_over_get_is_a_405(self, gql):
        result = gql.execute('mutation { rename(name: "x") }', method="GET")
        assert result.status_code == 405

    def test_get_queries_can_be_refused(self, build):
        with GraphClient(build(transport=Transport(get_queries=False))) as gql:
            assert gql.execute("{ hello }", method="GET").status_code == 405

    def test_a_get_with_no_query_and_no_ide_is_a_400(self, gql):
        assert gql._client.get("/graphql").status_code == 400

    def test_a_browser_gets_the_explorer_when_it_is_on(self, build):
        with GraphClient(build(ide=IDE(enabled=True))) as gql:
            response = gql.ide()
        assert response.status_code == 200
        assert "<!doctype html>" in response.text

    def test_a_browser_gets_a_400_when_the_explorer_is_off(self, gql):
        assert gql.ide().status_code == 400

    def test_a_non_browser_get_is_never_the_explorer(self, build):
        with GraphClient(build(ide=IDE(enabled=True))) as gql:
            response = gql._client.get(
                "/graphql", headers={"accept": "application/json"}
            )
        assert response.status_code == 400

    def test_variables_arrive_as_json_text(self, gql):
        result = gql.execute(
            "query ($t: String!) { search(term: $t) }",
            variables={"t": "abc"},
            method="GET",
        )
        assert result.data == {"search": "cba"}

    def test_an_extensions_only_get_is_treated_as_an_operation(self, gql):
        response = gql._client.get("/graphql", params={"extensions": "{}"})
        assert response.status_code == 400
        assert "No query" in response.json()["errors"][0]["message"]


class TestBatching:
    def test_a_batch_runs_in_order(self, gql):
        results = gql.batch("{ hello }", '{ search(term: "ab") }')
        assert [r.data for r in results] == [
            {"hello": "world"},
            {"search": "ba"},
        ]

    def test_a_batch_can_be_refused(self, build):
        with GraphClient(build(transport=Transport(batch=0))) as gql:
            response = gql._client.post("/graphql", json=[{"query": "{ hello }"}])
        assert response.status_code == 400
        assert "not accepted" in response.json()["errors"][0]["message"]

    def test_an_empty_batch_is_a_400(self, gql):
        response = gql._client.post("/graphql", json=[])
        assert response.status_code == 400

    def test_a_batch_over_the_cap_is_refused(self, build):
        with GraphClient(build(transport=Transport(batch=2))) as gql:
            response = gql._client.post("/graphql", json=[{"query": "{ hello }"}] * 3)
        assert response.status_code == 400
        assert "at most 2" in response.json()["errors"][0]["message"]

    def test_a_non_object_entry_is_reported_in_place(self, gql):
        response = gql._client.post("/graphql", json=[{"query": "{ hello }"}, 7])
        body = response.json()
        assert body[0]["data"] == {"hello": "world"}
        assert "must be an object" in body[1]["errors"][0]["message"]

    def test_the_worst_status_in_a_batch_wins(self, gql):
        response = gql._client.post(
            "/graphql", json=[{"query": "{ hello }"}, {"query": "{ nope }"}]
        )
        assert response.status_code == 400


class TestSpecMediaType:
    def test_a_successful_query_is_a_200(self, gql):
        assert gql.query("{ hello }", headers=SPEC).status_code == 200

    def test_the_response_names_the_media_type(self, gql):
        result = gql.query("{ hello }", headers=SPEC)
        assert result.headers["content-type"].startswith(GRAPHQL_RESPONSE_JSON)

    def test_a_validation_failure_is_a_400(self, gql):
        assert gql.query("{ nope }", headers=SPEC).status_code == 400

    def test_a_field_error_is_still_a_200(self, gql):
        # The operation ran; one field failed. That is not a bad request.
        result = gql.query("{ me(id: 99) }", headers=SPEC)
        assert result.status_code == 200
        assert result.errors

    def test_a_field_error_is_a_200_under_the_legacy_type_too(self, gql):
        assert gql.query("{ me(id: 99) }").status_code == 200


class TestUploads:
    def files(self, gql, *, operations, mapping, files):
        return gql._client.post(
            "/graphql",
            data={"operations": json.dumps(operations), "map": json.dumps(mapping)},
            files=files,
        )

    def test_uploads_are_refused_unless_enabled(self, gql):
        response = self.files(
            gql,
            operations={"query": "{ hello }"},
            mapping={},
            files={"0": ("a.txt", b"hi")},
        )
        assert response.status_code == 415

    def test_an_enabled_endpoint_accepts_the_operation(self, build):
        app = build(uploads=Uploads(enabled=True))
        with GraphClient(app) as gql:
            response = self.files(
                gql,
                operations={"query": "{ hello }"},
                mapping={},
                files={"0": ("a.txt", b"hi")},
            )
        assert response.json()["data"] == {"hello": "world"}

    def test_missing_operations_is_a_400(self, build):
        with GraphClient(build(uploads=Uploads(enabled=True))) as gql:
            response = gql._client.post(
                "/graphql", data={"map": "{}"}, files={"0": ("a.txt", b"hi")}
            )
        assert response.status_code == 400

    def test_operations_that_are_not_json_is_a_400(self, build):
        with GraphClient(build(uploads=Uploads(enabled=True))) as gql:
            response = gql._client.post(
                "/graphql",
                data={"operations": "{oops", "map": "{}"},
                files={"0": ("a.txt", b"hi")},
            )
        assert response.status_code == 400

    def test_operations_that_are_not_an_object_is_a_400(self, build):
        with GraphClient(build(uploads=Uploads(enabled=True))) as gql:
            response = self.files(
                gql, operations=[1], mapping={}, files={"0": ("a.txt", b"hi")}
            )
        assert response.status_code == 400

    def test_a_map_naming_an_absent_file_is_a_400(self, build):
        with GraphClient(build(uploads=Uploads(enabled=True))) as gql:
            response = self.files(
                gql,
                operations={"query": "{ hello }"},
                mapping={"7": ["variables.file"]},
                files={"0": ("a.txt", b"hi")},
            )
        assert response.status_code == 400
        assert "does not carry" in response.json()["errors"][0]["message"]

    def test_too_many_files_is_a_400(self, build):
        uploads = Uploads(enabled=True, max_files=1)
        with GraphClient(build(uploads=uploads)) as gql:
            response = self.files(
                gql,
                operations={"query": "{ hello }"},
                mapping={"0": ["variables.a"], "1": ["variables.b"]},
                files={"0": ("a.txt", b"hi"), "1": ("b.txt", b"yo")},
            )
        assert response.status_code == 400
        assert "over the limit" in response.json()["errors"][0]["message"]

    def test_a_file_over_the_size_limit_is_a_400(self, build):
        uploads = Uploads(enabled=True, max_size=4)
        with GraphClient(build(uploads=uploads)) as gql:
            response = self.files(
                gql,
                operations={"query": "{ hello }", "variables": {"file": None}},
                mapping={"0": ["variables.file"]},
                files={"0": ("a.txt", b"far too many bytes")},
            )
        assert response.status_code == 400
        assert "larger than" in response.json()["errors"][0]["message"]

    def test_a_disallowed_content_type_is_a_400(self, build):
        uploads = Uploads(enabled=True, content_types=("image/png",))
        with GraphClient(build(uploads=uploads)) as gql:
            response = self.files(
                gql,
                operations={"query": "{ hello }", "variables": {"file": None}},
                mapping={"0": ["variables.file"]},
                files={"0": ("a.txt", b"hi", "text/plain")},
            )
        assert response.status_code == 400
        assert "does not accept" in response.json()["errors"][0]["message"]

    def test_a_map_entry_that_is_not_a_list_is_a_400(self, build):
        with GraphClient(build(uploads=Uploads(enabled=True))) as gql:
            response = self.files(
                gql,
                operations={"query": "{ hello }"},
                mapping={"0": "variables.file"},
                files={"0": ("a.txt", b"hi")},
            )
        assert response.status_code == 400
        assert "list of variable paths" in response.json()["errors"][0]["message"]

    def test_a_path_the_operation_lacks_is_a_400(self, build):
        with GraphClient(build(uploads=Uploads(enabled=True))) as gql:
            response = self.files(
                gql,
                operations={"query": "{ hello }"},
                mapping={"0": ["variables.missing.deeper"]},
                files={"0": ("a.txt", b"hi")},
            )
        assert response.status_code == 400
        assert "does not have" in response.json()["errors"][0]["message"]


class TestResponseControl:
    def test_a_resolver_can_set_the_status(self, gql):
        result = gql.query("{ stamp }")
        assert result.status_code == 418

    def test_a_resolver_can_set_a_header(self, gql):
        assert gql.query("{ stamp }").headers["x-stamped"] == "yes"

    def test_a_resolver_can_set_a_cookie(self, gql):
        response = gql._client.post("/graphql", json={"query": "{ stamp }"})
        assert "seen=1" in response.headers.get("set-cookie", "")


class TestTransportUnits:
    """Paths a routed request cannot reach, driven directly."""

    def transport(self, app):
        from sillo.core.routing import Route  # noqa: F401

        return _transport_of(app)

    async def test_an_unhandled_method_is_a_405(self, app, http_context):
        from sillo.core.http import HttpContext

        ctx = HttpContext(
            {
                "type": "http",
                "method": "PATCH",
                "path": "/graphql",
                "headers": [],
                "query_string": b"",
            },
            receive=None,
            send=None,
        )
        response = await _transport_of(app).handle(ctx)
        assert response.status_code == 405

    def test_a_dict_valued_parameter_is_taken_as_is(self):
        from sillo_graphql.transport.http import _from_params

        payload = _from_params({"query": "{ x }", "variables": {"a": 1}})
        assert payload["variables"] == {"a": 1}

    def test_an_empty_variables_string_is_ignored(self):
        from sillo_graphql.transport.http import _from_params

        assert "variables" not in _from_params({"query": "{ x }", "variables": ""})

    def test_a_non_string_query_is_ignored(self):
        from sillo_graphql.transport.http import _from_params

        assert _from_params({"query": 7}) == {}


class TestSizeOf:
    def test_a_size_attribute_is_used(self):
        from sillo_graphql.transport.http import _size_of

        assert _size_of(type("F", (), {"size": 12})()) == 12

    def test_a_content_length_is_used_when_there_is_no_size(self):
        from sillo_graphql.transport.http import _size_of

        assert _size_of(type("F", (), {"content_length": 9})()) == 9

    def test_bytes_are_measured_directly(self):
        from sillo_graphql.transport.http import _size_of

        assert _size_of(type("F", (), {"file": b"abcd"})()) == 4

    def test_a_body_attribute_is_measured(self):
        from sillo_graphql.transport.http import _size_of

        assert _size_of(type("F", (), {"body": b"abc"})()) == 3

    def test_an_unmeasurable_upload_counts_as_nothing(self):
        from sillo_graphql.transport.http import _size_of

        assert _size_of(object()) == 0


class TestPlacement:
    def payload(self):
        return {
            "query": "{ hello }",
            "variables": {"input": {"file": None}, "files": [None, None]},
        }

    def test_a_file_lands_where_the_map_says(self, build):
        from sillo_graphql.policy import Uploads
        from sillo_graphql.transport.http import _attach

        payload = self.payload()
        upload = type("F", (), {"size": 3, "content_type": "text/plain"})()
        _attach(
            payload,
            {"0": ["variables.input.file"]},
            {"0": upload},
            Uploads(enabled=True),
        )
        assert payload["variables"]["input"]["file"] is upload

    def test_a_list_index_is_understood(self):
        from sillo_graphql.policy import Uploads
        from sillo_graphql.transport.http import _attach

        payload = self.payload()
        upload = type("F", (), {"size": 3, "content_type": "text/plain"})()
        _attach(
            payload, {"0": ["variables.files.1"]}, {"0": upload}, Uploads(enabled=True)
        )
        assert payload["variables"]["files"][1] is upload

    def test_one_file_can_land_in_two_places(self):
        from sillo_graphql.policy import Uploads
        from sillo_graphql.transport.http import _attach

        payload = self.payload()
        upload = type("F", (), {"size": 3, "content_type": "text/plain"})()
        _attach(
            payload,
            {"0": ["variables.input.file", "variables.files.0"]},
            {"0": upload},
            Uploads(enabled=True),
        )
        assert payload["variables"]["files"][0] is upload

    def test_an_out_of_range_index_is_reported(self):
        from sillo_graphql.errors import GraphQLError
        from sillo_graphql.policy import Uploads
        from sillo_graphql.transport.http import _attach

        payload = self.payload()
        upload = type("F", (), {"size": 3, "content_type": "text/plain"})()
        with pytest.raises(GraphQLError, match="does not have"):
            _attach(
                payload,
                {"0": ["variables.files.9"]},
                {"0": upload},
                Uploads(enabled=True),
            )

    def test_files_over_the_total_are_refused(self):
        from sillo_graphql.errors import GraphQLError
        from sillo_graphql.policy import Uploads
        from sillo_graphql.transport.http import _attach

        payload = self.payload()
        big = type("F", (), {"size": 6, "content_type": "text/plain"})()
        with pytest.raises(GraphQLError, match="total more than"):
            _attach(
                payload,
                {"0": ["variables.files.0"], "1": ["variables.files.1"]},
                {"0": big, "1": big},
                Uploads(enabled=True, max_total=8),
            )


def _transport_of(app):
    """The `HttpTransport` mounted on *app*."""
    for route in app.get_all_routes():
        handler = getattr(route, "handler", None)
        owner = getattr(handler, "__self__", None)
        if owner is not None and type(owner).__name__ == "HttpTransport":
            return owner
    raise AssertionError("no GraphQL transport on this application")
