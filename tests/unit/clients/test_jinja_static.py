import pytest

from dbt.artifacts.resources import RefArgs
from dbt.clients.jinja_static import (
    statically_extract_has_name_this,
    statically_extract_macro_calls,
    statically_parse_ref_or_source,
    statically_parse_unrendered_config,
)
from dbt.context.base import generate_base_context
from dbt.exceptions import ParsingError


@pytest.mark.parametrize(
    "macro_string,expected_possible_macro_calls",
    [
        (
            "{% macro parent_macro() %} {% do return(nested_macro()) %} {% endmacro %}",
            ["nested_macro"],
        ),
        (
            "{% macro lr_macro() %} {{ return(load_result('relations').table) }} {% endmacro %}",
            ["load_result"],
        ),
        (
            "{% macro get_snapshot_unique_id() -%} {{ return(adapter.dispatch('get_snapshot_unique_id')()) }} {%- endmacro %}",
            ["get_snapshot_unique_id"],
        ),
        (
            "{% macro get_columns_in_query(select_sql) -%} {{ return(adapter.dispatch('get_columns_in_query')(select_sql)) }} {% endmacro %}",
            ["get_columns_in_query"],
        ),
        (
            """{% macro test_mutually_exclusive_ranges(model) %}
            with base as (
                select {{ get_snapshot_unique_id() }} as dbt_unique_id,
                *
                from {{ model }} )
            {% endmacro %}""",
            ["get_snapshot_unique_id"],
        ),
        (
            "{% macro test_my_test(model) %} select {{ current_timestamp_backcompat() }} {% endmacro %}",
            ["current_timestamp_backcompat"],
        ),
        (
            "{% macro some_test(model) -%} {{ return(adapter.dispatch('test_some_kind4', 'foo_utils4')) }} {%- endmacro %}",
            ["test_some_kind4", "foo_utils4.test_some_kind4"],
        ),
        (
            "{% macro some_test(model) -%} {{ return(adapter.dispatch('test_some_kind5', macro_namespace = 'foo_utils5')) }} {%- endmacro %}",
            ["test_some_kind5", "foo_utils5.test_some_kind5"],
        ),
    ],
)
def test_extract_macro_calls(macro_string, expected_possible_macro_calls):
    cli_vars = {"local_utils_dispatch_list": ["foo_utils4"]}
    ctx = generate_base_context(cli_vars)

    possible_macro_calls = statically_extract_macro_calls(macro_string, ctx)
    assert possible_macro_calls == expected_possible_macro_calls


class TestStaticallyParseRefOrSource:
    def test_invalid_expression(self):
        with pytest.raises(ParsingError):
            statically_parse_ref_or_source("invalid")

    @pytest.mark.parametrize(
        "expression,expected_ref_or_source",
        [
            ("ref('model')", RefArgs(name="model")),
            ("ref('package','model')", RefArgs(name="model", package="package")),
            ("ref('model',v=3)", RefArgs(name="model", version=3)),
            ("ref('package','model',v=3)", RefArgs(name="model", package="package", version=3)),
            ("source('schema', 'table')", ["schema", "table"]),
        ],
    )
    def test_valid_ref_expression(self, expression, expected_ref_or_source):
        ref_or_source = statically_parse_ref_or_source(expression)
        assert ref_or_source == expected_ref_or_source


