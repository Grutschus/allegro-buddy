"""Tests for free-GPU count accuracy.

GPU free counts are read directly from node GresUsed fields (populated via
scontrol --json show nodes). No job scanning is needed for partition stats.

  summarize_partitions(nodes=...)
    → reads Gres (total) and GresUsed (allocated) directly from each node
    → gpu_free  = GPUs not assigned (from GresUsed)
    → gpu_usable = gpu_free on IDLE or MIXED nodes only
"""
from __future__ import annotations

from allegro_buddy.core import (
    empty_partition_stats,
    summarize_partitions,
    summarize_selected_partitions,
)

# ---------------------------------------------------------------------------
# Fixtures — nodes include GresUsed as returned by scontrol --json
# ---------------------------------------------------------------------------


def _node(
    name: str,
    state: str,
    gres: str,
    partitions: str,
    gres_used: str = '',
    cpu_tot: int = 48,
    cpu_alloc: int = 0,
    mem_mb: int = 256000,
    alloc_mem_mb: int = 0,
) -> dict[str, str]:
    return {
        'NodeName': name,
        'State': state,
        'CPUTot': str(cpu_tot),
        'CPUAlloc': str(cpu_alloc),
        'RealMemory': str(mem_mb),
        'AllocMem': str(alloc_mem_mb),
        'Gres': gres,
        'GresUsed': gres_used,
        'Partitions': partitions,
        'ActiveFeatures': '',
    }


def _fake_partition(name: str, allow_groups: str = 'ALL') -> dict[str, str]:
    return {'PartitionName': name, 'AllowGroups': allow_groups, 'MaxTime': '1-00:00:00'}


# ---------------------------------------------------------------------------
# summarize_partitions
# ---------------------------------------------------------------------------


