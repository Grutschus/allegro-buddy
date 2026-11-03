"""Tests for GPU type parsing, normalization, and allocation tracking.

GPU gres string formats are cluster-specific and change between Slurm versions
and hardware generations — these tests guard against silent regressions.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from rich.console import Console
from slurm_records import node_dict

from allegro_buddy.core import (
    add_gpu_type_counts,
    canonical_gpu_type,
    collect_display_gpu_types,
    format_gpu_type_header,
    gpu_type_label,
    infer_gpu_type_from_features,
    infer_node_gpu_type,
    node_gpu_type_counts,
    parse_gpu_ids,
    parse_gpu_type_counts,
    parse_index_blob,
    parse_node_gpu_types,
)
from allegro_buddy.handlers import resources

# ---------------------------------------------------------------------------
# canonical_gpu_type — normalizes raw GPU type strings to canonical form
# ---------------------------------------------------------------------------


class TestCanonicalGpuType:
    def test_a5000_synonyms_all_resolve(self):
        for variant in ('a5000', 'rtx_a5000', 'RTX-A5000'):
            assert canonical_gpu_type(variant) == 'rtx_a5000', f'failed for: {variant}'

    def test_gtx1080_synonyms_all_resolve(self):
        for variant in ('gtx1080', 'gtx_1080ti', 'GTX-1080ti', 'GTX1080ti'):
            assert canonical_gpu_type(variant) == 'gtx_1080ti', f'failed for: {variant}'

    def test_v100_synonyms(self):
        assert canonical_gpu_type('tesla_v100') == 'v100'

    def test_a100_synonyms(self):
        assert canonical_gpu_type('tesla_a100') == 'a100'
        assert canonical_gpu_type('nvidia_a100') == 'a100'

    def test_h100_synonyms(self):
        assert canonical_gpu_type('nvidia_h100') == 'h100'

    def test_unknown_type_lowercased_and_normalized(self):
        assert canonical_gpu_type('H200') == 'h200'
        assert canonical_gpu_type('L40S') == 'l40s'

    def test_none_returns_generic(self):
        assert canonical_gpu_type(None) == 'generic'

    def test_empty_string_returns_generic(self):
        assert canonical_gpu_type('') == 'generic'

    def test_special_chars_normalized_to_underscore(self):
        result = canonical_gpu_type('RTX-A5000')
        # RTX-A5000 normalizes to rtx_a5000 via synonym lookup
        assert result == 'rtx_a5000'

    def test_type_with_spaces_normalized(self):
        # Spaces become underscores, then lowercased
        result = canonical_gpu_type('RTX A5000')
        assert result == 'rtx_a5000'


# ---------------------------------------------------------------------------
# gpu_type_label — human-readable display labels
# ---------------------------------------------------------------------------


class TestGpuTypeLabel:
    @pytest.mark.parametrize(
        'gpu_type,expected',
        [
            ('rtx_a5000', 'A5000'),
            ('gtx_1080ti', 'GTX1080'),
            ('a100', 'A100'),
            ('h100', 'H100'),
            ('h200', 'H200'),
            ('v100', 'V100'),
            ('l40s', 'L40S'),
            ('generic', 'GPU'),
        ],
    )
    def test_known_types(self, gpu_type: str, expected: str):
        assert gpu_type_label(gpu_type) == expected

    def test_unknown_type_uppercased_underscores_removed(self):
        result = gpu_type_label('my_custom_gpu')
        assert result == 'MYCUSTOMGPU'


# ---------------------------------------------------------------------------
# parse_gpu_type_counts — parses gres/TRES GPU specs
# ---------------------------------------------------------------------------


class TestParseGpuTypeCounts:
    def test_simple_untyped_gpu(self):
        assert parse_gpu_type_counts('gpu:2') == {'generic': 2}

    def test_typed_gpu(self):
        assert parse_gpu_type_counts('gpu:rtx_a5000:4') == {'rtx_a5000': 4}

    def test_a5000_synonym_normalized(self):
        result = parse_gpu_type_counts('gpu:a5000:4')
        assert result == {'rtx_a5000': 4}

    def test_multiple_types_comma_separated(self):
        result = parse_gpu_type_counts('gpu:a100:2,gpu:h100:1')
        assert result['a100'] == 2
        assert result['h100'] == 1

    def test_none_returns_empty(self):
        assert parse_gpu_type_counts(None) == {}
        assert parse_gpu_type_counts('') == {}

    def test_no_gpu_in_spec(self):
        assert parse_gpu_type_counts('cpu:8') == {}

    def test_gres_prefix(self):
        assert parse_gpu_type_counts('gres/gpu:rtx_a5000:4') == {'rtx_a5000': 4}

    def test_with_idx_meta(self):
        # scontrol shows gpu:a5000:4(IDX:0-3) for GresUsed
        result = parse_gpu_type_counts('gpu:a5000:4(IDX:0-3)')
        assert result == {'rtx_a5000': 4}

    def test_tres_per_node_format(self):
        # TresPerNode field in scontrol job output
        result = parse_gpu_type_counts('gres/gpu:2')
        assert result == {'generic': 2}

    def test_accumulates_same_type(self):
        # If the same type appears twice, counts add up
        result = parse_gpu_type_counts('gpu:a100:2 gpu:a100:1')
        assert result == {'a100': 3}


# ---------------------------------------------------------------------------
# parse_index_blob — parses IDX ranges like "0-3,5,7-8"
# ---------------------------------------------------------------------------


class TestParseIndexBlob:
    def test_single_index(self):
        assert parse_index_blob('3') == [3]

    def test_range(self):
        assert parse_index_blob('0-3') == [0, 1, 2, 3]

    def test_comma_separated(self):
        assert parse_index_blob('0,2,4') == [0, 2, 4]

    def test_mixed_range_and_singles(self):
        assert parse_index_blob('0-2,5,7-8') == [0, 1, 2, 5, 7, 8]

    def test_empty_string_returns_empty(self):
        assert parse_index_blob('') == []

    def test_invalid_tokens_skipped(self):
        result = parse_index_blob('0,abc,2')
        assert 0 in result
        assert 2 in result


# ---------------------------------------------------------------------------
# parse_gpu_ids — extracts GPU indices from IDX: blobs
# ---------------------------------------------------------------------------


class TestParseGpuIds:
    def test_comma_separated_idx(self):
        assert parse_gpu_ids('gpu:a5000:2(IDX:0,1)') == [0, 1]

    def test_range_idx(self):
        assert parse_gpu_ids('gpu:a5000:4(IDX:0-3)') == [0, 1, 2, 3]

    def test_no_idx_returns_empty(self):
        assert parse_gpu_ids('gpu:a5000:4') == []

    def test_none_returns_empty(self):
        assert parse_gpu_ids(None) == []
        assert parse_gpu_ids('') == []

    def test_deduplicated_and_sorted(self):
        result = parse_gpu_ids('gpu:a5000:2(IDX:1,0)')
        assert result == [0, 1]


# ---------------------------------------------------------------------------
# parse_node_gpu_types — maps GPU slot indices to type names
# ---------------------------------------------------------------------------


class TestParseNodeGpuTypes:
    def test_untyped_gpus_all_generic(self):
        result = parse_node_gpu_types('gpu:4')
        assert set(result.values()) == {'generic'}
        assert len(result) == 4

    def test_typed_gpus_with_idx(self):
        result = parse_node_gpu_types('gpu:a5000:4(IDX:0-3)')
        assert result == {0: 'rtx_a5000', 1: 'rtx_a5000', 2: 'rtx_a5000', 3: 'rtx_a5000'}

    def test_mixed_types_with_idx(self):
        result = parse_node_gpu_types('gpu:a100:2(IDX:0-1),gpu:h100:2(IDX:2-3)')
        assert result[0] == 'a100'
        assert result[1] == 'a100'
        assert result[2] == 'h100'
        assert result[3] == 'h100'

    def test_socket_list_is_not_gpu_indices(self):
        # S:0-1 is the CPU socket affinity, not GPU ids.
        result = parse_node_gpu_types('gpu:a100:4(S:0-1)')
        assert result == {0: 'a100', 1: 'a100', 2: 'a100', 3: 'a100'}

    def test_none_returns_empty(self):
        assert parse_node_gpu_types(None) == {}
        assert parse_node_gpu_types('') == {}


# ---------------------------------------------------------------------------
# infer_gpu_type_from_features — guesses GPU type from node feature strings
# ---------------------------------------------------------------------------


class TestInferGpuTypeFromFeatures:
    def test_a5000_in_features(self):
        result = infer_gpu_type_from_features('a5000,rtx,nvlink,gpu4')
        assert result == 'rtx_a5000'

    def test_gtx1080_in_features(self):
        result = infer_gpu_type_from_features('gtx1080,cuda,pcie')
        assert result == 'gtx_1080ti'

    def test_a100_in_features(self):
        result = infer_gpu_type_from_features('a100,nvlink,hbm2e')
        assert result == 'a100'

    def test_h100_in_features(self):
        result = infer_gpu_type_from_features('h100,nvlink,hbm3')
        assert result == 'h100'

    def test_no_gpu_hints_returns_none(self):
        result = infer_gpu_type_from_features('infiniband,ib,opa')
        assert result is None

    def test_none_returns_none(self):
        assert infer_gpu_type_from_features(None) is None

    def test_empty_string_returns_none(self):
        assert infer_gpu_type_from_features('') is None

    def test_null_literal_returns_none(self):
        assert infer_gpu_type_from_features('(null)') is None
        assert infer_gpu_type_from_features('N/A') is None


# ---------------------------------------------------------------------------
# infer_node_gpu_type — picks from node fields
# ---------------------------------------------------------------------------


class TestInferNodeGpuType:
    def test_from_active_features(self):
        node = {
            'ActiveFeatures': 'a5000,rtx,nvlink',
            'AvailableFeatures': '',
            'Features': '',
        }
        assert infer_node_gpu_type(node) == 'rtx_a5000'

    def test_falls_through_to_available_features(self):
        node = {
            'ActiveFeatures': 'infiniband',
            'AvailableFeatures': 'a100,nvlink',
            'Features': '',
        }
        assert infer_node_gpu_type(node) == 'a100'

    def test_no_gpu_hints_anywhere_returns_none(self):
        node = {
            'ActiveFeatures': 'infiniband',
            'AvailableFeatures': 'ib',
            'Features': 'storage',
        }
        assert infer_node_gpu_type(node) is None

    def test_empty_node_returns_none(self):
        assert infer_node_gpu_type({}) is None


# ---------------------------------------------------------------------------
# node_gpu_type_counts — extracts GPU count by type from a node dict
# ---------------------------------------------------------------------------


class TestNodeGpuTypeCounts:
    def test_typed_gres(self):
        node = {'Gres': 'gpu:rtx_a5000:4', 'ActiveFeatures': ''}
        assert node_gpu_type_counts(node) == {'rtx_a5000': 4}

    def test_generic_gres_resolved_via_features(self):
        node = {'Gres': 'gpu:4', 'ActiveFeatures': 'a5000,rtx,nvlink'}
        result = node_gpu_type_counts(node)
        assert result == {'rtx_a5000': 4}

    def test_no_gpu_gres_returns_empty(self):
        node = {'Gres': '(null)', 'ActiveFeatures': ''}
        assert node_gpu_type_counts(node) == {}

    def test_missing_gres_returns_empty(self):
        assert node_gpu_type_counts({}) == {}

    def test_multiple_types(self):
        node = {'Gres': 'gpu:a100:2,gpu:h100:2', 'ActiveFeatures': ''}
        result = node_gpu_type_counts(node)
        assert result.get('a100') == 2
        assert result.get('h100') == 2


# ---------------------------------------------------------------------------
# add_gpu_type_counts — in-place merge helper
# ---------------------------------------------------------------------------


class TestAddGpuTypeCounts:
    def test_merges_overlapping_types(self):
        target = {'a100': 2}
        add_gpu_type_counts(target, {'a100': 1, 'h100': 3})
        assert target == {'a100': 3, 'h100': 3}

    def test_empty_source_unchanged(self):
        target = {'a100': 2}
        add_gpu_type_counts(target, {})
        assert target == {'a100': 2}

    def test_empty_target_filled_from_source(self):
        target: dict[str, int] = {}
        add_gpu_type_counts(target, {'a100': 4})
        assert target == {'a100': 4}

    def test_both_empty(self):
        target: dict[str, int] = {}
        add_gpu_type_counts(target, {})
        assert target == {}


# ---------------------------------------------------------------------------
# collect_display_gpu_types — determines which GPU types to show in tables
# ---------------------------------------------------------------------------


class TestCollectDisplayGpuTypes:
    def test_empty_input_returns_empty(self):
        assert collect_display_gpu_types([]) == []

    def test_single_type_returned(self):
        result = collect_display_gpu_types([{'rtx_a5000': 4}])
        assert 'rtx_a5000' in result

    def test_zero_count_type_excluded(self):
        result = collect_display_gpu_types([{'rtx_a5000': 4, 'a100': 0}])
        assert 'rtx_a5000' in result
        assert 'a100' not in result

    def test_display_order_respected(self):
        result = collect_display_gpu_types([{'rtx_a5000': 4, 'gtx_1080ti': 2}])
        assert 'rtx_a5000' in result
        assert 'gtx_1080ti' in result
        assert result.index('rtx_a5000') < result.index('gtx_1080ti')

    def test_type_not_deduplicated_across_maps(self):
        result = collect_display_gpu_types([{'rtx_a5000': 4}, {'rtx_a5000': 2}])
        assert result.count('rtx_a5000') == 1

    def test_types_from_multiple_maps_combined(self):
        result = collect_display_gpu_types([{'a100': 2}, {'h100': 4}])
        assert 'a100' in result
        assert 'h100' in result


# ---------------------------------------------------------------------------
# format_gpu_type_header
# ---------------------------------------------------------------------------


class TestFormatGpuTypeHeader:
    def test_with_prefix(self):
        assert format_gpu_type_header('Free ', 'rtx_a5000') == 'Free A5000'

    def test_without_prefix(self):
        assert format_gpu_type_header('', 'rtx_a5000') == 'A5000'

    def test_generic_type(self):
        assert format_gpu_type_header('', 'generic') == 'GPU'


def test_node_heading_leaves_out_system_memory():
    # same SpecMem math as `ab free --nodes`: (92000 - 2048) MB free is 88G, not 90G
    console = Console(record=True, width=120)
    with (
        patch.object(
            resources, 'load_nodes', return_value=[node_dict('gpu081', spec_mem=2048)]
        ),
        patch.object(resources, 'load_running_jobs', return_value=[]),
        patch.object(resources, 'CONSOLE', console),
    ):
        resources.cmd_node(node='gpu081')
    assert '88/88G mem' in console.export_text()


class TestFreeNodes:
    def test_sorted_filtered_and_reserved_nodes_for_the_user(self):
        nodes = [
            node_dict('gpu1', gpus_used=3),
            node_dict('gpu2', gpus_used=1),
            node_dict('gpu3', state='MAINT+RESERVED', gpus_used=0),
            node_dict('gpu4', state='MAINT+RESERVED', gpus_used=0),
            node_dict('cmp1', gres='(null)'),
            node_dict('gpu5', partitions='other'),
        ]
        resv = {'ReservationName': 'mine', 'Users': 'alice'}
        with patch.object(resources, 'current_user', lambda: 'alice'):
            entries = resources._free_nodes(
                nodes, {'gpu'}, kind='gpu', gpu_type=None, reserved_by={'gpu3': resv}
            )
        assert [(e.name, e.state, e.gpu_free) for e in entries] == [
            ('gpu3', 'RESERVED', 4),
            ('gpu2', 'MIXED', 3),
            ('gpu1', 'MIXED', 1),
        ]