class TestStaticallyParseUnrenderedConfig:
    @pytest.mark.parametrize(
        "expression,expected_unrendered_config",
        [
            # plain string — returned without quotes at the top level
            (
                "{{ config(materialized='view') }}",
                {"materialized": "view"},
            ),
            (
                '{{ config(materialized="view") }}',
                {"materialized": "view"},
            ),
            # multiple kwargs — bool is now a real bool
            (
                "{{ config(materialized='view', enabled=True) }}",
                {
                    "materialized": "view",
                    "enabled": True,
                },
            ),
            # macro call — string args keep repr() quoting
            (
                "{{ config(materialized=env_var('test')) }}",
                {"materialized": "env_var('test')"},
            ),
            # nested keyword arg in macro call
            (
                "{{ config(materialized=env_var('test', default='default')) }}",
                {"materialized": "env_var('test', default='default')"},
            ),
            # doubly nested macro calls
            (
                "{{ config(materialized=env_var('test', default=env_var('default'))) }}",
                {"materialized": "env_var('test', default=env_var('default'))"},
            ),
            # var() call
            (
                "{{ config(enabled=var('is_enabled')) }}",
                {"enabled": "var('is_enabled')"},
            ),
            # integer constant — now returns real int
            (
                "{{ config(hours_to_expiration=24) }}",
                {"hours_to_expiration": 24},
            ),
            # None / Jinja2 `none` — now returns real None
            (
                "{{ config(full_refresh=none) }}",
                {"full_refresh": None},
            ),
            # list literal — now returns real list
            (
                "{{ config(tags=['t1', 't2']) }}",
                {"tags": ["t1", "t2"]},
            ),
            # dict literal — now returns real dict
            (
                "{{ config(meta={'owner': 'alice'}) }}",
                {"meta": {"owner": "alice"}},
            ),
            # attribute access (expression — stays string)
            (
                "{{ config(alias=target.name) }}",
                {"alias": "target.name"},
            ),
            # comparison expression (stays string)
            (
                "{{ config(full_refresh=target.name == 'prod') }}",
                {"full_refresh": "target.name == 'prod'"},
            ),
            # ~ string concatenation (expression — stays string)
            (
                "{{ config(alias='prefix_' ~ target.schema) }}",
                {"alias": "'prefix_' ~ target.schema"},
            ),
            # not operator (expression — stays string)
            (
                "{{ config(enabled=not true) }}",
                {"enabled": "not True"},
            ),
            # config call with surrounding SQL
            (
                "{{ config(materialized='table') }}\nselect 1 as id",
                {"materialized": "table"},
            ),
            # empty config call
            (
                "{{ config() }}",
                {},
            ),
            # False boolean — now returns real bool
            (
                "{{ config(enabled=false) }}",
                {"enabled": False},
            ),
            # float constant — now returns real float
            (
                "{{ config(some_ratio=0.5) }}",
                {"some_ratio": 0.5},
            ),
            # negative number (Neg node) — expression, stays string
            (
                "{{ config(hours_to_expiration=-1) }}",
                {"hours_to_expiration": "-1"},
            ),
            # != comparison (stays string)
            (
                "{{ config(full_refresh=target.name != 'prod') }}",
                {"full_refresh": "target.name != 'prod'"},
            ),
            # in operator with list (expression — stays string)
            (
                "{{ config(enabled=target.name in ['prod', 'staging']) }}",
                {"enabled": "target.name in ['prod', 'staging']"},
            ),
            # and operator (expression — stays string)
            (
                "{{ config(enabled=var('x') and true) }}",
                {"enabled": "var('x') and True"},
            ),
            # or operator (expression — stays string)
            (
                "{{ config(enabled=var('x') or false) }}",
                {"enabled": "var('x') or False"},
            ),
            # list of dicts (BigQuery grants pattern) — now returns real list of dicts
            (
                "{{ config(grant_access_to=[{'project': 'p', 'dataset': 'd'}]) }}",
                {"grant_access_to": [{"project": "p", "dataset": "d"}]},
            ),
            # getitem access (expression — stays string)
            (
                "{{ config(alias=var('aliases')['my_model']) }}",
                {"alias": "var('aliases')['my_model']"},
            ),
        ],
    )
    def test_statically_parse_unrendered_config(self, expression, expected_unrendered_config):
        unrendered_config = statically_parse_unrendered_config(expression)
        assert unrendered_config == expected_unrendered_config

    @pytest.mark.parametrize(
        "expression",
        [
            "select 1 as id",
            "{{ ref('my_model') }}",
            "{% set x = 1 %}",
        ],
    )
    def test_statically_parse_unrendered_config_no_config_call(self, expression):
        assert statically_parse_unrendered_config(expression) is None


class TestStaticallyParseUnrenderedConfigLiteralTypes:
    """Regression tests for GH #16133: literal config values must preserve their real type."""

    def test_preserves_literal_list(self):
        # GH #16133: literal list config values must keep their real type so
        # state:modified does not flag unchanged models
        result = statically_parse_unrendered_config(
            "{{ config(cluster_by=['id']) }}\nselect 1 as id"
        )
        assert result == {"cluster_by": ["id"]}
        assert isinstance(result["cluster_by"], list)

    def test_preserves_literal_dict(self):
        result = statically_parse_unrendered_config(
            "{{ config(grants={'select': ['user']}) }}\nselect 1 as id"
        )
        assert result == {"grants": {"select": ["user"]}}
        assert isinstance(result["grants"], dict)

    def test_preserves_non_str_scalar_int(self):
        result = statically_parse_unrendered_config("{{ config(version=3) }}\nselect 1 as id")
        assert result == {"version": 3}
        assert isinstance(result["version"], int)

    def test_preserves_non_str_scalar_bool(self):
        result = statically_parse_unrendered_config("{{ config(enabled=True) }}")
        assert result == {"enabled": True}
        assert isinstance(result["enabled"], bool)

    def test_preserves_non_str_scalar_none(self):
        result = statically_parse_unrendered_config("{{ config(full_refresh=none) }}")
        assert result == {"full_refresh": None}
        assert result["full_refresh"] is None

    def test_preserves_list_of_dicts(self):
        # BigQuery grants pattern
        result = statically_parse_unrendered_config(
            "{{ config(grant_access_to=[{'project': 'p', 'dataset': 'd'}]) }}"
        )
        assert result == {"grant_access_to": [{"project": "p", "dataset": "d"}]}
        assert isinstance(result["grant_access_to"], list)
        assert isinstance(result["grant_access_to"][0], dict)

    def test_preserves_nested_list_in_dict(self):
        result = statically_parse_unrendered_config("{{ config(meta={'tags': ['a', 'b']}) }}")
        assert result == {"meta": {"tags": ["a", "b"]}}
        assert isinstance(result["meta"]["tags"], list)

    def test_mixed_literal_expression_stays_string(self):
        # List containing a var() call must remain a string
        result = statically_parse_unrendered_config(
            "{{ config(cluster_by=['id', var('extra')]) }}"
        )
        assert result == {"cluster_by": "['id', var('extra')]"}
        assert isinstance(result["cluster_by"], str)


@pytest.mark.parametrize(
    "raw_code,expected_result",
    [
        ("{{ this }}", True),
        ("{{ this.variable }}", True),
        ("{{ log(this) }}", True),
        ("{{ some_other_this }}", False),
        ("this", False),
        ("{{ some_object.this }}", False),
    ],
)
def test_statically_extract_has_name_this(raw_code: str, expected_result: bool) -> None:
    assert statically_extract_has_name_this(raw_code) == expected_result