class TestSummarizePartitionsFreeGpus:
    def _run(
        self,
        partitions: list[dict[str, str]],
        nodes: list[dict[str, str]],
    ) -> dict:
        return summarize_partitions([p['PartitionName'] for p in partitions], nodes=nodes)

    def test_idle_node_no_usage_all_gpus_free_and_usable(self):
        partitions = [_fake_partition('gpusmall')]
        # Slurm reports 0 used as gpu:TYPE:0(IDX:N/A)
        nodes = [_node('gpu001', 'IDLE', 'gpu:RTX-A5000:4', 'gpusmall',
                        gres_used='gpu:RTX-A5000:0(IDX:N/A)')]
        result = self._run(partitions, nodes)

        s = result['gpusmall']
        assert s['gpu_total'] == 4
        assert s['gpu_free'] == 4
        assert s['gpu_usable'] == 4

    def test_gres_used_reduces_free_count(self):
        partitions = [_fake_partition('gpusmall')]
        nodes = [_node('gpu001', 'MIXED', 'gpu:RTX-A5000:4', 'gpusmall',
                        gres_used='gpu:RTX-A5000:2(IDX:0-1)')]
        result = self._run(partitions, nodes)

        s = result['gpusmall']
        assert s['gpu_total'] == 4
        assert s['gpu_free'] == 2
        assert s['gpu_usable'] == 2
        assert s['gpu_free_by_type'].get('rtx_a5000') == 2

    def test_fully_allocated_node_has_zero_free(self):
        partitions = [_fake_partition('gpusmall')]
        nodes = [_node('gpu001', 'ALLOCATED', 'gpu:RTX-A5000:4', 'gpusmall',
                        gres_used='gpu:RTX-A5000:4(IDX:0-3)')]
        result = self._run(partitions, nodes)

        s = result['gpusmall']
        assert s['gpu_free'] == 0
        assert s['gpu_usable'] == 0

    def test_drained_node_excluded(self):
        partitions = [_fake_partition('gpusmall')]
        nodes = [_node('gpu001', 'IDLE+DRAIN', 'gpu:RTX-A5000:4', 'gpusmall')]
        result = self._run(partitions, nodes)
        assert result['gpusmall']['gpu_total'] == 0

    def test_allocated_node_partially_used_not_usable(self):
        """ALLOCATED node: some GPUs free but node won't accept new jobs."""
        partitions = [_fake_partition('gpusmall')]
        nodes = [_node('gpu001', 'ALLOCATED', 'gpu:RTX-A5000:4', 'gpusmall',
                        gres_used='gpu:RTX-A5000:2(IDX:0,1)')]
        result = self._run(partitions, nodes)

        s = result['gpusmall']
        assert s['gpu_free'] == 2
        assert s['gpu_usable'] == 0

    def test_two_nodes_counts_summed(self):
        partitions = [_fake_partition('gpusmall')]
        nodes = [
            _node('gpu001', 'IDLE', 'gpu:RTX-A5000:4', 'gpusmall',
                  gres_used='gpu:RTX-A5000:0(IDX:N/A)'),
            _node('gpu002', 'MIXED', 'gpu:RTX-A5000:4', 'gpusmall',
                  gres_used='gpu:RTX-A5000:2(IDX:0,1)'),
        ]
        result = self._run(partitions, nodes)

        s = result['gpusmall']
        assert s['nodes'] == 2
        assert s['gpu_total'] == 8
        assert s['gpu_free'] == 6    # 4 + (4-2)
        assert s['gpu_usable'] == 6  # both IDLE/MIXED

    def test_node_in_multiple_partitions_counted_in_each(self):
        partitions = [_fake_partition('gpusmall'), _fake_partition('gpu')]
        nodes = [_node('gpu001', 'IDLE', 'gpu:RTX-A5000:4', 'gpusmall,gpu',
                        gres_used='gpu:RTX-A5000:0(IDX:N/A)')]
        result = self._run(partitions, nodes)

        assert result['gpusmall']['gpu_total'] == 4
        assert result['gpu']['gpu_total'] == 4

    def test_down_node_excluded(self):
        partitions = [_fake_partition('gpusmall')]
        nodes = [
            _node('gpu001', 'IDLE', 'gpu:RTX-A5000:4', 'gpusmall'),
            _node('gpu002', 'DOWN', 'gpu:RTX-A5000:4', 'gpusmall'),
        ]
        result = self._run(partitions, nodes)

        s = result['gpusmall']
        assert s['nodes'] == 1
        assert s['gpu_total'] == 4

    def test_empty_partition_returns_zeros(self):
        partitions = [_fake_partition('gpusmall')]
        result = self._run(partitions, nodes=[])
        assert result['gpusmall'] == empty_partition_stats()

    def test_idle_node_count(self):
        partitions = [_fake_partition('gpusmall')]
        nodes = [
            _node('gpu001', 'IDLE', 'gpu:RTX-A5000:4', 'gpusmall',
                  gres_used='gpu:RTX-A5000:0(IDX:N/A)'),
            _node('gpu002', 'MIXED', 'gpu:RTX-A5000:4', 'gpusmall',
                  gres_used='gpu:RTX-A5000:2(IDX:0-1)'),
            _node('gpu003', 'ALLOCATED', 'gpu:RTX-A5000:4', 'gpusmall',
                  gres_used='gpu:RTX-A5000:4(IDX:0-3)'),
        ]
        result = self._run(partitions, nodes)

        s = result['gpusmall']
        assert s['nodes'] == 3
        assert s['idle_nodes'] == 1
        # 4 free on IDLE + 2 free on MIXED + 0 free on ALLOCATED = 6
        assert s['gpu_free'] == 6
        # usable excludes ALLOCATED node, so only IDLE + MIXED count
        assert s['gpu_usable'] == 6

    def test_free_count_cannot_go_negative(self):
        """Data inconsistency (GresUsed > Gres) should clamp to 0."""
        partitions = [_fake_partition('gpusmall')]
        nodes = [_node('gpu001', 'MIXED', 'gpu:RTX-A5000:4', 'gpusmall',
                        gres_used='gpu:RTX-A5000:6')]
        result = self._run(partitions, nodes)

        s = result['gpusmall']
        assert s['gpu_free'] == 0
        assert s['gpu_usable'] == 0


# ---------------------------------------------------------------------------
# summarize_selected_partitions
# ---------------------------------------------------------------------------


class TestSummarizeSelectedPartitions:
    def test_empty_partition_set_returns_zero_stats(self):
        result = summarize_selected_partitions(set(), nodes=[])
        assert result == empty_partition_stats()

    def test_counts_only_nodes_in_selected_partitions(self):
        nodes = [
            _node('gpu001', 'IDLE', 'gpu:RTX-A5000:4', 'gpusmall,gpu'),
            _node('cmp001', 'IDLE', '(null)', 'small'),
        ]
        result = summarize_selected_partitions({'gpusmall'}, nodes=nodes)
        assert result['nodes'] == 1
        assert result['gpu_total'] == 4

    def test_gpu_free_from_gres_used(self):
        nodes = [_node('gpu001', 'MIXED', 'gpu:RTX-A5000:4', 'gpusmall',
                        gres_used='gpu:RTX-A5000:1(IDX:0)')]
        result = summarize_selected_partitions({'gpusmall'}, nodes=nodes)
        assert result['gpu_free'] == 3
        assert result['gpu_usable'] == 3

    def test_multiple_partitions_merged(self):
        nodes = [
            _node('gpu001', 'IDLE', 'gpu:RTX-A5000:4', 'gpusmall'),
            _node('gpu002', 'IDLE', 'gpu:RTX-A5000:4', 'gpu'),
        ]
        result = summarize_selected_partitions({'gpusmall', 'gpu'}, nodes=nodes)
        assert result['gpu_total'] == 8
