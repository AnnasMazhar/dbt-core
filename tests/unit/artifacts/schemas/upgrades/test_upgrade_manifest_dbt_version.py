"""Tests for manifest upgrade functions.

Specifically tests GH #16133: manifest upgrade must preserve literal types
in unrendered_config to prevent false state:modified on unchanged models.
"""

from argparse import Namespace

import pytest

from dbt.artifacts.schemas.upgrades import upgrade_manifest_json_dbt_version
from dbt.flags import set_from_args


class TestUpgradeUnrenderedConfig:
    """Regression tests for GH #16133: manifest upgrade must preserve literal config types."""

    @pytest.fixture(autouse=True)
    def setup_flags(self):
        """Enable the flag that triggers the upgrade path."""
        set_from_args(Namespace(state_modified_compare_more_unrendered_values=True), {})
        yield
        set_from_args(Namespace(), {})

    def test_preserves_literal_list_type(self):
        # GH #16133: manifest upgrade must not corrupt literal list configs into strings
        # unrendered_config must be truthy (non-empty) for upgrade to run
        manifest = {
            "nodes": {
                "model.test.m": {
                    "resource_type": "model",
                    "raw_code": "{{ config(cluster_by=['id']) }}\nselect 1 as id",
                    "unrendered_config": {"materialized": "table"},
                }
            }
        }
        upgraded = upgrade_manifest_json_dbt_version(manifest)
        assert upgraded["nodes"]["model.test.m"]["unrendered_config"]["cluster_by"] == ["id"]
        assert isinstance(
            upgraded["nodes"]["model.test.m"]["unrendered_config"]["cluster_by"], list
        )

    def test_preserves_literal_dict_type(self):
        manifest = {
            "nodes": {
                "model.test.m": {
                    "resource_type": "model",
                    "raw_code": "{{ config(grants={'select': ['user']}) }}\nselect 1",
                    "unrendered_config": {"materialized": "table"},
                }
            }
        }
        upgraded = upgrade_manifest_json_dbt_version(manifest)
        assert upgraded["nodes"]["model.test.m"]["unrendered_config"]["grants"] == {
            "select": ["user"]
        }
        assert isinstance(upgraded["nodes"]["model.test.m"]["unrendered_config"]["grants"], dict)

    def test_preserves_non_str_scalars(self):
        manifest = {
            "nodes": {
                "model.test.m": {
                    "resource_type": "model",
                    "raw_code": "{{ config(version=3, enabled=True, full_refresh=none) }}\nselect 1",
                    "unrendered_config": {"materialized": "table"},
                }
            }
        }
        upgraded = upgrade_manifest_json_dbt_version(manifest)
        config = upgraded["nodes"]["model.test.m"]["unrendered_config"]
        assert config["version"] == 3
        assert isinstance(config["version"], int)
        assert config["enabled"] is True
        assert isinstance(config["enabled"], bool)
        assert config["full_refresh"] is None

    def test_expression_values_stay_strings(self):
        manifest = {
            "nodes": {
                "model.test.m": {
                    "resource_type": "model",
                    "raw_code": "{{ config(alias=target.name) }}\nselect 1",
                    "unrendered_config": {"materialized": "table"},
                }
            }
        }
        upgraded = upgrade_manifest_json_dbt_version(manifest)
        # Non-literal expressions remain strings
        assert upgraded["nodes"]["model.test.m"]["unrendered_config"]["alias"] == "target.name"
        assert isinstance(upgraded["nodes"]["model.test.m"]["unrendered_config"]["alias"], str)

    def test_list_of_dicts_bigquery_grants(self):
        # Real-world BigQuery grants pattern from GH #16133
        manifest = {
            "nodes": {
                "model.test.m": {
                    "resource_type": "model",
                    "raw_code": "{{ config(grant_access_to=[{'project': 'p', 'dataset': 'd'}]) }}\nselect 1",
                    "unrendered_config": {"materialized": "table"},
                }
            }
        }
        upgraded = upgrade_manifest_json_dbt_version(manifest)
        grant_access = upgraded["nodes"]["model.test.m"]["unrendered_config"]["grant_access_to"]
        assert grant_access == [{"project": "p", "dataset": "d"}]
        assert isinstance(grant_access, list)
        assert isinstance(grant_access[0], dict)
