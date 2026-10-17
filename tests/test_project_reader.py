import io
import json

import pytest

from osa.persistence.project_reader import ProjectReader


@pytest.mark.parametrize("chunk_size", [1, 2, 7, 31, 128, 4096])
@pytest.mark.parametrize("indent", [None, 2])
def test_incremental_reader_preserves_values_across_buffer_boundaries(chunk_size, indent):
    data = {
        "format": "open-structural-analysis/v2",
        "nodes": [{"name": "Nó \\\" [}]", "x": -123.456e90, "y": 1e-90, "z": 0}],
        "members": [],
        "results": [{
            "model_revision": 1,
            "load_reference": "Combinação 01",
            "node_results": {"Nó": {"dx": -12.3e-10, "ok": True, "empty": None}},
            "member_results": {"B1": {"samples": [{"x": i / 7, "value": i} for i in range(90)]}},
        }],
        "thumbnail": {"format": "png", "data": "prévia \\\" {[}]" * 10},
    }
    source = json.dumps(data, ensure_ascii=False, indent=indent)

    assert ProjectReader(io.StringIO(source), chunk_size=chunk_size).read() == data


@pytest.mark.parametrize("chunk_size", [1, 2, 7, 128])
@pytest.mark.parametrize("preview_position", [0, 1, 2])
def test_preview_reader_skips_nested_values_and_escaped_strings(chunk_size, preview_position):
    fields = [
        ("members", [{"text": 'quote: " slash: \\ braces: { [ } ]'}] * 3),
        ("results", [{"member_results": {"B1": {"samples": [1, 2, 3]}}}]),
    ]
    thumbnail = {"format": "png", "data": "base64-preview"}
    fields.insert(preview_position, ("thumbnail", thumbnail))
    source = json.dumps(dict(fields))

    assert ProjectReader(io.StringIO(source), chunk_size=chunk_size).read_thumbnail() == thumbnail


@pytest.mark.parametrize("source", [
    '{"nodes": [1,]}', '{"results": [{"node_results": {"N1": 1,}}]}',
    '{"nodes": [1]} trailing', '{"nodes": [1]', '{"x": 1e}',
])
def test_incremental_reader_rejects_malformed_json(source):
    with pytest.raises(json.JSONDecodeError):
        ProjectReader(io.StringIO(source), chunk_size=2).read()


def test_preview_reader_handles_missing_preview_without_materializing_results():
    reader = ProjectReader(io.StringIO('{"results": [{"samples": [1,2,3]}]}'), chunk_size=7)

    assert reader.read_thumbnail() is None
